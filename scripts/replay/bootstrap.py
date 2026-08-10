# -*- coding: utf-8 -*-
"""Bootstrap the bundled Host replay runtime on a fresh workstation.

The operator source may live on Windows while CANN/compilation live in WSL.
Only WSL + CANN + the operator checkout are prerequisites; a hand-installed
``/work/.../run_replay.sh`` is not.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _run(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=check)


def _wsl(distro: str, *args: str) -> subprocess.CompletedProcess:
    return _run(["wsl", "-d", distro, "-e", *args])


def _wsl_path(distro: str, path: Path) -> str:
    p = path.expanduser().resolve()
    if sys.platform.startswith("linux"):
        return p.as_posix()
    proc = _wsl(distro, "wslpath", "-a", str(p))
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"WSL_PATH_FAILED:{p}:{proc.stderr.strip()[:160]}")
    return proc.stdout.strip()


def _ops_root(runner: Any) -> Path:
    for name in ("OPS_TRANSFORMER_ROOT", "UO_OPS_ROOT", "OPS_ROOT"):
        raw = (os.environ.get(name) or "").strip()
        if raw:
            return Path(raw).expanduser().resolve()
    op_root = os.environ.get("ASCENDC_PROJECT_ROOT") or os.environ.get("UO_OP_DIR") or ""
    if not op_root:
        raise RuntimeError("REPLAY_OP_ROOT_UNRESOLVED:set ASCENDC_PROJECT_ROOT/UO_OP_DIR")
    root = Path(op_root).expanduser().resolve()
    rel = Path(str(runner.manifest.relative_path or ""))
    for _ in rel.parts:
        root = root.parent
    return root


def _bundled(runner: Any, name: str) -> Path:
    # ReplayRunner.root is AscendC-Pilot checkout root.
    return Path(runner.root) / "scripts" / "replay" / "wsl" / name


def _disabled(runner: Any) -> bool:
    if str(os.environ.get("TG_CLOSURE_CI") or "").lower() in {"1", "true", "yes"}:
        return True
    return str(getattr(runner.manifest, "name", "")).startswith("_synthetic")


def ensure_runner(runner: Any) -> dict[str, Any]:
    """Ensure ``runner.manifest.entry`` and its replay binary exist.

    Existing runtimes are reused. The function is idempotent and only performs
    WSL setup when the configured entry is absent.
    """
    if _disabled(runner):
        return {"ok": True, "skipped": "ci_or_synthetic"}

    manifest = runner.manifest
    host = str(manifest.host or "wsl").lower()
    entry = str(manifest.entry or "")
    if host == "native" or sys.platform.startswith("linux"):
        if entry and Path(entry).expanduser().is_file():
            return {"ok": True, "reused": True, "entry": entry}
        return {"ok": False, "error": "NATIVE_REPLAY_ENTRY_MISSING", "entry": entry}
    if host != "wsl":
        return {"ok": False, "error": f"UNSUPPORTED_REPLAY_HOST:{host}"}

    distro = str(os.environ.get("UO_REPLAY_DISTRO") or manifest.distro or "")
    if not distro:
        return {"ok": False, "error": "WSL_DISTRO_UNRESOLVED"}

    # If a user explicitly supplied UO_REPLAY_SCRIPT, honour it and fail closed.
    explicit_entry = bool((os.environ.get("UO_REPLAY_SCRIPT") or "").strip())
    probe = _wsl(distro, "test", "-f", entry)
    if probe.returncode == 0:
        return {"ok": True, "reused": True, "entry": entry, "distro": distro}
    if explicit_entry:
        return {"ok": False, "error": "EXPLICIT_REPLAY_ENTRY_MISSING", "entry": entry, "distro": distro}

    run_script = _bundled(runner, "run_replay.sh")
    build_script = _bundled(runner, "build_replay.sh")
    source_cpp = _bundled(runner, "replay_main.cpp")
    for path in (run_script, build_script, source_cpp):
        if not path.is_file():
            return {"ok": False, "error": "BUNDLED_REPLAY_FILE_MISSING", "path": str(path)}

    ops = _ops_root(runner)
    ops_wsl = _wsl_path(distro, ops)
    run_wsl = _wsl_path(distro, run_script)
    build_wsl = _wsl_path(distro, build_script)
    cpp_wsl = _wsl_path(distro, source_cpp)

    # Keep existing manifest entry compatible: install the bundled script there.
    install = _wsl(
        distro,
        "bash",
        "-lc",
        f"set -e; mkdir -p {sh_quote(str(Path(entry).parent))}; cp {sh_quote(run_wsl)} {sh_quote(entry)}; chmod +x {sh_quote(entry)}",
    )
    if install.returncode != 0:
        return {"ok": False, "error": "REPLAY_ENTRY_INSTALL_FAILED", "stderr": install.stderr[-500:]}

    replay_bin = os.environ.get("REPLAY_BIN") or "/work/replay/build/fag_replay"
    so = f"{ops_wsl}/build/tests/ut/framework_normal/op_host/libophost_transformer_ut.so"
    have = _wsl(distro, "bash", "-lc", f"test -x {sh_quote(replay_bin)} -a -f {sh_quote(so)}")
    host_build_attempted = False
    if have.returncode != 0:
        # Build the host UT prerequisites when the source checkout provides its
        # normal build.sh. This is the same prerequisite the old manual setup
        # required, now owned by the agent/runtime instead of the user.
        check_so = _wsl(distro, "test", "-f", so)
        if check_so.returncode != 0:
            host_build_attempted = True
            op = str(manifest.name or "")
            build_host = _wsl(
                distro,
                "bash",
                "-lc",
                f"set -e; cd {sh_quote(ops_wsl)}; "
                f"test -x ./build.sh || chmod +x ./build.sh; "
                f"./build.sh --ophost_test --ops={sh_quote(op)} --noexec",
            )
            if build_host.returncode != 0:
                return {
                    "ok": False,
                    "error": "OPHOST_BOOTSTRAP_FAILED",
                    "command": "./build.sh --ophost_test --ops=<operator> --noexec",
                    "stdout": build_host.stdout[-1000:],
                    "stderr": build_host.stderr[-1000:],
                }

        build = _wsl(
            distro,
            "bash",
            "-lc",
            f"set -e; export OPS_ROOT={sh_quote(ops_wsl)}; "
            f"bash {sh_quote(build_wsl)} {sh_quote(cpp_wsl)} {sh_quote(replay_bin)}",
        )
        if build.returncode != 0:
            return {"ok": False, "error": "REPLAY_DRIVER_BUILD_FAILED", "stdout": build.stdout[-1000:], "stderr": build.stderr[-1000:]}

    final = _wsl(distro, "bash", "-lc", f"test -f {sh_quote(entry)} -a -x {sh_quote(replay_bin)} -a -f {sh_quote(so)}")
    if final.returncode != 0:
        return {"ok": False, "error": "REPLAY_BOOTSTRAP_INCOMPLETE", "entry": entry, "bin": replay_bin, "so": so}
    return {
        "ok": True,
        "bootstrapped": True,
        "entry": entry,
        "bin": replay_bin,
        "ops_root": ops_wsl,
        "distro": distro,
        "host_build_attempted": host_build_attempted,
    }


def sh_quote(value: str) -> str:
    return "'" + str(value).replace("'", "'\"'\"'") + "'"
