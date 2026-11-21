#!/usr/bin/env python3
"""Turn runtime coverage plus the static manifest into coverage seeds.

This is the analysis half of the headless discovery loop. It reads tier-2
capture checkpoints/journals and the program manifest for the same build, then
reports two things side by side:

* **function boundaries** — every variant the analyzer decoded, its extent and
  its declared boundary exits;
* **runtime hits** — where the interpreter actually executed, aggregated per
  exact ``(pc24, M, X)`` variant with its observed/completed/yielded/bail
  counters.

Gate-passing hits are written to ``recomp/symbols.toml`` as ``emit = true``
rows so the next analyze step takes them as explicit roots. Everything else is
reported as a ranked candidate; ``--write-candidates`` opts into seeding those
as ``emit = false`` (force-LLE) instead.

The report is strict JSON. JSON is a subset of HJSON, so it also parses with an
HJSON reader; the repository deliberately carries no HJSON dependency.

Promotion here is an *analysis-root request*, not proof of AOT correctness. The
analyzer still classifies each variant as AOT-eligible or LLE-only, and replay
validation remains required before release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import tempfile
from dataclasses import dataclass, field

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
for _path in (REPO / "recompiler", REPO / "tools"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from sync_symbols import (  # noqa: E402
    FunctionSymbol,
    load_symbols,
)
from v2.cfg_loader import load_bank_cfg  # noqa: E402
from v2.coverage_profile import (  # noqa: E402
    canonical_pc,
    execution_pc,
    load_profiles,
    pc,
    promotion_reason,
)
from v2.program_analysis import ProgramManifest, VariantKey  # noqa: E402


SCHEMA = "snesrecomp coverage discovery report v1"
COUNTERS = ("observed_hits", "completed_hits", "yielded_hits", "bail_hits",
            "pending_hits")
_PROMOTABLE = "candidate_requires_analysis_and_replay"
_BANK_CFG = re.compile(r"bank([0-9a-fA-F]{2})")


def _hex24(value: int) -> str:
    return f"{value & 0xFFFFFF:06X}"


def _variant_text(pc24: int, entry_mx: str) -> str:
    return f"{_hex24(pc24)}:{entry_mx}"


def _entry_modes(entry_mx: str):
    """Parse the capture's ``M[01]X[01]`` tag, or return None."""
    text = str(entry_mx or "")
    if len(text) != 4 or text[0] != "M" or text[2] != "X":
        return None
    if text[1] not in "01" or text[3] not in "01":
        return None
    return int(text[1]), int(text[3])


def _atomic_write(path: pathlib.Path, text: str) -> None:
    path = pathlib.Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.tmp-", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


@dataclass
class StaticView:
    """Cfg and manifest facts used to gate and name candidate roots."""

    parsed: list = field(default_factory=list)
    declared: set = field(default_factory=set)
    force_lle: set = field(default_factory=set)
    names: dict = field(default_factory=dict)
    manifest: ProgramManifest | None = None
    nodes: dict = field(default_factory=dict)
    extents: list = field(default_factory=list)

    def exclusion_reason(self, target_pc24: int):
        bank = target_pc24 >> 16
        addr = target_pc24 & 0xFFFF
        for cfg_bank, _path, cfg in self.parsed:
            if cfg_bank != bank:
                continue
            for start, end in cfg.exclude_ranges:
                if start <= addr < end:
                    return "exclude_range"
            for region_bank, start, end in cfg.data_regions:
                if region_bank == bank and start <= addr < end:
                    return "data_region"
        return None

    def extent_owner(self, target_pc24: int, entry_mx: str):
        """Return the extent that contains ``target_pc24`` from another entry."""
        modes = _entry_modes(entry_mx)
        for node in self.nodes.values():
            key = node.key
            if key.pc24 == target_pc24:
                continue
            if modes is not None and (key.m, key.x) == modes:
                # The exact variant is itself an analyzed entry.
                continue
            if node.min_pc24 <= target_pc24 <= node.max_pc24:
                return node
        return None


