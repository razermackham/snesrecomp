"""The runtime -> analysis seed loop: discovery report and symbols.toml seeds."""

import json
import hashlib
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "tools"), str(REPO / "recompiler")]

import discover_report  # noqa: E402
from sync_symbols import sync_symbols  # noqa: E402
from v2.cfg_loader import load_bank_cfg  # noqa: E402

ROM = "a" * 64


def capture(rows, *, session="one", seq=3, **identity):
    return {
        "schema": "snesrecomp tier2 coverage v2",
        "capture_id": session,
        "sequence": seq,
        "identity": {
            "rom_sha256": ROM,
            "module_id": "main",
            "mapper": "lorom",
            "program_digest": "b" * 64,
            **identity,
        },
        "discoveries": rows,
    }


def row(**kwargs):
    values = dict(site_pc24="0x808000", target_pc24="0x808100",
                  entry_mx="M0X1", emulation=0, site_kind="call_gap",
                  observed_hits=1)
    values.update(kwargs)
    return values


def node(pc24, m, x, min_pc24=None, max_pc24=None, disposition="aot_eligible",
         boundary_exits=()):
    return {
        "key": {"pc24": pc24, "m": m, "x": x},
        "disposition": disposition,
        "instruction_count": 2,
        "min_pc24": pc24 if min_pc24 is None else min_pc24,
        "max_pc24": pc24 if max_pc24 is None else max_pc24,
        "demands": [],
        "boundary_exits": [
            {"site_pc24": site,
             "target": {"pc24": target, "m": tm, "x": tx}}
            for site, target, tm, tx in boundary_exits
        ],
        "reasons": [],
        "digest": "native",
    }


def manifest(*nodes):
    return {
        "format_version": 3,
        "roots": [],
        "exit_modes": {},
        "exit_mode_sets": {},
        "nodes": {f"{item['key']['pc24']:06X}:M{item['key']['m']}X"
                  f"{item['key']['x']}": item for item in nodes},
    }


def setup_project(tmp_path, *, captures, program=None, cfg_lines=()):
    cfg = tmp_path / "recomp"
    cfg.mkdir()
    (cfg / "bank00.cfg").write_text(
        "bank = 00\n" + "".join(line + "\n" for line in cfg_lines),
        encoding="utf-8")
    paths = []
    for index, document in enumerate(captures):
        path = tmp_path / f"capture{index}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths.append(path)
    manifest_path = None
    if program is not None:
        manifest_path = tmp_path / "program_manifest.json"
        manifest_path.write_text(json.dumps(program), encoding="utf-8")
        # A capture records the digest of the manifest its build came from.
        # Bind the fixtures to the file actually written so the join is the
        # same one a real capture/manifest pair goes through.
        digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        for path, document in zip(paths, captures):
            document["identity"]["program_digest"] = digest
            path.write_text(json.dumps(document), encoding="utf-8")
    return cfg, paths, manifest_path


def run(tmp_path, cfg, captures, program=None, **kwargs):
    out = tmp_path / "report.json"
    arguments = ["--capture", *[str(path) for path in captures],
                 "--cfg-dir", str(cfg), "--out", str(out)]
    if program is not None:
        arguments += ["--program-manifest", str(tmp_path / "program_manifest.json")]
    for key, value in kwargs.items():
        if value is True:
            arguments.append("--" + key.replace("_", "-"))
        elif value is not None and value is not False:
            arguments.extend(["--" + key.replace("_", "-"), str(value)])
    assert discover_report.main(arguments) == 0
    return json.loads(out.read_text(encoding="utf-8"))


