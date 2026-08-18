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
    snap = (os.environ.get("ASCENDC_SNAPSHOT_WORKSPACE") or "").strip()
    if snap:
        return Path(snap).expanduser().resolve()
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


def _decode_wsl_list(raw: bytes) -> str:
    blob = raw or b""
    if blob.startswith(b"\xff\xfe") or blob.startswith(b"\xfe\xff"):
        return blob.decode("utf-16", errors="replace")
    if b"\x00" in blob[:64]:
        return blob.decode("utf-16-le", errors="replace")
    return blob.decode("utf-8", errors="replace")


def _wsl_list_distros() -> list[str]:
    try:
        proc = subprocess.run(["wsl", "-l", "-q"], capture_output=True, check=False)
    except FileNotFoundError:
        return []
    if proc.returncode != 0:
        return []
    text = _decode_wsl_list(proc.stdout or b"").replace("\x00", "")
    skip = {"docker-desktop", "docker-desktop-data"}
    names: list[str] = []
    for line in text.splitlines():
        name = line.strip()
        if name and name.lower() not in skip:
            names.append(name)
    return names


def _resolve_wsl_distro(manifest_distro: str) -> tuple[str, str]:
    """Return (distro, error_code). Empty distro means failure."""
    env = (os.environ.get("UO_REPLAY_DISTRO") or "").strip()
    listed = _wsl_list_distros()
    if not listed:
        return "", "WSL_UNAVAILABLE"
    if env:
        if env in listed or env.lower() in {n.lower() for n in listed}:
            return env, ""
        return "", "WSL_DISTRO_UNRESOLVED"
    pinned = str(manifest_distro or "").strip()
    if pinned:
        if pinned in listed or pinned.lower() in {n.lower() for n in listed}:
            return pinned, ""
        return "", "WSL_DISTRO_UNRESOLVED"
    if len(listed) == 1:
        return listed[0], ""
    return "", "WSL_DISTRO_AMBIGUOUS"


def _cann_pkg_root() -> Path | None:
    try:
        from uo_init.paths import cann_root
    except ImportError:
        return None
    root = cann_root()
    return root if root is not None and root.is_dir() else None


def _cann_host(pkg: Path) -> str:
    try:
        from uo_init.paths import cann_host_dir
    except ImportError:
        cann_host_dir = None  # type: ignore[assignment]
    if cann_host_dir is not None:
        host = cann_host_dir(pkg)
        if host:
            return host
    for name in ("x86_64-linux", "aarch64-linux"):
        if (pkg / "cann-asc-devkit" / name).is_dir() or (pkg / "cann-metadef" / name).is_dir():
            return name
    return "x86_64-linux"


def _cann_env_wrapper_text(pkg_linux: str, host: str) -> str:
    return (
        "#!/usr/bin/env bash\n"
        "# Generated by AscendC-Pilot from the UO extracted CANN tree.\n"
        f"export CANN_PKG_ROOT={sh_quote(pkg_linux)}\n"
        f"export CANN_HOST={sh_quote(host)}\n"
        'DEVKIT="$CANN_PKG_ROOT/cann-asc-devkit/$CANN_HOST"\n'
        'META="$CANN_PKG_ROOT/cann-metadef/$CANN_HOST"\n'
        'RT="$CANN_PKG_ROOT/cann-npu-runtime/$CANN_HOST"\n'
        'OPBASE="$CANN_PKG_ROOT/cann-opbase/$CANN_HOST"\n'
        'export ASCEND_HOME_PATH="$DEVKIT"\n'
        'export ASCEND_TOOLKIT_HOME="$DEVKIT"\n'
        "_libs=()\n"
        'for d in "$DEVKIT/lib64" "$DEVKIT/lib" "$META/lib64" "$RT/lib64" "$OPBASE/lib64"; do\n'
        '  [ -d "$d" ] && _libs+=("$d")\n'
        "done\n"
        "if [ ${#_libs[@]} -gt 0 ]; then\n"
        '  export LD_LIBRARY_PATH="$(IFS=:; echo "${_libs[*]}"):${LD_LIBRARY_PATH:-}"\n'
        "fi\n"
        'if [ -d "$CANN_PKG_ROOT/bisheng/bin" ]; then\n'
        '  export PATH="$CANN_PKG_ROOT/bisheng/bin:$PATH"\n'
        "fi\n"
    )


def _write_cann_env(runtime: Path, pkg_linux: str, host: str) -> Path:
    path = runtime / "cann_env.sh"
    path.write_text(_cann_env_wrapper_text(pkg_linux, host), encoding="utf-8", newline="\n")
    try:
        path.chmod(path.stat().st_mode | 0o111)
    except OSError:
        pass
    return path