def _load_static(cfg_dir: pathlib.Path, manifest_path) -> StaticView:
    view = StaticView()
    for path in sorted(cfg_dir.glob("bank*.cfg")):
        match = _BANK_CFG.fullmatch(path.stem)
        if not match:
            continue
        bank = int(match[1], 16)
        cfg = load_bank_cfg(str(path))
        view.parsed.append((bank, path, cfg))
        for entry in cfg.entries:
            pc24 = (bank << 16) | (entry.start & 0xFFFF)
            view.declared.add(pc24)
            view.names.setdefault(pc24, entry.name)
        for declaration in (*cfg.symbols, *cfg.names):
            view.names.setdefault(declaration.addr_24 & 0xFFFFFF,
                                  declaration.name)
        for forced in cfg.force_lle:
            view.force_lle.add(forced & 0xFFFFFF)

    if manifest_path is not None:
        raw = pathlib.Path(manifest_path).read_bytes()
        view.manifest = ProgramManifest.from_dict(json.loads(raw))
        view.nodes = dict(view.manifest.nodes)
        view.extents = [
            (node.key, node.min_pc24, node.max_pc24)
            for node in view.manifest.nodes.values()
        ]
    return view


def _aggregate(profile, static: StaticView) -> list[dict]:
    """Group discovery rows into one record per canonical (pc24, M, X)."""
    mapper = profile.identity.get("mapper")
    groups: dict[tuple, dict] = {}
    for row in profile.discoveries:
        if row.get("record_kind", "transfer") != "transfer":
            continue
        target = canonical_pc(row["target_pc24"], mapper)
        entry_mx = str(row.get("entry_mx", "unknown"))
        key = (target, entry_mx)
        group = groups.get(key)
        if group is None:
            group = groups[key] = {
                "target_pc24": target,
                "entry_mx": entry_mx,
                "sites": [],
                "counters": {name: 0 for name in COUNTERS},
                "emulations": set(),
                "missing_emulation": False,
                "site_kinds": set(),
                "legacy": False,
                "reasons": [],
            }
        for name in COUNTERS:
            group["counters"][name] += int(row.get(name, 0))
        if "emulation" in row:
            group["emulations"].add(row.get("emulation"))
        if row.get("emulation") is None and not row.get("legacy"):
            group["missing_emulation"] = True
        group["site_kinds"].add(row.get("site_kind", "unknown"))
        group["legacy"] = group["legacy"] or bool(row.get("legacy"))
        reason = promotion_reason(row, static.declared, profile.identity)
        group["reasons"].append(reason)
        group["sites"].append({
            "site_pc24": execution_pc(row.get("site_pc24", 0), mapper),
            "site_kind": row.get("site_kind", "unknown"),
            "fallback_reason": row.get("fallback_reason", "unknown"),
            "emulation": row.get("emulation"),
            "counters": {name: int(row.get(name, 0)) for name in COUNTERS},
            "promotion_reason": reason,
        })
    return [groups[key] for key in sorted(groups)]


def _classify(group: dict, profile, static: StaticView,
              seeded: set) -> dict:
    """Apply the promotion gates and return the report row."""
    target = group["target_pc24"]
    entry_mx = group["entry_mx"]
    modes = _entry_modes(entry_mx)
    counters = group["counters"]
    hits = sum(counters[name] for name in
               ("observed_hits", "completed_hits", "yielded_hits"))
    blockers: list[str] = []

    if counters["bail_hits"]:
        blockers.append("bailed_requires_investigation")
    if target in {canonical_pc(value, profile.identity.get("mapper"))
                  for value in profile.unsafe_targets}:
        blockers.append("unsafe_aot_target")
    if hits == 0:
        blockers.append("no_execution_evidence")
    if modes is None:
        blockers.append("missing_entry_width")
    if any(value not in (0, None) for value in group["emulations"]):
        blockers.append("emulation_mode_requires_analysis_support")
    if group["missing_emulation"]:
        blockers.append("missing_emulation_mode")
    if target >> 16 in (0x7E, 0x7F):
        blockers.append("ram_requires_decoded_snapshot_and_guard")

    # A declared boundary makes a goto/tail landing an admissible entry; a
    # hardware call landing is admissible on its own.
    if target not in static.declared and "call_gap" not in group["site_kinds"]:
        blockers.append("landing_requires_function_boundary")

    if _PROMOTABLE not in group["reasons"]:
        # Keep the most specific non-promotable explanation from the rows.
        other = next((reason for reason in group["reasons"]
                      if reason != _PROMOTABLE), "no_promotion_evidence")
        blockers.append(other)

    action = "candidate"
    if not blockers:
        exclusion = static.exclusion_reason(target)
        if exclusion is not None:
            blockers.append(exclusion)
        else:
            owner = static.extent_owner(target, entry_mx)
            if owner is not None:
                blockers.append(
                    f"inside_analyzed_extent:{_hex24(owner.key.pc24)}")

    if not blockers:
        node = static.nodes.get(VariantKey(
            target, modes[0], modes[1])) if modes is not None else None
        if node is not None:
            if node.disposition.value == "aot_eligible":
                action = "covered"
                blockers.append("already_aot_eligible")
            else:
                blockers.append("analysis_rejected_variant")
        elif target in static.force_lle:
            blockers.append("force_lle_declared")
        elif modes is not None and (target, modes[0], modes[1]) in seeded:
            action = "seeded"
            blockers.append("already_seeded")
        elif target in static.declared:
            action = "declared"
            blockers.append("already_declared_function")

    if not blockers:
        action = "promote"

    return {
        "variant": _variant_text(target, entry_mx),
        "target_pc24": target,
        "target": _hex24(target),
        "entry_mx": entry_mx,
        "emulation": sorted(
            value for value in group["emulations"] if value is not None),
        "site_kinds": sorted(group["site_kinds"]),
        "hits": hits,
        **counters,
        "sites": group["sites"],
        "analysis_disposition": (
            static.nodes[VariantKey(target, modes[0], modes[1])].disposition.value
            if modes is not None and VariantKey(target, modes[0], modes[1])
            in static.nodes else None),
        "action": action,
        "blocking_reasons": sorted(set(blockers)),
    }


