from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from replay import bootstrap


@dataclass(frozen=True)
class _Manifest:
    name: str = "toy_op"
    relative_path: str = "family/toy"
    arch: str = "arch35"
    host: str = "wsl"
    distro: str = "Ubuntu-22.04"
    entry: str = ""


def _runner(tmp_path: Path):
    return SimpleNamespace(
        manifest=_Manifest(),
        cache=tmp_path / ".ascendc-pilot" / "arch35" / "tg" / "replay",
        root=tmp_path / "pilot",
    )


def test_linux_missing_legacy_entry_bootstraps_instead_of_refusing(tmp_path, monkeypatch) -> None:
    runner = _runner(tmp_path)
    monkeypatch.delenv("UO_REPLAY_SCRIPT", raising=False)
    monkeypatch.delenv("TG_CLOSURE_CI", raising=False)
    monkeypatch.setattr(bootstrap.sys, "platform", "linux")
    monkeypatch.setattr(bootstrap, "_inside_wsl", lambda: True)
    called = {}

    def fake_native(value, **_kwargs):
        called["runner"] = value
        called["kwargs"] = _kwargs
        return {"ok": True, "bootstrapped": True, "controller": "wsl"}

    monkeypatch.setattr(bootstrap, "_native_bootstrap", fake_native)
    out = bootstrap.ensure_runner(runner)
    assert out["ok"] is True
    assert out["bootstrapped"] is True
    assert called["runner"] is runner


def test_explicit_missing_replay_entry_fails_closed(tmp_path, monkeypatch) -> None:
    runner = _runner(tmp_path)
    missing = tmp_path / "does-not-exist.sh"
    runner.manifest = _Manifest(host="native", entry=str(missing))
    monkeypatch.setenv("UO_REPLAY_SCRIPT", str(missing))
    monkeypatch.setattr(bootstrap.sys, "platform", "linux")
    out = bootstrap.ensure_runner(runner)
    assert out["ok"] is False
    assert out["error"] == "EXPLICIT_REPLAY_ENTRY_MISSING"


def test_windows_missing_entry_routes_to_wsl_bootstrap(tmp_path, monkeypatch) -> None:
    runner = _runner(tmp_path)
    monkeypatch.delenv("UO_REPLAY_SCRIPT", raising=False)
    monkeypatch.delenv("UO_REPLAY_DISTRO", raising=False)
    monkeypatch.delenv("TG_CLOSURE_CI", raising=False)
    monkeypatch.setattr(bootstrap.sys, "platform", "win32")
    monkeypatch.setattr(bootstrap, "_wsl_list_distros", lambda: ["Ubuntu-22.04"])
    monkeypatch.setattr(
        bootstrap,
        "_wsl",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="missing"),
    )
    called = {}

    def fake_windows(value, distro, **_kwargs):
        called["runner"] = value
        called["distro"] = distro
        called["kwargs"] = _kwargs
        return {"ok": True, "bootstrapped": True, "controller": "windows"}

    monkeypatch.setattr(bootstrap, "_windows_wsl_bootstrap", fake_windows)
    out = bootstrap.ensure_runner(runner)
    assert out["ok"] is True
    assert called["runner"] is runner
    assert called["distro"] == "Ubuntu-22.04"


def test_generated_wrapper_pins_runtime_inputs() -> None:
    text = bootstrap._wrapper_text(
        cann_env="/mnt/d/op/.ascendc-pilot/arch35/tg/replay/runtime/cann_env.sh",
        run_script="/mnt/d/pilot/scripts/replay/wsl/run_replay.sh",
        ops_root="/mnt/d/ops-transformer",
        replay_bin="/mnt/d/op/.ascendc-pilot/arch35/tg/replay/runtime/replay_main",
        replay_so="/mnt/d/ops-transformer/build/libophost_transformer_ut.so",
        op_name="FlashAttentionScoreGrad",
    )
    assert "source '/mnt/d/op/.ascendc-pilot/arch35/tg/replay/runtime/cann_env.sh'" in text
    assert "export REPLAY_CANN_ENV=" in text
    assert "/usr/local/Ascend" not in text
    assert "export REPLAY_BIN='/mnt/d/op/.ascendc-pilot/arch35/tg/replay/runtime/replay_main'" in text
    assert "export OPS_ROOT='/mnt/d/ops-transformer'" in text
    assert "/work/wsl/setup" not in text