def _linux_tree(distro: str, windows_path: Path, cache_key: str) -> tuple[str, str]:
    """Map a Windows tree into WSL; copy into ~/.cache/ascendc-pilot when /mnt fails."""
    mapped = ""
    try:
        mapped = _wsl_path(distro, windows_path)
    except RuntimeError:
        mapped = ""
    if mapped:
        probe = _wsl(distro, "bash", "-lc", f"test -d {sh_quote(mapped)} && test -r {sh_quote(mapped)}")
        if probe.returncode == 0:
            return mapped, "map"
    dest = Path.home() / ".cache" / "ascendc-pilot" / cache_key
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        windows_path,
        dest,
        ignore=shutil.ignore_patterns(".git", "build", "__pycache__", ".pytest_cache"),
    )
    return _wsl_path(distro, dest), "copy"


def _ensure_wsl_build_deps(distro: str) -> dict[str, Any] | None:
    probe = _wsl(
        distro,
        "bash",
        "-lc",
        "command -v g++ >/dev/null && command -v cmake >/dev/null",
    )
    if probe.returncode == 0:
        return None
    install = _wsl(
        distro,
        "bash",
        "-lc",
        "set -e; export DEBIAN_FRONTEND=noninteractive; "
        "if command -v g++ >/dev/null && command -v cmake >/dev/null; then exit 0; fi; "
        'if [ "$(id -u)" -eq 0 ]; then apt-get update -qq && apt-get install -y -qq g++ cmake; '
        "else sudo -n apt-get update -qq && sudo -n apt-get install -y -qq g++ cmake; fi",
    )
    if install.returncode != 0:
        return {
            "ok": False,
            "error": "WSL_BUILD_DEPS_MISSING",
            "message_zh": "WSL 缺少 g++/cmake，非交互 apt-get 失败。",
            "stderr": (install.stderr or "")[-400:],
        }
    return None


def _native_cann_env(runtime: Path) -> str:
    pkg = _cann_pkg_root()
    if pkg is None:
        return ""
    host = _cann_host(pkg)
    return str(_write_cann_env(runtime, pkg.as_posix(), host))


def _wsl_cann_env(distro: str, runtime: Path) -> str:
    pkg = _cann_pkg_root()
    if pkg is None:
        return ""
    host = _cann_host(pkg)
    try:
        pkg_linux, _mode = _linux_tree(distro, pkg, f"cann/{pkg.name}")
    except RuntimeError:
        return ""
    wrapper = _write_cann_env(runtime, pkg_linux, host)
    try:
        return _wsl_path(distro, wrapper)
    except RuntimeError:
        return ""


def _camel_op(name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in str(name).split("_") if part)


def _wrapper_text(*, cann_env: str, run_script: str, ops_root: str, replay_bin: str, replay_so: str, op_name: str) -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"source {sh_quote(cann_env)} >/dev/null 2>&1\n"
        f"export REPLAY_CANN_ENV={sh_quote(cann_env)}\n"
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

    cann_env = _native_cann_env(runtime)
    if not cann_env:
        return {
            "ok": False,
            "error": "CANN_ENV_NOT_FOUND",
            "message_zh": "未找到 UO 解包的 CANN（UO_CANN_ROOT / ASCEND_CANN_PACKAGE_PATH / _cann/pkg）。",
            "hint": "python scripts/cann_extract.py <toolkit.run> --dest _cann/pkg",
        }
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
        "cann_pkg": str(_cann_pkg_root() or ""),
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

    deps = _ensure_wsl_build_deps(distro) if not _inside_wsl() else None
    if isinstance(deps, dict):
        return deps
    cann_env = _wsl_cann_env(distro, runtime)
    if not cann_env:
        return {
            "ok": False,
            "error": "CANN_ENV_NOT_FOUND",
            "distro": distro,
            "message_zh": "未找到 UO 解包的 CANN，或无法映射进 WSL。设置 UO_CANN_ROOT 后重试。",
            "hint": "python scripts/cann_extract.py <toolkit.run> --dest _cann/pkg",
        }
    ops = _ops_root(runner)
    try:
        ops_wsl, _ops_mode = _linux_tree(distro, ops, f"{manifest.name}/ops")
        runtime_wsl = _wsl_path(distro, runtime)
        run_wsl = _wsl_path(distro, run_script)
        build_wsl = _wsl_path(distro, build_script)
        cpp_wsl = _wsl_path(distro, source_cpp)
    except RuntimeError as exc:
        return {"ok": False, "error": "WSL_PATH_FAILED", "distro": distro, "detail": str(exc)[:200]}
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
        "cann_pkg": str(_cann_pkg_root() or ""),
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
            "root": str(result.get("cann_pkg") or ""),
            "layout": "extract",
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
    distro, distro_err = _resolve_wsl_distro(str(manifest.distro or ""))
    if distro_err:
        return _write_environment_receipt(
            runner,
            {
                "ok": False,
                "error": distro_err,
                "message_zh": {
                    "WSL_UNAVAILABLE": "未检测到可用的 WSL 发行版。",
                    "WSL_DISTRO_AMBIGUOUS": "存在多个 WSL 发行版，请设置 UO_REPLAY_DISTRO。",
                    "WSL_DISTRO_UNRESOLVED": "指定的 WSL 发行版不在 `wsl -l -q` 列表中。",
                }.get(distro_err, distro_err),
                "distro": str(manifest.distro or os.environ.get("UO_REPLAY_DISTRO") or ""),
            },
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
