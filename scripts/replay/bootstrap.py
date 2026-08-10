# -*- coding: utf-8 -*-
"""Bootstrap the bundled Host replay runtime on a fresh workstation.

The operator source may live on Windows while CANN/compilation live in WSL.
Only WSL + CANN + the operator checkout are prerequisites; a hand-installed
``/work/.../run_replay.sh`` is not.

The generated runtime is owned by TG and lives below ``tg/replay/runtime``.
That keeps machine-local build products out of UO and avoids absolute setup
paths becoming part of the operator contract.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any


def _run(
    cmd: list[str],
    *,
    check: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
        env=env,
    )


def _wsl(distro: str, *args: str) -> subprocess.CompletedProcess:
    return _run(["wsl", "-d", distro, "-e", *args])


def _inside_wsl() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    if (os.environ.get("WSL_DISTRO_NAME") or "").strip():
        return True
    for path in (Path("/proc/sys/kernel/osrelease"), Path("/proc/version")):
        try:
            if "microsoft" in path.read_text(encoding="utf-8", errors="ignore").lower():
                return True
        except OSError:
            pass
    return False


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
    return Path(runner.root) / "scripts" / "replay" / "wsl" / name


def _runtime_dir(runner: Any) -> Path:
    path = Path(runner.cache).expanduser().resolve() / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _disabled(runner: Any) -> bool:
    if str(os.environ.get("TG_CLOSURE_CI") or "").lower() in {"1", "true", "yes"}:
        return True
    return str(getattr(runner.manifest, "name", "")).startswith("_synthetic")


def _native_cann_env() -> str:
    explicit = (os.environ.get("CANN_SET_ENV") or "").strip()
    if explicit and Path(explicit).is_file():
        return str(Path(explicit).expanduser().resolve())
    home = (os.environ.get("ASCEND_HOME_PATH") or "").strip()
    if home:
        p = Path(home)
        for candidate in (p / "set_env.sh", p.parent / "set_env.sh"):
            if candidate.is_file():
                return str(candidate.resolve())
    candidates = [Path("/usr/local/Ascend/cann/set_env.sh")]
    candidates.extend(sorted(Path("/usr/local/Ascend").glob("cann-*/set_env.sh"), reverse=True))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return ""


def _wsl_cann_env(distro: str) -> str:
    explicit = (os.environ.get("CANN_SET_ENV") or "").strip()
    command = (
        "set -e; "
        + (f"test -f {sh_quote(explicit)} && printf '%s' {sh_quote(explicit)} && exit 0; " if explicit else "")
        + "if [ -f /usr/local/Ascend/cann/set_env.sh ]; then printf '%s' /usr/local/Ascend/cann/set_env.sh; exit 0; fi; "
        + "p=$(ls -1d /usr/local/Ascend/cann-*/set_env.sh 2>/dev/null | sort -Vr | head -n1); "
        + "test -n \"$p\"; printf '%s' \"$p\""
    )
    proc = _wsl(distro, "bash", "-lc", command)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _camel_op(name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in str(name).split("_") if part)


def _wrapper_text(*, cann_env: str, run_script: str, ops_root: str, replay_bin: str, replay_so: str, op_name: str) -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"source {sh_quote(cann_env)} >/dev/null 2>&1\n"
        f"export OPS_ROOT={sh_quote(ops_root)}\n"
        f"export REPLAY_BIN={sh_quote(replay_bin)}\n"
        f"export REPLAY_SO={sh_quote(replay_so)}\n"
        f"export REPLAY_OP_NAME={sh_quote(op_name)}\n"
        f"exec bash {sh_quote(run_script)} \"$@\"\n"
    )


def _native_bootstrap(runner: Any) -> dict[str, Any]:
    manifest = runner.manifest
    runtime = _runtime_dir(runner)
    run_script = _bundled(runner, "run_replay.sh").resolve()
    build_script = _bundled(runner, "build_replay.sh").resolve()
    source_cpp = _bundled(runner, "replay_main.cpp").resolve()
    for path in (run_script, build_script, source_cpp):
        if not path.is_file():
            return {"ok": False, "error": "BUNDLED_REPLAY_FILE_MISSING", "path": str(path)}

    cann_env = _native_cann_env()
    if not cann_env:
        return {"ok": False, "error": "CANN_ENV_NOT_FOUND", "hint": "set CANN_SET_ENV or install CANN under /usr/local/Ascend"}
    ops = _ops_root(runner)
    replay_bin = runtime / "replay_main"
    replay_so = ops / "build" / "tests" / "ut" / "framework_normal" / "op_host" / "libophost_transformer_ut.so"

    host_build_attempted = False
    if not replay_so.is_file():
        host_build_attempted = True
        build_sh = ops / "build.sh"
        if not build_sh.is_file():
            return {"ok": False, "error": "OPHOST_BUILD_SCRIPT_MISSING", "path": str(build_sh)}
        cmd = (
            f"set -e; source {sh_quote(cann_env)} >/dev/null 2>&1; cd {sh_quote(str(ops))}; "
            "chmod +x ./build.sh; "
            f"./build.sh --ophost_test --ops={sh_quote(str(manifest.name))} --noexec"
        )
        proc = _run(["bash", "-lc", cmd])
        if proc.returncode != 0:
            return {"ok": False, "error": "OPHOST_BOOTSTRAP_FAILED", "stdout": proc.stdout[-1000:], "stderr": proc.stderr[-1000:]}

    if not replay_bin.is_file():
        cmd = (
            f"set -e; source {sh_quote(cann_env)} >/dev/null 2>&1; "
            f"export OPS_ROOT={sh_quote(str(ops))}; "
            f"bash {sh_quote(str(build_script))} {sh_quote(str(source_cpp))} {sh_quote(str(replay_bin))}"
        )
        proc = _run(["bash", "-lc", cmd])
        if proc.returncode != 0:
            return {"ok": False, "error": "REPLAY_DRIVER_BUILD_FAILED", "stdout": proc.stdout[-1000:], "stderr": proc.stderr[-1000:]}

    wrapper = runtime / "run_replay.sh"
    wrapper.write_text(
        _wrapper_text(
            cann_env=cann_env,
            run_script=str(run_script),
            ops_root=str(ops),
            replay_bin=str(replay_bin),
            replay_so=str(replay_so),
            op_name=_camel_op(manifest.name),
        ),
        encoding="utf-8",
        newline="\n",
    )
    wrapper.chmod(wrapper.stat().st_mode | 0o111)
    runner.manifest = replace(manifest, host="native", entry=str(wrapper))
    return {
        "ok": True,
        "bootstrapped": True,
        "entry": str(wrapper),
        "bin": str(replay_bin),
        "ops_root": str(ops),
        "cann_env": cann_env,
        "controller": "wsl" if _inside_wsl() else "linux",
        "host_build_attempted": host_build_attempted,
    }


def _windows_wsl_bootstrap(runner: Any, distro: str) -> dict[str, Any]:
    manifest = runner.manifest
    runtime = _runtime_dir(runner)
    run_script = _bundled(runner, "run_replay.sh")
    build_script = _bundled(runner, "build_replay.sh")
    source_cpp = _bundled(runner, "replay_main.cpp")
    for path in (run_script, build_script, source_cpp):
        if not path.is_file():
            return {"ok": False, "error": "BUNDLED_REPLAY_FILE_MISSING", "path": str(path)}

    cann_env = _wsl_cann_env(distro)
    if not cann_env:
        return {"ok": False, "error": "CANN_ENV_NOT_FOUND", "distro": distro, "hint": "install CANN in WSL or set CANN_SET_ENV"}
    ops = _ops_root(runner)
    ops_wsl = _wsl_path(distro, ops)
    runtime_wsl = _wsl_path(distro, runtime)
    run_wsl = _wsl_path(distro, run_script)
    build_wsl = _wsl_path(distro, build_script)
    cpp_wsl = _wsl_path(distro, source_cpp)
    replay_bin = f"{runtime_wsl}/replay_main"
    replay_so = f"{ops_wsl}/build/tests/ut/framework_normal/op_host/libophost_transformer_ut.so"

    host_build_attempted = False
    have_so = _wsl(distro, "test", "-f", replay_so)
    if have_so.returncode != 0:
        host_build_attempted = True
        cmd = (
            f"set -e; source {sh_quote(cann_env)} >/dev/null 2>&1; cd {sh_quote(ops_wsl)}; "
            "test -f ./build.sh; chmod +x ./build.sh; "
            f"./build.sh --ophost_test --ops={sh_quote(str(manifest.name))} --noexec"
        )
        proc = _wsl(distro, "bash", "-lc", cmd)
        if proc.returncode != 0:
            return {"ok": False, "error": "OPHOST_BOOTSTRAP_FAILED", "stdout": proc.stdout[-1000:], "stderr": proc.stderr[-1000:]}

    have_bin = _wsl(distro, "test", "-x", replay_bin)
    if have_bin.returncode != 0:
        cmd = (
            f"set -e; source {sh_quote(cann_env)} >/dev/null 2>&1; "
            f"export OPS_ROOT={sh_quote(ops_wsl)}; "
            f"bash {sh_quote(build_wsl)} {sh_quote(cpp_wsl)} {sh_quote(replay_bin)}"
        )
        proc = _wsl(distro, "bash", "-lc", cmd)
        if proc.returncode != 0:
            return {"ok": False, "error": "REPLAY_DRIVER_BUILD_FAILED", "stdout": proc.stdout[-1000:], "stderr": proc.stderr[-1000:]}

    wrapper = f"{runtime_wsl}/run_replay.sh"
    text = _wrapper_text(
        cann_env=cann_env,
        run_script=run_wsl,
        ops_root=ops_wsl,
        replay_bin=replay_bin,
        replay_so=replay_so,
        op_name=_camel_op(manifest.name),
    )
    install = _wsl(
        distro,
        "bash",
        "-lc",
        f"set -e; mkdir -p {sh_quote(runtime_wsl)}; cat > {sh_quote(wrapper)} <<'ACP_EOF'\n{text}ACP_EOF\nchmod +x {sh_quote(wrapper)}",
    )
    if install.returncode != 0:
        return {"ok": False, "error": "REPLAY_ENTRY_INSTALL_FAILED", "stderr": install.stderr[-500:]}

    runner.manifest = replace(manifest, host="wsl", distro=distro, entry=wrapper)
    return {
        "ok": True,
        "bootstrapped": True,
        "entry": wrapper,
        "bin": replay_bin,
        "ops_root": ops_wsl,
        "cann_env": cann_env,
        "distro": distro,
        "controller": "windows",
        "host_build_attempted": host_build_attempted,
    }


def _operator_path_bridge(runner: Any, *, distro: str = "") -> dict[str, str]:
    """Resolve Windows controller path and Linux/WSL execution path for the op."""
    op_root = (os.environ.get("ASCENDC_PROJECT_ROOT") or os.environ.get("UO_OP_DIR") or "").strip()
    windows_root = ""
    linux_root = ""
    if op_root:
        root = Path(op_root).expanduser().resolve()
        windows_root = str(root)
        if sys.platform.startswith("linux"):
            linux_root = root.as_posix()
        elif distro:
            try:
                linux_root = _wsl_path(distro, root)
            except Exception as exc:
                linux_root = f"WSL_PATH_FAILED:{exc}"[:180]
    return {
        "windows_root": windows_root,
        "linux_root": linux_root,
        "ops_root_env": (os.environ.get("OPS_TRANSFORMER_ROOT") or os.environ.get("UO_OPS_ROOT") or "").strip(),
    }


def _write_environment_receipt(runner: Any, result: dict[str, Any]) -> dict[str, Any]:
    """Persist a durable replay environment receipt under tg/replay/."""
    try:
        import yaml
    except Exception:
        return result
    cache = Path(runner.cache).expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / "environment.yaml"
    distro = str(result.get("distro") or getattr(runner.manifest, "distro", "") or "")
    bridge = _operator_path_bridge(runner, distro=distro)
    cann_env = str(result.get("cann_env") or "")
    entry = str(result.get("entry") or getattr(runner.manifest, "entry", "") or "")
    driver_status = "missing"
    if result.get("ok") and (result.get("reused") or result.get("bootstrapped")):
        driver_status = "ready"
    elif result.get("skipped"):
        driver_status = "skipped"
    elif not result.get("ok"):
        driver_status = "error"
    receipt = {
        "schema": "tg-replay-environment/v1",
        "controller": {
            "os": "windows" if sys.platform.startswith("win") else ("wsl" if _inside_wsl() else "linux"),
            "platform": sys.platform,
        },
        "executor": {
            "kind": "wsl" if str(getattr(runner.manifest, "host", "") or "").lower() == "wsl" and not sys.platform.startswith("linux") else ("native" if sys.platform.startswith("linux") else str(getattr(runner.manifest, "host", "") or "")),
            "distro": distro,
            "host": str(getattr(runner.manifest, "host", "") or ""),
        },
        "operator": {
            "name": str(getattr(runner.manifest, "name", "") or ""),
            "architecture": str(getattr(runner.manifest, "arch", "") or ""),
            "windows_root": bridge.get("windows_root") or "",
            "linux_root": bridge.get("linux_root") or "",
            "ops_root": str(result.get("ops_root") or bridge.get("ops_root_env") or ""),
        },
        "cann": {
            "set_env": cann_env,
            "root": str(Path(cann_env).parent) if cann_env else "",
            "usable": bool(cann_env) or driver_status in {"ready", "skipped"},
        },
        "driver": {
            "status": driver_status,
            "entry": entry,
            "bin": str(result.get("bin") or ""),
            "reused": bool(result.get("reused")),
            "bootstrapped": bool(result.get("bootstrapped")),
            "error": str(result.get("error") or ""),
        },
        "result": {k: result.get(k) for k in ("ok", "skipped", "error", "controller") if k in result},
    }
    path.write_text(yaml.safe_dump(receipt, allow_unicode=True, sort_keys=False), encoding="utf-8")
    result = dict(result)
    result["environment"] = path.as_posix()
    return result


def ensure_runner(runner: Any) -> dict[str, Any]:
    """Ensure a usable replay entry and binary exist, then bind the runner to it.

    Existing explicit runtimes are reused. Otherwise the generated runtime is
    created under TG's replay cache. The function is idempotent and always
    writes ``tg/replay/environment.yaml`` (except CI/synthetic skips).
    """
    if _disabled(runner):
        return _write_environment_receipt(runner, {"ok": True, "skipped": "ci_or_synthetic"})

    manifest = runner.manifest
    explicit_entry = bool((os.environ.get("UO_REPLAY_SCRIPT") or "").strip())
    native = sys.platform.startswith("linux") or str(manifest.host or "").lower() == "native" or str(os.environ.get("UO_REPLAY_HOST") or "").lower() == "native"

    if native:
        entry = str(manifest.entry or "")
        if entry and Path(entry).expanduser().is_file():
            return _write_environment_receipt(
                runner,
                {"ok": True, "reused": True, "entry": entry, "controller": "wsl" if _inside_wsl() else "linux"},
            )
        if explicit_entry:
            return _write_environment_receipt(
                runner,
                {"ok": False, "error": "EXPLICIT_REPLAY_ENTRY_MISSING", "entry": entry},
            )
        return _write_environment_receipt(runner, _native_bootstrap(runner))

    host = str(manifest.host or "wsl").lower()
    if host != "wsl":
        return _write_environment_receipt(runner, {"ok": False, "error": f"UNSUPPORTED_REPLAY_HOST:{host}"})
    distro = str(os.environ.get("UO_REPLAY_DISTRO") or manifest.distro or "").strip()
    if not distro:
        return _write_environment_receipt(runner, {"ok": False, "error": "WSL_DISTRO_UNRESOLVED"})

    listing = _run(["wsl", "-l", "-q"])
    if listing.returncode != 0:
        return _write_environment_receipt(
            runner,
            {"ok": False, "error": "WSL_UNAVAILABLE", "stderr": listing.stderr[-300:], "distro": distro},
        )
    probe = _wsl(distro, "test", "-f", str(manifest.entry or "")) if manifest.entry else None
    if probe is not None and probe.returncode == 0:
        return _write_environment_receipt(
            runner,
            {"ok": True, "reused": True, "entry": manifest.entry, "distro": distro, "controller": "windows"},
        )
    if explicit_entry:
        return _write_environment_receipt(
            runner,
            {"ok": False, "error": "EXPLICIT_REPLAY_ENTRY_MISSING", "entry": manifest.entry, "distro": distro},
        )
    return _write_environment_receipt(runner, _windows_wsl_bootstrap(runner, distro))


def sh_quote(value: str) -> str:
    return "'" + str(value).replace("'", "'\"'\"'") + "'"