def test_extract_cann_env_wrapper_uses_pkg_layout() -> None:
    text = bootstrap._cann_env_wrapper_text("/mnt/d/_cann/pkg", "x86_64-linux")
    assert "CANN_PKG_ROOT='/mnt/d/_cann/pkg'" in text
    assert "cann-asc-devkit/$CANN_HOST" in text
    assert "/usr/local/Ascend" not in text


def test_ensure_runner_writes_environment_receipt(tmp_path, monkeypatch) -> None:
    import yaml

    runner = _runner(tmp_path)
    monkeypatch.delenv("UO_REPLAY_SCRIPT", raising=False)
    monkeypatch.delenv("TG_CLOSURE_CI", raising=False)
    monkeypatch.setattr(bootstrap.sys, "platform", "linux")
    monkeypatch.setattr(bootstrap, "_inside_wsl", lambda: True)
    monkeypatch.setattr(
        bootstrap,
        "_native_bootstrap",
        lambda value, **_kwargs: {
            "ok": True,
            "bootstrapped": True,
            "controller": "wsl",
            "entry": str(tmp_path / "run_replay.sh"),
            "cann_env": "/mnt/d/op/.ascendc-pilot/arch35/tg/replay/runtime/cann_env.sh",
            "cann_pkg": "/mnt/d/_cann/pkg",
            "ops_root": "/mnt/d/ops",
            "bin": str(tmp_path / "replay_main"),
        },
    )
    out = bootstrap.ensure_runner(runner)
    assert out["ok"] is True
    receipt_path = Path(out["environment"])
    assert receipt_path.is_file()
    doc = yaml.safe_load(receipt_path.read_text(encoding="utf-8"))
    assert doc["schema"] == "tg-replay-environment/v1"
    assert doc["driver"]["status"] == "ready"
    assert doc["driver"]["bootstrapped"] is True
    assert doc["cann"]["set_env"] == "/mnt/d/op/.ascendc-pilot/arch35/tg/replay/runtime/cann_env.sh"
    assert doc["cann"]["root"] == "/mnt/d/_cann/pkg"
    assert doc["cann"]["layout"] == "extract"


def test_wsl_distro_ambiguous_fails_closed(tmp_path, monkeypatch) -> None:
    runner = _runner(tmp_path)
    runner.manifest = _Manifest(distro="")
    monkeypatch.delenv("UO_REPLAY_SCRIPT", raising=False)
    monkeypatch.delenv("UO_REPLAY_DISTRO", raising=False)
    monkeypatch.delenv("TG_CLOSURE_CI", raising=False)
    monkeypatch.setattr(bootstrap.sys, "platform", "win32")
    monkeypatch.setattr(bootstrap, "_wsl_list_distros", lambda: ["Ubuntu-22.04", "Debian"])
    out = bootstrap.ensure_runner(runner)
    assert out["ok"] is False
    assert out["error"] == "WSL_DISTRO_AMBIGUOUS"


def test_wsl_unavailable_fails_closed(tmp_path, monkeypatch) -> None:
    runner = _runner(tmp_path)
    monkeypatch.delenv("UO_REPLAY_SCRIPT", raising=False)
    monkeypatch.delenv("UO_REPLAY_DISTRO", raising=False)
    monkeypatch.delenv("TG_CLOSURE_CI", raising=False)
    monkeypatch.setattr(bootstrap.sys, "platform", "win32")
    monkeypatch.setattr(bootstrap, "_wsl_list_distros", lambda: [])
    out = bootstrap.ensure_runner(runner)
    assert out["ok"] is False
    assert out["error"] == "WSL_UNAVAILABLE"


def test_decode_wsl_list_utf16() -> None:
    raw = "Ubuntu-22.04\nDebian\n".encode("utf-16-le")
    text = bootstrap._decode_wsl_list(raw).replace("\x00", "")
    assert "Ubuntu-22.04" in text
    assert "Debian" in text


