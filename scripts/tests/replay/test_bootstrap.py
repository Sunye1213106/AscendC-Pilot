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

    def fake_native(value):
        called["runner"] = value
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
    monkeypatch.delenv("TG_CLOSURE_CI", raising=False)
    monkeypatch.setattr(bootstrap.sys, "platform", "win32")
    monkeypatch.setattr(
        bootstrap,
        "_run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="Ubuntu-22.04\n", stderr=""),
    )
    monkeypatch.setattr(
        bootstrap,
        "_wsl",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="missing"),
    )
    called = {}

    def fake_windows(value, distro):
        called["runner"] = value
        called["distro"] = distro
        return {"ok": True, "bootstrapped": True, "controller": "windows"}

    monkeypatch.setattr(bootstrap, "_windows_wsl_bootstrap", fake_windows)
    out = bootstrap.ensure_runner(runner)
    assert out["ok"] is True
    assert called == {"runner": runner, "distro": "Ubuntu-22.04"}


def test_generated_wrapper_pins_runtime_inputs() -> None:
    text = bootstrap._wrapper_text(
        cann_env="/usr/local/Ascend/cann-9.1.0/set_env.sh",
        run_script="/mnt/d/pilot/scripts/replay/wsl/run_replay.sh",
        ops_root="/mnt/d/ops-transformer",
        replay_bin="/mnt/d/op/.ascendc-pilot/arch35/tg/replay/runtime/replay_main",
        replay_so="/mnt/d/ops-transformer/build/libophost_transformer_ut.so",
        op_name="FlashAttentionScoreGrad",
    )
    assert "source '/usr/local/Ascend/cann-9.1.0/set_env.sh'" in text
    assert "export REPLAY_BIN='/mnt/d/op/.ascendc-pilot/arch35/tg/replay/runtime/replay_main'" in text
    assert "export OPS_ROOT='/mnt/d/ops-transformer'" in text
    assert "/work/wsl/setup" not in text


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
        lambda value: {
            "ok": True,
            "bootstrapped": True,
            "controller": "wsl",
            "entry": str(tmp_path / "run_replay.sh"),
            "cann_env": "/usr/local/Ascend/cann/set_env.sh",
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
    assert doc["cann"]["set_env"] == "/usr/local/Ascend/cann/set_env.sh"
