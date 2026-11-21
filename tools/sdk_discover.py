"""Headless coverage discovery: build, run, capture, analyze, seed.

Stable entry point:
  python snesrecomp_cli.py discover ...

The command is the automated half of docs/COVERAGE_EXPANSION.md:

  1. verify the ROM (exit 3 on a digest mismatch, like generate);
  2. configure and build the project's headless target (no window, no audio
     device, no SDL_Init, deterministic guest execution);
  3. run it with tier-2 capture enabled for a bounded frame budget;
  4. join the capture against the program manifest of that same build;
  5. write report.json and append analysis seeds to recomp/symbols.toml.

Steps 4 and 5 are tools/discover_report.py; this module only owns the
build/run orchestration, so there is exactly one implementation of the
promotion gates and the seed writer.

Exit codes:
  0  success
  1  build / run / analysis failure
  2  usage / argument error
  3  ROM verification failure
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
from typing import Optional, Sequence

from tools.sdk_progress import ProgressReporter
from tools.sdk_rom import RomVerifyError, verify_rom


EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_VERIFY = 3

DEFAULT_FRAMES = 6000
DEFAULT_CFG_DIR = "recomp"
DEFAULT_OUT_DIR = "src/gen"
DEFAULT_BUILD_DIR = "build/headless"
DEFAULT_RUN_DIR = "discovery/run"
DEFAULT_BUILD_TYPE = "Release"

CAPTURE_NAME = "capture.json"
JOURNAL_NAME = "capture.jsonl"
REPORT_NAME = "report.json"
LOG_NAME = "run.log"

# Files an executable search must never pick: they are build products, not
# programs. Directories named CMakeFiles hold the compiler probes.
_NOT_EXECUTABLE_SUFFIXES = {
    ".a", ".lib", ".o", ".obj", ".so", ".dylib", ".dll", ".pdb", ".ilk",
    ".cmake", ".ninja", ".json", ".txt", ".md", ".log", ".py", ".sh",
    ".bat", ".ps1", ".cfg", ".toml", ".h", ".c",
}


def _resolve_under(root: Optional[pathlib.Path], value: str) -> pathlib.Path:
    path = pathlib.Path(value).expanduser()
    if not path.is_absolute() and root is not None:
        path = root / path
    return path.resolve()


def _cmake() -> str:
    found = os.environ.get("CMAKE") or ""
    if found:
        return found
    for name in ("cmake", "cmake.exe"):
        candidate = shutil.which(name)
        if candidate:
            return candidate
    raise RuntimeError("cmake was not found on PATH (or set CMAKE)")


def _run(
    command: Sequence[str],
    *,
    cwd: Optional[pathlib.Path] = None,
    env: Optional[dict] = None,
    log: Optional[pathlib.Path] = None,
    timeout: Optional[float] = None,
) -> subprocess.CompletedProcess:
    """Run one build/run step, keeping its output in the run log.

    Output is captured rather than inherited so a ``--json-progress`` caller
    keeps a clean stdout; the same text lands in the log either way.
    """
    try:
        result = subprocess.run(
            [str(item) for item in command],
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            errors="replace",
        )
    except OSError as exc:
        raise RuntimeError(f"could not run {command[0]}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{pathlib.Path(str(command[0])).name} timed out after {timeout}s"
        ) from exc
    if log is not None:
        text = result.stdout or ""
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"$ {' '.join(str(item) for item in command)}\n")
            handle.write(text)
            if text and not text.endswith("\n"):
                handle.write("\n")
            handle.write(f"[exit {result.returncode}]\n\n")
    return result


def configure(
    project_root: pathlib.Path,
    build_dir: pathlib.Path,
    *,
    build_type: str = DEFAULT_BUILD_TYPE,
    cmake_args: Sequence[str] = (),
    log: Optional[pathlib.Path] = None,
) -> None:
    """Configure a headless build. Never configures the desktop target."""
    command = [
        _cmake(),
        "-S", str(project_root),
        "-B", str(build_dir),
        "-DSNESRECOMP_HEADLESS=ON",
        f"-DCMAKE_BUILD_TYPE={build_type}",
        *cmake_args,
    ]
    result = _run(command, cwd=project_root, log=log)
    if result.returncode != 0:
        raise RuntimeError(
            f"headless configure failed (exit {result.returncode}); see {log}")


def build(
    build_dir: pathlib.Path,
    *,
    target: Optional[str] = None,
    build_type: str = DEFAULT_BUILD_TYPE,
    log: Optional[pathlib.Path] = None,
) -> None:
    command = [_cmake(), "--build", str(build_dir), "--parallel"]
    if target:
        command.extend(["--target", target])
    # Ignored by single-config generators, required by multi-config ones.
    command.extend(["--config", build_type])
    result = _run(command, log=log)
    if result.returncode != 0:
        raise RuntimeError(
            f"headless build failed (exit {result.returncode}); see {log}")


def find_executable(
    build_dir: pathlib.Path,
    *,
    explicit: Optional[pathlib.Path] = None,
    hint: Optional[str] = None,
) -> pathlib.Path:
    """The headless program a build produced.

    A discovery run must not silently execute the desktop host, so an
    ambiguous build is an error naming the candidates rather than a guess.
    """
    if explicit is not None:
        path = pathlib.Path(explicit)
        if not path.is_file():
            # A bare name (a wrapper such as `python3`) is resolved on PATH;
            # relative paths already resolved against the project root.
            found = shutil.which(str(explicit))
            if found:
                return pathlib.Path(found)
            raise ValueError(f"--headless-exe is not a file: {path}")
        return path
    found = []
    for path in sorted(build_dir.rglob("*")):
        if not path.is_file() or "CMakeFiles" in path.parts:
            continue
        if path.suffix.lower() in _NOT_EXECUTABLE_SUFFIXES:
            continue
        if not os.access(path, os.X_OK):
            continue
        found.append(path)
    if hint:
        needle = hint.lower()
        matched = [path for path in found if needle in path.name.lower()]
        if matched:
            found = matched
    if len(found) == 1:
        return found[0]
    if not found:
        raise ValueError(
            f"no executable in {build_dir}; build the headless target first "
            "or pass --headless-exe")
    names = ", ".join(path.name for path in found[:8])
    raise ValueError(
        f"several executables in {build_dir} ({names}); pass --headless-exe")


def run_headless(
    executable: pathlib.Path,
    *,
    rom: pathlib.Path,
    frames: int,
    run_dir: pathlib.Path,
    script: Optional[pathlib.Path] = None,
    save_root: Optional[pathlib.Path] = None,
    timeout: Optional[float] = None,
    log: Optional[pathlib.Path] = None,
    exe_args: Sequence[str] = (),
) -> dict:
    """Run the headless host with tier-2 capture, returning the artifacts."""
    run_dir.mkdir(parents=True, exist_ok=True)
    capture = run_dir / CAPTURE_NAME
    journal = run_dir / JOURNAL_NAME
    # A journal from an earlier run in the same directory would otherwise be
    # joined with this one and inflate the evidence.
    for path in (capture, journal):
        if path.exists():
            path.unlink()

    environment = os.environ.copy()
    environment["SNESRECOMP_TIER2_CAPTURE"] = "1"
    environment["SNESRECOMP_TIER2_MANIFEST"] = str(capture)
    environment["SNESRECOMP_TIER2_JOURNAL"] = str(journal)

    command = [str(executable), *exe_args, "--rom", str(rom),
               "--frames", str(frames)]
    if script is not None:
        command.extend(["--input-script", str(script)])
    if save_root is not None:
        save_root.mkdir(parents=True, exist_ok=True)
        command.extend(["--save-root", str(save_root)])

    result = _run(command, cwd=run_dir, env=environment, log=log,
                  timeout=timeout)
    artifacts = [path for path in (capture, journal) if path.is_file()]
    if result.returncode != 0:
        raise RuntimeError(
            f"headless run failed (exit {result.returncode}); see {log}")
    if not artifacts:
        raise RuntimeError(
            "headless run produced no tier-2 capture; the target may not link "
            "the capture runtime")
    return {"command": command, "artifacts": artifacts}


def analyze(
    *,
    run_dir: pathlib.Path,
    cfg_dir: pathlib.Path,
    program_manifest: pathlib.Path,
    write_candidates: bool,
    reporter: ProgressReporter,
) -> dict:
    """Join the capture with the manifest and append the seeds.

    No ROM digest is passed on purpose: the capture was produced by the run
    above, and the runtime hashes the headerless image while ``verify_rom``
    hashes the file, so a headered ``.smc`` would compare unequal for no
    reason. The manifest digest is still enforced, because that one can
    legitimately be stale.
    """
    from tools import discover_report

    captures = [str(path) for path in (
        run_dir / CAPTURE_NAME, run_dir / JOURNAL_NAME) if path.is_file()]
    report, static, hits, seed_path = discover_report.build_report(
        captures=captures,
        cfg_dir=cfg_dir,
        program_manifest=program_manifest,
    )
    seeds = discover_report.write_seeds(
        seed_path, hits, write_candidates=write_candidates, static=static)
    report["seeds"] = seeds

    out = run_dir / REPORT_NAME
    out.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8")

    summary = report["summary"]
    reporter.log(
        f"discover: {summary['runtime_variants']} runtime variant(s), "
        f"{summary['promotions']} promotion(s), "
        f"{summary['candidates']} candidate(s)")
    reporter.log(
        f"discover: seeds -> {seeds['path']} ({len(seeds['written'])} row(s))")
    for warning in report["warnings"]:
        reporter.log(f"discover: warning: {warning}", level="warning")
    return report


def apply_seeds(
    *,
    rom: pathlib.Path,
    cfg_dir: pathlib.Path,
    out_dir: pathlib.Path,
    funcs_h: pathlib.Path,
    project_root: pathlib.Path,
    build_dir: pathlib.Path,
    build_type: str,
    target: Optional[str],
    cmake_args: Sequence[str],
    expected_crc32: Optional[str],
    expected_sha256: Optional[str],
    log: pathlib.Path,
    reporter: ProgressReporter,
) -> None:
    """Regenerate the emitted C and rebuild so the new seeds take effect."""
    from tools.sdk_generate import generate

    reporter.phase("regenerate", pct=0.85,
                   message="Regenerating C from the new seeds")
    generate(
        rom=rom,
        cfg_dir=cfg_dir,
        out_dir=out_dir,
        funcs_h=funcs_h,
        expected_crc32=expected_crc32,
        expected_sha256=expected_sha256,
        progress=reporter,
    )
    reporter.phase("rebuild", pct=0.95, message="Rebuilding the headless target")
    configure(project_root, build_dir, build_type=build_type,
              cmake_args=cmake_args, log=log)
    build(build_dir, target=target, build_type=build_type, log=log)


def discover_command(args: argparse.Namespace, progress: ProgressReporter) -> int:
    project_root = pathlib.Path(args.project_root).expanduser().resolve()
    if not project_root.is_dir():
        progress.error(f"project-root is not a directory: {project_root}",
                       code=EXIT_USAGE)
        return EXIT_USAGE

    rom = _resolve_under(project_root, args.rom)
    cfg_dir = _resolve_under(project_root, args.cfg_dir)
    out_dir = _resolve_under(project_root, args.out_dir)
    build_dir = _resolve_under(project_root, args.build_dir)
    run_dir = _resolve_under(project_root, args.run_dir)
    program_manifest = _resolve_under(project_root, args.program_manifest)
    funcs_h = _resolve_under(project_root, args.funcs_h or
                             str(pathlib.Path(args.cfg_dir) / "funcs.h"))
    script = _resolve_under(project_root, args.input_script) if args.input_script else None
    save_root = _resolve_under(project_root, args.save_root) if args.save_root else (
        run_dir / "save")

    if args.frames == 0 and script is None:
        progress.error(
            "--frames 0 runs until the script quits, so it needs "
            "--input-script", code=EXIT_USAGE)
        return EXIT_USAGE
    if script is not None and not script.is_file():
        progress.error(f"input script not found: {script}", code=EXIT_USAGE)
        return EXIT_USAGE
    if not cfg_dir.is_dir():
        progress.error(f"cfg-dir is not a directory: {cfg_dir}", code=EXIT_USAGE)
        return EXIT_USAGE
    if not program_manifest.is_file():
        progress.error(
            f"program manifest not found: {program_manifest} (run generate "
            "first: the manifest must describe the build being captured)",
            code=EXIT_USAGE)
        return EXIT_USAGE

    try:
        progress.phase("verify", pct=0.05, message=f"Verifying ROM {rom.name}")
        identity = verify_rom(rom, expected_crc32=args.expected_crc32,
                              expected_sha256=args.expected_sha256)
    except RomVerifyError as exc:
        progress.error(str(exc), code=EXIT_VERIFY, details=exc.details)
        return EXIT_VERIFY
    except (OSError, ValueError) as exc:
        progress.error(str(exc), code=EXIT_ERROR)
        return EXIT_ERROR

    run_dir.mkdir(parents=True, exist_ok=True)
    log = run_dir / LOG_NAME
    log.write_text("", encoding="utf-8")

    try:
        if args.headless_exe:
            explicit = pathlib.Path(args.headless_exe).expanduser()
            relative = project_root / explicit
            if not explicit.is_absolute() and relative.exists():
                explicit = relative
            executable = find_executable(build_dir, explicit=explicit)
        elif args.skip_build:
            executable = find_executable(build_dir)
        else:
            progress.phase("configure", pct=0.1,
                           message=f"Configuring headless build in {build_dir}")
            configure(project_root, build_dir, build_type=args.build_type,
                      cmake_args=args.cmake_arg, log=log)
            progress.phase("build", pct=0.2,
                           message="Building the headless target")
            build(build_dir, target=args.build_target,
                  build_type=args.build_type, log=log)
            executable = find_executable(build_dir, hint=args.executable_hint)

        progress.phase("run", pct=0.5,
                       message=f"Running {args.frames} frame(s) headless")
        capture = run_headless(
            executable,
            rom=rom,
            frames=args.frames,
            run_dir=run_dir,
            script=script,
            save_root=save_root,
            timeout=args.timeout,
            log=log,
            exe_args=args.headless_exe_arg,
        )
        progress.event("capture", artifacts=[str(p) for p in capture["artifacts"]])

        progress.phase("analyze", pct=0.7, message="Analyzing the capture")
        report = analyze(
            run_dir=run_dir,
            cfg_dir=cfg_dir,
            program_manifest=program_manifest,
            write_candidates=bool(args.write_candidates),
            reporter=progress,
        )

        if args.apply:
            apply_seeds(
                rom=rom,
                cfg_dir=cfg_dir,
                out_dir=out_dir,
                funcs_h=funcs_h,
                project_root=project_root,
                build_dir=build_dir,
                build_type=args.build_type,
                target=args.build_target,
                cmake_args=args.cmake_arg,
                expected_crc32=args.expected_crc32,
                expected_sha256=args.expected_sha256,
                log=log,
                reporter=progress,
            )
    except (OSError, RuntimeError, ValueError) as exc:
        progress.error(str(exc), code=EXIT_ERROR)
        return EXIT_ERROR

    progress.phase("done", pct=1.0, message="Discovery complete")
    progress.result(
        ok=True,
        rom=identity,
        executable=str(executable),
        frames=args.frames,
        run_dir=str(run_dir),
        report=str(run_dir / REPORT_NAME),
        seeds=report["seeds"],
        summary=report["summary"],
        applied=bool(args.apply),
    )
    return EXIT_OK


def add_discover_parser(subparsers) -> None:
    discover = subparsers.add_parser(
        "discover",
        help="run the headless build and turn its coverage capture into "
             "analysis seeds",
    )
    discover.add_argument("--rom", required=True, help="path to .sfc/.smc ROM")
    discover.add_argument("--project-root", required=True,
                          help="recompilation project root; relative paths "
                               "resolve here")
    discover.add_argument("--cfg-dir", default=DEFAULT_CFG_DIR,
                          help=f"analysis cfg directory (default {DEFAULT_CFG_DIR})")
    discover.add_argument("--out-dir", default=DEFAULT_OUT_DIR,
                          help=f"generated C directory, used by --apply "
                               f"(default {DEFAULT_OUT_DIR})")
    discover.add_argument("--funcs-h",
                          help="funcs.h to rewrite on --apply "
                               "(default <cfg-dir>/funcs.h)")
    discover.add_argument("--program-manifest",
                          default=f"{DEFAULT_OUT_DIR}/program_manifest.json",
                          help="manifest from the build being captured "
                               f"(default {DEFAULT_OUT_DIR}/program_manifest.json)")
    discover.add_argument("--build-dir", default=DEFAULT_BUILD_DIR,
                          help=f"headless build directory (default {DEFAULT_BUILD_DIR})")
    discover.add_argument("--run-dir", default=DEFAULT_RUN_DIR,
                          help=f"capture and report directory (default {DEFAULT_RUN_DIR})")
    discover.add_argument("--frames", type=int, default=DEFAULT_FRAMES,
                          help=f"guest frames to simulate; 0 runs until the "
                               f"script quits (default {DEFAULT_FRAMES})")
    discover.add_argument("--input-script",
                          help="route to replay (runner input-script grammar)")
    discover.add_argument("--save-root",
                          help="savestate root (default <run-dir>/save)")
    discover.add_argument("--write-candidates", action="store_true",
                          help="also seed report-only candidates as emit=false")
    discover.add_argument("--apply", action="store_true",
                          help="regenerate C and rebuild after seeding")
    discover.add_argument("--skip-build", action="store_true",
                          help="reuse the existing build directory")
    discover.add_argument("--headless-exe",
                          help="explicit headless executable (skips the search)")
    discover.add_argument("--headless-exe-arg", action="append", default=[],
                          help="extra argument placed before the host's own "
                               "flags, for a wrapper such as an interpreter "
                               "(repeatable)")
    discover.add_argument("--executable-hint",
                          help="prefer build executables whose name contains this")
    discover.add_argument("--build-target",
                          help="cmake --build --target value")
    discover.add_argument("--build-type", default=DEFAULT_BUILD_TYPE,
                          help=f"CMAKE_BUILD_TYPE (default {DEFAULT_BUILD_TYPE})")
    discover.add_argument("--cmake-arg", action="append", default=[],
                          help="extra cmake argument; use --cmake-arg=-DKEY=VAL "
                               "for -D options (repeatable)")
    discover.add_argument("--timeout", type=float,
                          help="seconds to allow the headless run")
    discover.add_argument("--expected-crc32",
                          help="optional CRC32 (8 hex digits, optional 0x prefix)")
    discover.add_argument("--expected-sha256",
                          help="optional SHA-256 (64 hex digits)")
    discover.add_argument("--json-progress", action="store_true",
                          help="emit JSONL progress/result events on stdout")
    discover.set_defaults(handler=discover_command)