def _functions(static: StaticView) -> list[dict]:
    by_pc: dict[int, dict] = {}
    for node in sorted(static.nodes.values(), key=lambda item: item.key):
        entry = by_pc.setdefault(node.key.pc24, {
            "pc24": node.key.pc24,
            "pc": _hex24(node.key.pc24),
            "name": static.names.get(node.key.pc24),
            "declared": node.key.pc24 in static.declared,
            "extent": {"min_pc24": node.min_pc24, "max_pc24": node.max_pc24},
            "variants": [],
            "boundary_exits": [],
        })
        entry["extent"]["min_pc24"] = min(
            entry["extent"]["min_pc24"], node.min_pc24)
        entry["extent"]["max_pc24"] = max(
            entry["extent"]["max_pc24"], node.max_pc24)
        entry["variants"].append({
            "entry_mx": f"M{node.key.m}X{node.key.x}",
            "disposition": node.disposition.value,
            "instruction_count": node.instruction_count,
            "reasons": list(node.reasons),
        })
        for exit_ in node.boundary_exits:
            entry["boundary_exits"].append({
                "site_pc24": exit_.site_pc24,
                "site": _hex24(exit_.site_pc24),
                "target_pc24": exit_.target.pc24,
                "target": _hex24(exit_.target.pc24),
                "target_entry_mx": f"M{exit_.target.m}X{exit_.target.x}",
            })
    for entry in by_pc.values():
        entry["boundary_exits"].sort(
            key=lambda item: (item["site_pc24"], item["target_pc24"],
                              item["target_entry_mx"]))
    return [by_pc[key] for key in sorted(by_pc)]


def _rank(candidates: list[dict], costs: dict) -> None:
    def score(row):
        cost = costs.get((row["target_pc24"], row["entry_mx"]), (0, 0))
        return (4 * row["completed_hits"] + 2 * row["yielded_hits"]
                + row["observed_hits"], cost[1], cost[0])

    candidates.sort(key=lambda row: (
        tuple(-value for value in score(row)), row["target_pc24"],
        row["entry_mx"]))
    for index, row in enumerate(candidates, 1):
        row["rank"] = index
        cost = costs.get((row["target_pc24"], row["entry_mx"]), (0, 0))
        row["interpreted_instructions"], row["guest_cycles"] = cost


def _costs(profile, mapper) -> dict:
    result: dict[tuple, list[int]] = {}
    for row in profile.costs:
        target = canonical_pc(row["target_pc24"], mapper)
        key = (target, str(row.get("entry_mx", "unknown")))
        value = result.setdefault(key, [0, 0])
        value[0] += int(row.get("interpreted_instructions", 0))
        value[1] += int(row.get("guest_cycles", 0))
    return {key: tuple(value) for key, value in result.items()}


def _seed_name(target_pc24: int, static: StaticView, used: dict) -> str:
    existing = static.names.get(target_pc24)
    if existing:
        return existing
    base = f"bank_{target_pc24 >> 16:02X}_{target_pc24 & 0xFFFF:04X}"
    name = base
    suffix = 2
    while name in used and used[name] != target_pc24:
        name = f"{base}_{suffix}"
        suffix += 1
    used[name] = target_pc24
    return name


def _read_seed_rows(path: pathlib.Path) -> list[FunctionSymbol]:
    if not path.is_file():
        return []
    return load_symbols(path)


