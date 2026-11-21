"""The headless discovery route: build/run orchestration around the report."""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "tools"), str(REPO / "recompiler")]

from tools import sdk_discover  # noqa: E402


def completed(code=0, output=""):
    return subprocess.CompletedProcess(args=["cmake"], returncode=code,
                                       stdout=output, stderr="")


def test_find_executable_prefers_the_named_build(tmp_path):
    (tmp_path / "CMakeFiles").mkdir()
    (tmp_path / "CMakeFiles" / "probe").write_text("")
    desktop = tmp_path / "GameRecomp"
    headless = tmp_path / "GameRecompHeadless"
    for path in (desktop, headless):
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)

    assert sdk_discover.find_executable(
        tmp_path, hint="headless") == headless
    with pytest.raises(ValueError, match="several executables"):
        sdk_discover.find_executable(tmp_path)


def test_find_executable_accepts_a_wrapper_on_path():
    resolved = sdk_discover.find_executable(
        pathlib.Path("/nonexistent"), explicit=pathlib.Path("python3"))
    assert resolved.name.lower().startswith("python")
    with pytest.raises(ValueError, match="not a file"):
        sdk_discover.find_executable(
            pathlib.Path("/nonexistent"), explicit=pathlib.Path("no-such-wrapper"))


def test_configure_and_build_request_the_headless_target(monkeypatch, tmp_path):
    recorded = []

    def fake_run(command, **kwargs):
        recorded.append(list(command))
        return completed()

    monkeypatch.setattr(sdk_discover, "_run", fake_run)
    monkeypatch.setattr(sdk_discover, "_cmake", lambda: "cmake")

    sdk_discover.configure(tmp_path, tmp_path / "build",
                           cmake_args=["-DSNESRECOMP_ROOT=/framework"])
    sdk_discover.build(tmp_path / "build", target="GameHeadless")

    configure, build = recorded
    assert configure[:2] == ["cmake", "-S"]
    assert str(tmp_path) in configure and "-B" in configure
    assert "-DSNESRECOMP_HEADLESS=ON" in configure
    assert "-DSNESRECOMP_ROOT=/framework" in configure
    assert build[:3] == ["cmake", "--build", str(tmp_path / "build")]
    assert "--target" in build and "GameHeadless" in build


def test_configure_failure_names_the_log(monkeypatch, tmp_path):
    monkeypatch.setattr(sdk_discover, "_run", lambda *a, **k: completed(1))
    monkeypatch.setattr(sdk_discover, "_cmake", lambda: "cmake")
    log = tmp_path / "run.log"
    with pytest.raises(RuntimeError, match="headless configure failed"):
        sdk_discover.configure(tmp_path, tmp_path / "build", log=log)


def test_run_headless_clears_a_stale_capture(monkeypatch, tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    stale = run_dir / sdk_discover.JOURNAL_NAME
    stale.write_text('{"schema":"old"}\n', encoding="utf-8")
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = list(command)
        seen["environment"] = dict(kwargs["env"])
        seen["stale_exists"] = stale.exists()
        (run_dir / sdk_discover.CAPTURE_NAME).write_text("{}", encoding="utf-8")
        return completed()

    monkeypatch.setattr(sdk_discover, "_run", fake_run)
    result = sdk_discover.run_headless(
        pathlib.Path("/game-headless"),
        rom=tmp_path / "game.sfc",
        frames=120,
        run_dir=run_dir,
        script=None,
    )

    assert not seen["stale_exists"]
    assert seen["environment"]["SNESRECOMP_TIER2_CAPTURE"] == "1"
    assert seen["environment"]["SNESRECOMP_TIER2_MANIFEST"].endswith("capture.json")
    assert "--frames" in seen["command"] and "120" in seen["command"]
    assert "--input-script" not in seen["command"]
    assert result["artifacts"] == [run_dir / sdk_discover.CAPTURE_NAME]


def test_run_headless_without_capture_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(sdk_discover, "_run", lambda *a, **k: completed())
    with pytest.raises(RuntimeError, match="no tier-2 capture"):
        sdk_discover.run_headless(pathlib.Path("/game-headless"),
                                  rom=tmp_path / "game.sfc", frames=1,
                                  run_dir=tmp_path / "run")


def test_apply_seeds_regenerates_before_rebuilding(monkeypatch, tmp_path):
    order = []
    recorded = {}

    def fake_generate(**kwargs):
        order.append("generate")
        recorded.update(kwargs)

    monkeypatch.setattr("tools.sdk_generate.generate", fake_generate)
    monkeypatch.setattr(sdk_discover, "configure",
                        lambda *a, **k: order.append("configure"))
    monkeypatch.setattr(sdk_discover, "build",
                        lambda *a, **k: order.append("build"))

    sdk_discover.apply_seeds(
        rom=tmp_path / "game.sfc",
        cfg_dir=tmp_path / "recomp",
        out_dir=tmp_path / "src" / "gen",
        funcs_h=tmp_path / "recomp" / "funcs.h",
        project_root=tmp_path,
        build_dir=tmp_path / "build",
        build_type="Release",
        target=None,
        cmake_args=[],
        expected_crc32=None,
        expected_sha256=None,
        log=tmp_path / "run.log",
        reporter=sdk_discover.ProgressReporter(),
    )

    assert order == ["generate", "configure", "build"]
    assert recorded["cfg_dir"] == tmp_path / "recomp"
    assert recorded["funcs_h"] == tmp_path / "recomp" / "funcs.h"


def test_missing_program_manifest_is_a_usage_error(tmp_path, capsys):
    (tmp_path / "recomp").mkdir()
    (tmp_path / "game.sfc").write_bytes(b"\0" * 0x8000)
    code = sdk_discover.discover_command(
        _arguments(tmp_path), sdk_discover.ProgressReporter())
    assert code == sdk_discover.EXIT_USAGE
    assert "program manifest not found" in capsys.readouterr().err


def test_frames_zero_needs_a_script(tmp_path, capsys):
    (tmp_path / "recomp").mkdir()
    (tmp_path / "src" / "gen").mkdir(parents=True)
    (tmp_path / "src" / "gen" / "program_manifest.json").write_text("{}")
    (tmp_path / "game.sfc").write_bytes(b"\0" * 0x8000)
    code = sdk_discover.discover_command(
        _arguments(tmp_path, frames=0), sdk_discover.ProgressReporter())
    assert code == sdk_discover.EXIT_USAGE
    assert "needs --input-script" in capsys.readouterr().err


def _arguments(project, **overrides):
    values = dict(
        rom=str(project / "game.sfc"),
        project_root=str(project),
        cfg_dir="recomp",
        out_dir="src/gen",
        funcs_h=None,
        program_manifest="src/gen/program_manifest.json",
        build_dir="build/headless",
        run_dir="discovery/run",
        frames=600,
        input_script=None,
        save_root=None,
        write_candidates=False,
        apply=False,
        skip_build=True,
        headless_exe=None,
        headless_exe_arg=[],
        executable_hint=None,
        build_target=None,
        build_type="Release",
        cmake_arg=[],
        timeout=None,
        expected_crc32=None,
        expected_sha256=None,
        json_progress=False,
    )
    values.update(overrides)
    return type("Arguments", (), values)()