def test_gate_passing_hit_promotes_and_writes_every_variant(tmp_path):
    cfg, captures, program = setup_project(
        tmp_path,
        captures=[capture([
            row(entry_mx="M0X1", observed_hits=2, completed_hits=5),
            row(entry_mx="M1X1", observed_hits=1, completed_hits=1),
        ])],
        program=manifest(node(0x8000, 1, 1, boundary_exits=[
            (0x8000, 0x8002, 0, 1)])),
    )
    report = run(tmp_path, cfg, captures, program)

    assert report["schema"] == discover_report.SCHEMA
    assert report["summary"]["promotions"] == 2
    assert report["promotions"] == ["008100:M0X1", "008100:M1X1"]
    # Both static function boundaries and runtime hits are present.
    assert report["functions"][0]["pc"] == "008000"
    assert report["functions"][0]["boundary_exits"] == [{
        "site": "008000", "site_pc24": 0x8000,
        "target": "008002", "target_pc24": 0x8002,
        "target_entry_mx": "M0X1",
    }]
    assert {hit["variant"] for hit in report["runtime_hits"]} == {
        "008100:M0X1", "008100:M1X1"}

    seeds = (cfg / "symbols.toml").read_text(encoding="utf-8")
    assert seeds.count("[[func]]") == 2
    assert seeds.count('name = "bank_00_8100"') == 2
    assert "emit = true" in seeds and "emit = false" not in seeds
    # The seed file feeds the existing sync path unchanged.
    sync_symbols(cfg)
    entries = load_bank_cfg(str(cfg / "bank00.cfg")).entries
    assert {(entry.name, entry.start, entry.entry_m, entry.entry_x)
            for entry in entries} == {
        ("bank_00_8100", 0x8100, 0, 1), ("bank_00_8100", 0x8100, 1, 1)}


def test_second_run_is_idempotent(tmp_path):
    cfg, captures, program = setup_project(
        tmp_path, captures=[capture([row()])], program=manifest(node(0x8000, 1, 1)))
    first = run(tmp_path, cfg, captures, program)
    assert first["summary"]["promotions"] == 1
    text = (cfg / "symbols.toml").read_text(encoding="utf-8")

    second = run(tmp_path, cfg, captures, program)
    assert second["summary"]["seeded"] == 1
    assert second["summary"]["promotions"] == 0
    assert second["seeds"]["written"] == []
    assert (cfg / "symbols.toml").read_text(encoding="utf-8") == text


def test_bailed_hit_is_report_only_until_candidates_are_requested(tmp_path):
    cfg, captures, program = setup_project(
        tmp_path, captures=[capture([row(bail_hits=1)])],
        program=manifest(node(0x8000, 1, 1)))
    report = run(tmp_path, cfg, captures, program)

    hit, = report["runtime_hits"]
    assert hit["action"] == "candidate"
    assert "bailed_requires_investigation" in hit["blocking_reasons"]
    assert report["candidates"][0]["rank"] == 1
    assert not (cfg / "symbols.toml").exists()

    report = run(tmp_path, cfg, captures, program, write_candidates=True)
    assert report["seeds"]["written"][0]["emit"] is False
    seeds = (cfg / "symbols.toml").read_text(encoding="utf-8")
    assert "emit = false" in seeds
    sync_symbols(cfg)
    bank = load_bank_cfg(str(cfg / "bank00.cfg"))
    assert not bank.entries
    assert bank.force_lle == {0x008100}


@pytest.mark.parametrize("change,reason", [
    ({"site_kind": "goto_gap"}, "landing_requires_function_boundary"),
    ({"emulation": 1}, "emulation_mode_requires_analysis_support"),
    ({"observed_hits": 0, "yielded_hits": 3}, "no_execution_evidence"),
])
def test_non_gate_hits_are_candidates_with_reasons(tmp_path, change, reason):
    cfg, captures, program = setup_project(
        tmp_path, captures=[capture([row(**change)])],
        program=manifest(node(0x8000, 1, 1)))
    report = run(tmp_path, cfg, captures, program)
    hit, = report["runtime_hits"]
    assert hit["action"] == "candidate"
    assert reason in hit["blocking_reasons"]


def test_declared_boundary_admits_a_goto_landing(tmp_path):
    cfg, captures, program = setup_project(
        tmp_path,
        captures=[capture([row(site_kind="goto_gap")])],
        program=manifest(node(0x8000, 1, 1)),
        cfg_lines=["func Landing 8100 entry_mx:0,1"],
    )
    report = run(tmp_path, cfg, captures, program)
    hit, = report["runtime_hits"]
    assert hit["action"] == "declared"
    assert hit["blocking_reasons"] == ["already_declared_function"]


def test_inside_analyzed_extent_blocks_promotion(tmp_path):
    cfg, captures, program = setup_project(
        tmp_path,
        captures=[capture([row(target_pc24="0x808001")])],
        program=manifest(node(0x8000, 1, 1, min_pc24=0x8000, max_pc24=0x8010)),
    )
    report = run(tmp_path, cfg, captures, program)
    hit, = report["runtime_hits"]
    assert hit["action"] == "candidate"
    assert "inside_analyzed_extent:008000" in hit["blocking_reasons"]