def _toml_row(name: str, target_pc24: int, entry_mx: str,
              emit: bool) -> str:
    modes = _entry_modes(entry_mx)
    assert modes is not None
    return (
        "[[func]]\n"
        f'name = "{name}"\n'
        f'addr = "{target_pc24 & 0xFFFF:04x}"\n'
        f"bank = 0x{target_pc24 >> 16:02x}\n"
        f"emit = {str(emit).lower()}\n"
        f"entry_m = {modes[0]}\n"
        f"entry_x = {modes[1]}\n"
    )


def write_seeds(path: pathlib.Path, rows: list[dict], *,
                write_candidates: bool, static: StaticView,
                dry_run: bool = False) -> dict:
    """Append seed rows for variants not already present; keep the rest."""
    path = pathlib.Path(path)
    existing = _read_seed_rows(path)
    existing_keys = {(row.pc24, row.entry_m, row.entry_x) for row in existing}
    existing_emit = {row.pc24: row.emit for row in existing}
    used_names = {row.name: row.pc24 for row in existing}
    for pc24, name in static.names.items():
        used_names.setdefault(name, pc24)
    promoted_pc24 = {row["target_pc24"] for row in rows
                     if row["action"] == "promote"}

    written, skipped = [], []
    additions = []
    for row in rows:
        if row["action"] != "promote" and not (
                write_candidates and row["action"] == "candidate"):
            continue
        modes = _entry_modes(row["entry_mx"])
        if modes is None:
            skipped.append({"variant": row["variant"],
                            "reason": "missing_entry_width"})
            continue
        key = (row["target_pc24"], modes[0], modes[1])
        if key in existing_keys:
            skipped.append({"variant": row["variant"],
                            "reason": "already_seeded"})
            continue
        emit = row["action"] == "promote"
        # `emit` and force_lle are per pc24; never seed a tier that fights an
        # existing row or a promotion for another variant of the same address.
        if existing_emit.get(row["target_pc24"], emit) != emit or (
                not emit and row["target_pc24"] in promoted_pc24):
            skipped.append({"variant": row["variant"],
                            "reason": "tier_conflict_at_address"})
            continue
        name = _seed_name(row["target_pc24"], static, used_names)
        additions.append(_toml_row(name, row["target_pc24"],
                                   row["entry_mx"], emit))
        existing_keys.add(key)
        existing_emit[row["target_pc24"]] = emit
        written.append({"variant": row["variant"], "name": name,
                        "emit": emit})

    if additions and not dry_run:
        text = path.read_text(encoding="utf-8") if path.is_file() else (
            "# snesrecomp analysis seeds.\n"
            "# Generated rows are appended by tools/discover_report.py.\n")
        if not text.endswith("\n"):
            text += "\n"
        text += "\n" + "".join(additions)
        _atomic_write(path, text)
    return {
        "path": str(path),
        "written": written,
        "skipped": skipped,
        "dry_run": bool(dry_run),
    }


def build_report(*, captures, cfg_dir, program_manifest=None,
                 expected_rom=None, legacy_rom=None) -> dict:
    cfg_dir = pathlib.Path(cfg_dir)
    if not cfg_dir.is_dir():
        raise ValueError(f"cfg-dir is not a directory: {cfg_dir}")
    static = _load_static(cfg_dir, program_manifest)
    profile = load_profiles(list(captures), expected_rom=expected_rom,
                            legacy_rom=legacy_rom)
    if program_manifest is not None:
        # The capture records the digest of the manifest that produced the
        # build it ran on. A manifest from a later regeneration describes a
        # different executable, so joining the two would attribute analysis
        # results to code that never executed. Same rule, same message as
        # tools/tier2_ingest.py.
        expected_digest = profile.identity.get("program_digest")
        actual_digest = hashlib.sha256(
            pathlib.Path(program_manifest).read_bytes()).hexdigest()
        if expected_digest and actual_digest != expected_digest:
            raise ValueError(
                "program manifest differs from captured build; supply the "
                "original generated manifest")
    seed_path = cfg_dir / "symbols.toml"
    seeded = {(row.pc24, row.entry_m, row.entry_x)
              for row in _read_seed_rows(seed_path)}
    hits = [_classify(group, profile, static, seeded)
            for group in _aggregate(profile, static)]
    costs = _costs(profile, profile.identity.get("mapper"))
    promotions = [row for row in hits if row["action"] == "promote"]
    candidates = [row for row in hits if row["action"] == "candidate"]
    _rank(candidates, costs)
    for row in hits:
        if row["action"] != "candidate":
            row["rank"] = None
            cost = costs.get((row["target_pc24"], row["entry_mx"]), (0, 0))
            row["interpreted_instructions"], row["guest_cycles"] = cost

    report = {
        "schema": SCHEMA,
        "identity": profile.identity,
        "capture_count": len(profile.captures),
        "warnings": sorted(set(profile.warnings)),
        "cost_attribution": (
            "exclusive instruction PC, entry M/X and E; never inferred "
            "function ownership"),
        "summary": {
            "function_boundaries": len({node.key.pc24
                                        for node in static.nodes.values()}),
            "analyzed_variants": len(static.nodes),
            "runtime_variants": len(hits),
            "promotions": len(promotions),
            "candidates": len(candidates),
            "covered": sum(row["action"] == "covered" for row in hits),
            "seeded": sum(row["action"] == "seeded" for row in hits),
            "declared": sum(row["action"] == "declared" for row in hits),
        },
        "functions": _functions(static),
        "runtime_hits": hits,
        "promotions": [row["variant"] for row in promotions],
        "candidates": [
            {
                "rank": row["rank"],
                "variant": row["variant"],
                "target": row["target"],
                "entry_mx": row["entry_mx"],
                "hits": row["hits"],
                "interpreted_instructions": row["interpreted_instructions"],
                "guest_cycles": row["guest_cycles"],
                "blocking_reasons": row["blocking_reasons"],
            }
            for row in candidates
        ],
    }
    return report, static, hits, seed_path


