"""Smoke-test headless ``discover`` without a compiler or a real game ROM.

The build step is covered by tests; this exercises the route the SDK promises:
verify a ROM, run a headless host with tier-2 capture enabled, join the
capture against the program manifest of that build, and append the seeds.
The host is a small Python stand-in invoked through ``--headless-exe``, so the
check runs anywhere Python does.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import zlib


ROOT = pathlib.Path(__file__).resolve().parent.parent
CLI = ROOT / "snesrecomp_cli.py"

# A stand-in headless host: writes the tier-2 capture the runtime would write,
# with the identity of the ROM it was given and the manifest it was told about.
FAKE_HOST = '''\
import hashlib, json, os, sys

rom = None
frames = 0
args = sys.argv[1:]
index = 0
while index < len(args):
    if args[index] == "--rom":
        rom = args[index + 1]
        index += 2
    elif args[index] == "--frames":
        frames = int(args[index + 1])
        index += 2
    else:
        index += 1

manifest = os.environ["FAKE_MANIFEST"]
identity = {
    "rom_sha256": hashlib.sha256(open(rom, "rb").read()).hexdigest(),
    "module_id": "main",
    "mapper": "lorom",
    "program_digest": hashlib.sha256(open(manifest, "rb").read()).hexdigest(),
}
row = {
    "site_pc24": "0x808000",
    "target_pc24": "0x808100",
    "entry_mx": "M1X1",
    "emulation": 0,
    "site_kind": "call_gap",
    "promotion_reason": "candidate_requires_analysis_and_replay",
    "fallback_reason": "missing_entry",
    "observed_hits": 1,
    "completed_hits": 1,
    "yielded_hits": 0,
    "bail_hits": 0,
    "pending_hits": 0,
}
document = {
    "schema": "snesrecomp tier2 coverage v2",
    "capture_id": "smoke_1",
    "sequence": 1,
    "identity": identity,
    "discoveries": [row],
}
with open(os.environ["SNESRECOMP_TIER2_MANIFEST"], "w", encoding="utf-8") as handle:
    json.dump(document, handle)
print("fake headless: %d frame(s)" % frames)
'''


def write_fixture_rom(path: pathlib.Path) -> bytes:
    rom = bytearray([0xFF] * 0x8000)
    rom[0] = 0x60  # RTS at $00:8000
    rom[0x7FC0 + 0x15] = 0x20  # standard LoROM mapping byte
    rom[0x7FC0 + 0x1C:0x7FC0 + 0x20] = bytes([0xFF, 0xFF, 0, 0])
    for offset in (0x0A, 0x0E, 0x1C):
        rom[0x7FE0 + offset:0x7FE0 + offset + 2] = bytes([0x00, 0x80])
    path.write_bytes(rom)
    return bytes(rom)


def write_manifest(path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "format_version": 3,
        "roots": [{"pc24": 0x8000, "m": 1, "x": 1}],
        "exit_modes": {},
        "exit_mode_sets": {},
        "nodes": {
            "008000:M1X1": {
                "key": {"pc24": 0x8000, "m": 1, "x": 1},
                "disposition": "aot_eligible",
                "instruction_count": 2,
                "min_pc24": 0x8000,
                "max_pc24": 0x8000,
                "demands": [],
                "boundary_exits": [],
                "reasons": [],
                "digest": "native",
            },
        },
    }), encoding="utf-8")


def run_cli(args: list[str], *, environment: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="snesrecomp-discover-smoke-") as directory:
        root = pathlib.Path(directory)
        rom_path = root / "fixture.sfc"
        raw = write_fixture_rom(rom_path)
        crc32 = f"{zlib.crc32(raw) & 0xFFFFFFFF:08x}"

        project = root / "project"
        (project / "recomp").mkdir(parents=True)
        (project / "recomp" / "bank00.cfg").write_text(
            "bank = 0\nauto_vectors\n", encoding="utf-8")
        manifest = project / "src" / "gen" / "program_manifest.json"
        write_manifest(manifest)

        host = root / "fake_host.py"
        host.write_text(FAKE_HOST, encoding="utf-8")

        common = [
            "discover",
            "--rom", str(rom_path),
            "--project-root", str(project),
            "--skip-build",
            "--headless-exe", sys.executable,
            "--headless-exe-arg", str(host),
            "--frames", "2",
            "--run-dir", "discovery/run",
            "--expected-crc32", crc32,
            "--json-progress",
        ]
        environment = dict(os.environ)
        environment["FAKE_MANIFEST"] = str(manifest)

        missing_manifest = run_cli(
            ["discover", "--rom", str(rom_path), "--project-root", str(project),
             "--skip-build", "--headless-exe", sys.executable,
             "--program-manifest", "src/gen/absent.json"],
            environment=environment)
        if missing_manifest.returncode != 2:
            raise RuntimeError(
                "discover should exit 2 when the manifest is missing, got "
                f"{missing_manifest.returncode}\nstderr:\n{missing_manifest.stderr}")

        completed = run_cli(common, environment=environment)
        if completed.returncode != 0:
            raise RuntimeError(
                f"discover failed: rc={completed.returncode}\n"
                f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}")

        events = []
        for line in completed.stdout.splitlines():
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"discover stdout is not clean JSONL: {line!r} ({exc})\n"
                    f"full stdout:\n{completed.stdout}") from exc
        phases = [event.get("phase") for event in events
                  if event.get("event") == "phase"]
        for required in ("verify", "run", "analyze", "done"):
            if required not in phases:
                raise RuntimeError(f"discover missing phase {required!r}: {phases}")
        result = next((event for event in events
                       if event.get("event") == "result"), None)
        if not result or not result.get("ok"):
            raise RuntimeError(f"discover missing result event: {events}")
        if result["summary"]["promotions"] != 1:
            raise RuntimeError(
                f"discover should promote the fixture hit: {result['summary']}")

        run_dir = project / "discovery" / "run"
        report_path = run_dir / "report.json"
        if not report_path.is_file():
            raise RuntimeError("discover did not write report.json")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report["schema"] != "snesrecomp coverage discovery report v1":
            raise RuntimeError(f"unexpected report schema: {report['schema']}")
        if [hit["variant"] for hit in report["runtime_hits"]] != ["008100:M1X1"]:
            raise RuntimeError(f"unexpected runtime hits: {report['runtime_hits']}")
        if not (run_dir / "capture.json").is_file():
            raise RuntimeError("discover did not keep the capture")
        if "fake headless: 2 frame(s)" not in (run_dir / "run.log").read_text(
                encoding="utf-8"):
            raise RuntimeError("discover did not log the headless run output")

        seeds = (project / "recomp" / "symbols.toml").read_text(encoding="utf-8")
        if seeds.count("[[func]]") != 1 or "emit = true" not in seeds:
            raise RuntimeError(f"discover did not seed the promoted variant:\n{seeds}")

    print("sdk discover smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