@pytest.mark.parametrize("directive,reason", [
    ("data_region 00 8100 8110", "data_region"),
    ("exclude_range 8100 8110", "exclude_range"),
])
def test_cfg_data_exclusions_block_promotion(tmp_path, directive, reason):
    cfg, captures, program = setup_project(
        tmp_path, captures=[capture([row()])],
        program=manifest(node(0x8000, 1, 1)), cfg_lines=[directive])
    report = run(tmp_path, cfg, captures, program)
    hit, = report["runtime_hits"]
    assert hit["action"] == "candidate"
    assert reason in hit["blocking_reasons"]


def test_aot_eligible_manifest_variant_is_covered_not_promoted(tmp_path):
    cfg, captures, program = setup_project(
        tmp_path, captures=[capture([row()])],
        program=manifest(node(0x8100, 0, 1)))
    report = run(tmp_path, cfg, captures, program)
    hit, = report["runtime_hits"]
    assert hit["action"] == "covered"
    assert report["summary"]["covered"] == 1
    assert report["promotions"] == []


def test_force_lle_address_is_never_auto_promoted(tmp_path):
    cfg, captures, program = setup_project(
        tmp_path, captures=[capture([row()])],
        program=manifest(node(0x8000, 1, 1)),
        cfg_lines=["force_lle 008100"])
    report = run(tmp_path, cfg, captures, program)
    hit, = report["runtime_hits"]
    assert hit["action"] == "candidate"
    assert "force_lle_declared" in hit["blocking_reasons"]


def test_candidates_are_ranked_by_evidence_then_cost(tmp_path):
    document = capture([
        row(target_pc24="0x808100", observed_hits=1, site_kind="goto_gap"),
        row(target_pc24="0x808200", observed_hits=9, site_kind="goto_gap"),
        row(target_pc24="0x808300", observed_hits=4, site_kind="goto_gap"),
    ])
    document["costs"] = [
        dict(row(target_pc24="0x808200", record_kind="instruction",
                 interpreted_instructions=3, guest_cycles=30)),
        dict(row(target_pc24="0x808300", record_kind="instruction",
                 interpreted_instructions=7, guest_cycles=70)),
    ]
    cfg, captures, program = setup_project(
        tmp_path, captures=[document],
        program=manifest(node(0x8000, 1, 1)))
    report = run(tmp_path, cfg, captures, program)
    ranked = [(item["variant"], item["rank"]) for item in report["candidates"]]
    assert ranked == [("008200:M0X1", 1), ("008300:M0X1", 2), ("008100:M0X1", 3)]
    assert report["candidates"][0]["guest_cycles"] == 30


def test_no_program_manifest_still_reports_runtime_hits(tmp_path):
    cfg, captures, _ = setup_project(tmp_path, captures=[capture([row()])])
    report = run(tmp_path, cfg, captures)
    assert report["functions"] == []
    assert any("no program manifest" in warning
               for warning in report["warnings"])
    assert report["summary"]["runtime_variants"] == 1


def test_program_manifest_from_another_build_is_rejected(tmp_path):
    cfg, captures, _ = setup_project(
        tmp_path, captures=[capture([row()])], program=manifest(node(0x8000, 1, 1)))
    # Same shape, different generation: the digest no longer matches what the
    # captured build ran on, so the two must not be joined.
    other = tmp_path / "regenerated_manifest.json"
    other.write_text(json.dumps(manifest(node(0x8000, 1, 1), node(0x8200, 0, 0))),
                     encoding="utf-8")

    with pytest.raises(ValueError, match="differs from captured build"):
        discover_report.build_report(
            captures=[str(captures[0])], cfg_dir=cfg, program_manifest=other)

    with pytest.raises(SystemExit) as failure:
        discover_report.main([
            "--capture", str(captures[0]), "--cfg-dir", str(cfg),
            "--program-manifest", str(other), "--no-write-seeds"])
    assert failure.value.code == 2


def test_report_is_strict_json(tmp_path):
    cfg, captures, program = setup_project(
        tmp_path, captures=[capture([row()])], program=manifest(node(0x8000, 1, 1)))
    out = tmp_path / "report.json"
    assert discover_report.main([
        "--capture", str(captures[0]), "--cfg-dir", str(cfg),
        "--program-manifest", str(program), "--out", str(out),
        "--no-write-seeds"]) == 0
    text = out.read_text(encoding="utf-8")
    json.loads(text)  # strict JSON (and therefore a valid HJSON subset)
    assert "NaN" not in text and "Infinity" not in text