def _print_summary(report: dict, seeds: dict, stream) -> None:
    summary = report["summary"]
    print(f"discover: {summary['runtime_variants']} runtime variant(s) from "
          f"{report['capture_count']} capture(s)", file=stream)
    print(f"discover: {summary['function_boundaries']} analyzed function "
          f"boundary(ies), {summary['analyzed_variants']} variant(s)",
          file=stream)
    print(f"discover: {summary['promotions']} promotion(s), "
          f"{summary['candidates']} candidate(s), "
          f"{summary['covered']} already covered", file=stream)
    for warning in report["warnings"]:
        print(f"discover: warning: {warning}", file=stream)
    if seeds is not None:
        print(f"discover: seeds -> {seeds['path']} "
              f"({len(seeds['written'])} row(s)"
              f"{', dry run' if seeds['dry_run'] else ''})", file=stream)
        for row in seeds["written"]:
            print(f"  {row['variant']} {row['name']} "
                  f"emit={str(row['emit']).lower()}", file=stream)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="append", required=True,
                        help="tier-2 checkpoint/journal/bundle (repeatable)")
    parser.add_argument("--cfg-dir", required=True,
                        help="directory containing bank*.cfg and symbols.toml")
    parser.add_argument("--program-manifest", type=pathlib.Path,
                        help="program manifest from the captured build")
    parser.add_argument("--out", type=pathlib.Path,
                        help="write the JSON report here instead of stdout")
    parser.add_argument("--symbols", type=pathlib.Path,
                        help="seed file (default: <cfg-dir>/symbols.toml)")
    parser.add_argument("--write-candidates", action="store_true",
                        help="also seed report-only candidates as emit=false")
    parser.add_argument("--no-write-seeds", action="store_true",
                        help="report only; do not modify symbols.toml")
    parser.add_argument("--dry-run", action="store_true",
                        help="compute seeds without writing symbols.toml")
    parser.add_argument("--rom-sha256",
                        help="require captures to match this ROM SHA-256")
    parser.add_argument("--legacy-profile-rom-sha256",
                        help="explicitly bind an unbound v1 profile to this ROM")
    args = parser.parse_args(argv)

    try:
        report, static, hits, default_seed_path = build_report(
            captures=args.capture,
            cfg_dir=pathlib.Path(args.cfg_dir),
            program_manifest=args.program_manifest,
            expected_rom=args.rom_sha256,
            legacy_rom=args.legacy_profile_rom_sha256,
        )
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    if args.program_manifest is None:
        report["warnings"].append(
            "no program manifest: function boundaries are absent and "
            "promotions cannot check extent overlap")

    seeds = None
    if not args.no_write_seeds:
        seed_path = args.symbols or default_seed_path
        seeds = write_seeds(
            seed_path, hits, write_candidates=args.write_candidates,
            static=static, dry_run=args.dry_run)
        report["seeds"] = seeds
    else:
        report["seeds"] = None

    text = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.out is not None:
        _atomic_write(args.out, text)
        _print_summary(report, seeds, sys.stdout)
    else:
        sys.stdout.write(text)
        _print_summary(report, seeds, sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