def test_linux_tree_force_copy_never_maps(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ASCENDC_PILOT_CACHE", str(tmp_path / "cache"))
    src = tmp_path / "ops"
    src.mkdir()
    (src / "host.cpp").write_text("int kvMerge = 0;\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "_wsl_path", lambda distro, path: f"/wsl/{Path(path).as_posix()}")
    monkeypatch.setattr(
        bootstrap,
        "_wsl",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    _linux, mode = bootstrap._linux_tree("Ubuntu-22.04", src, "toy_op/ops", force_copy=False)
    assert mode == "map"
    _linux, mode = bootstrap._linux_tree("Ubuntu-22.04", src, "toy_op/ops", force_copy=True)
    assert mode == "copy"
    dest = tmp_path / "cache" / "toy_op" / "ops"
    assert (dest / "host.cpp").is_file()
    assert (src / "host.cpp").read_text(encoding="utf-8") == "int kvMerge = 0;\n"


def test_ensure_runner_passes_force_copy_and_rebuild(tmp_path, monkeypatch) -> None:
    runner = _runner(tmp_path)
    monkeypatch.delenv("UO_REPLAY_SCRIPT", raising=False)
    monkeypatch.delenv("TG_CLOSURE_CI", raising=False)
    monkeypatch.setattr(bootstrap.sys, "platform", "win32")
    monkeypatch.setattr(bootstrap, "_wsl_list_distros", lambda: ["Ubuntu-22.04"])
    monkeypatch.setattr(
        bootstrap,
        "_wsl",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="missing"),
    )
    seen: list[dict] = []

    def fake_windows(value, distro, **kwargs):
        seen.append(dict(kwargs))
        return {"ok": True, "bootstrapped": True, "controller": "windows", "distro": distro}

    monkeypatch.setattr(bootstrap, "_windows_wsl_bootstrap", fake_windows)
    assert bootstrap.ensure_runner(runner, force_copy=True)["ok"] is True
    assert seen[-1].get("force_copy") is True
    assert seen[-1].get("rebuild") is False
    assert bootstrap.ensure_runner(runner, rebuild=True)["ok"] is True
    assert seen[-1].get("rebuild") is True
    assert seen[-1].get("force_copy") is False


def test_rebuild_uses_existing_sandbox_without_recopy(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ASCENDC_PILOT_CACHE", str(tmp_path / "cache"))
    runner = _runner(tmp_path)
    dest = bootstrap.ops_sandbox_local(runner)
    dest.mkdir(parents=True)
    marker = dest / "probed.cpp"
    marker.write_text("TG_PROBE kvMerge=1\n", encoding="utf-8")
    copies: list[bool] = []

    def fake_tree(*args, **kwargs):
        copies.append(True)
        raise AssertionError("rebuild must not recopy ops")

    monkeypatch.setattr(bootstrap, "_linux_tree", fake_tree)
    monkeypatch.setattr(bootstrap, "_ops_root", lambda _runner: tmp_path / "ops-git")
    (tmp_path / "ops-git").mkdir()
    monkeypatch.setattr(bootstrap, "_wsl_path", lambda distro, path: f"/wsl/{Path(path).as_posix()}")
    monkeypatch.setattr(bootstrap, "_wsl_cann_env", lambda distro, runtime: "/wsl/cann_env.sh")
    monkeypatch.setattr(bootstrap, "_ensure_wsl_build_deps", lambda distro: None)
    monkeypatch.setattr(bootstrap, "_cann_pkg_root", lambda: None)
    monkeypatch.setattr(
        bootstrap,
        "_bundled",
        lambda _runner, name: tmp_path / "bundled" / name,
    )
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    for name in ("run_replay.sh", "build_replay.sh", "replay_main.cpp"):
        (bundled / name).write_text("x\n", encoding="utf-8")
    commands: list[tuple] = []

    def fake_wsl(distro, *args):
        commands.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(bootstrap, "_wsl", fake_wsl)
    out = bootstrap._windows_wsl_bootstrap(runner, "Ubuntu-22.04", force_copy=False, rebuild=True)
    assert out["ok"] is True
    assert copies == []
    assert marker.read_text(encoding="utf-8") == "TG_PROBE kvMerge=1\n"
    assert out["ops_mode"] == "copy"
    joined = " ".join(" ".join(str(a) for a in args) for args in commands)
    assert "--ophost_test" in joined
    assert "build_replay.sh" in joined or str(bundled / "build_replay.sh").replace("\\", "/") in joined.replace("\\", "/")
