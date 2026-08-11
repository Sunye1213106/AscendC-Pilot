#!/usr/bin/env python3
"""Validate an AscendC-Pilot installation.

Default checks cover the Python packages installed by the documented one-line
install command. Optional flags check the heavier external environments used by
UO source extraction and TG Host replay.
"""

from __future__ import annotations

import argparse
import importlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Result:
    name: str
    ok: bool
    detail: str
    required: bool = True


class Reporter:
    def __init__(self) -> None:
        self.results: list[Result] = []

    def add(self, name: str, ok: bool, detail: str, *, required: bool = True) -> None:
        self.results.append(Result(name=name, ok=ok, detail=detail, required=required))
        tag = "OK" if ok else ("FAIL" if required else "WARN")
        print(f"[{tag}] {name}: {detail}")

    def failed_required(self) -> list[Result]:
        return [r for r in self.results if r.required and not r.ok]


def _package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "version unknown"


def check_import(reporter: Reporter, package: str, module: str) -> None:
    try:
        mod = importlib.import_module(module)
    except Exception as exc:  # noqa: BLE001 - diagnostic script
        reporter.add(
            f"import {module}",
            False,
            f"{exc}; run the documented python -m pip install command from {ROOT}",
        )
        return
    origin = getattr(mod, "__file__", "<builtin>")
    reporter.add(f"import {module}", True, f"{_package_version(package)} at {origin}")


def check_tool(reporter: Reporter, name: str, *, required: bool) -> str | None:
    found = shutil.which(name)
    reporter.add(f"tool {name}", bool(found), found or "not on PATH", required=required)
    return found


def check_python(reporter: Reporter) -> None:
    ok = sys.version_info >= (3, 10)
    reporter.add(
        "python",
        ok,
        f"{sys.version.split()[0]} at {sys.executable}; need >= 3.10",
    )


def check_base(reporter: Reporter) -> None:
    print("\n== Base Python install ==")
    check_python(reporter)
    for package, module in (
        ("PyYAML", "yaml"),
        ("jsonschema", "jsonschema"),
        ("acp-common", "acp_common"),
        ("ascendc-pilot", "ascendc_pilot"),
        ("uo-init", "uo_init"),
        ("testcase-agent", "testcase_agent"),
        ("code-engineering", "code_engineering"),
        ("numpy", "numpy"),
        ("pandas", "pandas"),
        ("scikit-learn", "sklearn"),
    ):
        check_import(reporter, package, module)
    check_tool(reporter, "acp", required=True)


def check_uo(reporter: Reporter) -> None:
    print("\n== UO source extraction environment ==")
    check_import(reporter, "libclang", "clang.cindex")
    check_tool(reporter, "clang", required=True)
    check_tool(reporter, "cmake", required=False)
    check_tool(reporter, "c++", required=False)

    op_root_raw = (os.environ.get("ASCENDC_PROJECT_ROOT") or os.environ.get("UO_OP_DIR") or "").strip()
    op_root = Path(op_root_raw).expanduser() if op_root_raw else None
    reporter.add(
        "target operator root",
        bool(op_root and op_root.is_dir()),
        str(op_root) if op_root and op_root.is_dir() else "not set; use ASCENDC_PROJECT_ROOT / UO_OP_DIR when checking a concrete operator",
        required=False,
    )

    try:
        from uo_init.paths import cann_root, explain, ops_root
    except Exception as exc:  # noqa: BLE001 - diagnostic script
        reporter.add("uo_init.paths", False, f"{exc}")
        return

    cann = cann_root()
    ops = ops_root()
    reporter.add(
        "CANN root",
        cann is not None,
        str(cann) if cann else "not found; set UO_CANN_ROOT / ASCEND_CANN_PACKAGE_PATH / CANN_ROOT",
    )
    reporter.add(
        "source/dependency root",
        ops is not None,
        str(ops) if ops else "not found; set UO_OPS_ROOT / OPS_ROOT when the operator needs an external dependency checkout",
        required=False,
    )
    print("\nresolution detail:")
    print(explain())


def _run(cmd: list[str], *, timeout: int = 10) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic script
        return False, str(exc)
    text = (proc.stdout or "").strip().replace("\r", "")
    if len(text) > 300:
        text = text[:300] + "..."
    return proc.returncode == 0, text or f"exit={proc.returncode}"


def _default_cann_set_env() -> Path:
    return Path("/usr/local/Ascend/cann/set_env.sh")


def check_replay(reporter: Reporter) -> None:
    print("\n== TG Host replay environment ==")
    if os.name == "nt":
        wsl = check_tool(reporter, "wsl", required=True)
        distro = os.environ.get("UO_REPLAY_DISTRO", "").strip()
        reporter.add(
            "UO_REPLAY_DISTRO",
            bool(distro),
            distro or "not set; set it to the WSL distro that has CANN",
        )
        if wsl:
            ok, detail = _run(["wsl", "-l", "-q"])
            reporter.add("wsl distro list", ok, detail, required=True)
        if wsl and distro:
            script = 'p="${CANN_SET_ENV:-/usr/local/Ascend/cann/set_env.sh}"; test -f "$p" && echo "$p"'
            ok, detail = _run(["wsl", "-d", distro, "--", "sh", "-lc", script])
            reporter.add(
                "WSL CANN set_env.sh",
                ok,
                detail if ok else "not found in WSL; install CANN or set CANN_SET_ENV inside the distro",
                required=True,
            )
    else:
        set_env = Path(os.environ.get("CANN_SET_ENV") or _default_cann_set_env())
        reporter.add(
            "CANN set_env.sh",
            set_env.is_file(),
            str(set_env) if set_env.is_file() else "not found; set CANN_SET_ENV",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uo", action="store_true", help="also check Clang/CANN/source dependency roots")
    parser.add_argument("--replay", action="store_true", help="also check TG Host replay environment")
    parser.add_argument("--all", action="store_true", help="check base, UO, and replay environments")
    args = parser.parse_args(argv)

    print(f"repo={ROOT}")
    reporter = Reporter()
    check_base(reporter)
    if args.uo or args.all:
        check_uo(reporter)
    if args.replay or args.all:
        check_replay(reporter)

    failed = reporter.failed_required()
    print("\n== Summary ==")
    if failed:
        print(f"install_check_failed: {len(failed)} required check(s) failed")
        for result in failed:
            print(f"  - {result.name}: {result.detail}")
        return 1
    print("install_check_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
