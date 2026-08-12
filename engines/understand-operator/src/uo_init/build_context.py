# -*- coding: utf-8 -*-
"""Resolve build_context.yaml placeholders into concrete clang/libclang args."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from uo_init.paths import require_architecture
import yaml

from uo_init import paths

SPEC_DIR = Path(__file__).resolve().parents[2] / "spec"
DEFAULT_CONTEXT = SPEC_DIR / "build_context.yaml"
FUNCTION_LIKE_QUALIFIERS = {"__in_pipe__", "__out_pipe__", "__inout_pipe__"}


def _sub(s: str, mapping: dict[str, str]) -> str:
    out = s
    # multi-pass so nested placeholders resolve
    for _ in range(4):
        prev = out
        for k, v in mapping.items():
            out = out.replace("{" + k + "}", v)
        if out == prev:
            break
    return out


@dataclass
class BuildContext:
    raw: dict[str, Any]
    cann_root: str
    ops_root: str
    compat_root: str
    op_dir: str = ""
    arch_dir: str = ""
    repo_root: str = ""

    @classmethod
    def load(
        cls,
        path: Path | str | None = None,
        *,
        cann_root: str | None = None,
        ops_root: str | None = None,
        op_dir: str | None = None,
        arch_dir: str = "",
        repo_root: str | None = None,
    ) -> "BuildContext":
        p = Path(path) if path else DEFAULT_CONTEXT
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        defaults = dict(raw.get("defaults") or {})
        # AscendC-Pilot root: .../engines/understand-operator/src/uo_init -> parents[4]
        rr = repo_root or str(Path(__file__).resolve().parents[4])
        # The spec file carries no machine-specific defaults; where the external
        # trees live is a property of the checkout, resolved by uo_init.paths.
        cann_fallback = cann_root or defaults.get("cann_root") or paths.cann_root() or ""
        ops_fallback = ops_root or defaults.get("ops_root") or paths.ops_root() or ""
        mapping = {
            "repo_root": rr.replace("\\", "/"),
            "cann_root": str(cann_fallback).replace("\\", "/"),
            "ops_root": str(ops_fallback).replace("\\", "/"),
            "compat_root": "",
            "op_dir": (op_dir or "").replace("\\", "/"),
            "arch_dir": arch_dir,
        }
        # Always prefer the in-package compat/ (shim + prelude) unless overridden
        cr = str(SPEC_DIR / "compat").replace("\\", "/")
        if defaults.get("compat_root"):
            cr = _sub(defaults["compat_root"], mapping).replace("\\", "/")
        mapping["compat_root"] = cr
        if cann_root:
            mapping["cann_root"] = cann_root.replace("\\", "/")
        if ops_root:
            mapping["ops_root"] = ops_root.replace("\\", "/")
        return cls(
            raw=raw,
            cann_root=mapping["cann_root"],
            ops_root=mapping["ops_root"],
            compat_root=mapping["compat_root"],
            op_dir=mapping["op_dir"],
            arch_dir=arch_dir,
            repo_root=rr.replace("\\", "/"),
        )

    def mapping(self) -> dict[str, str]:
        return {
            "cann_root": self.cann_root,
            "ops_root": self.ops_root,
            "compat_root": self.compat_root,
            "op_dir": self.op_dir,
            "arch_dir": self.arch_dir,
            "repo_root": self.repo_root,
        }

    def resolve_path(self, template: str) -> str:
        return _sub(template, self.mapping()).replace("\\", "/")

    def sysroot_includes(self) -> list[str]:
        return [self.resolve_path(p) for p in self.raw.get("sysroot_includes") or []]

    def host_includes(self) -> list[str]:
        return [self.resolve_path(p) for p in (self.raw.get("host") or {}).get("includes") or []]

    def kernel_includes(self) -> list[str]:
        return [self.resolve_path(p) for p in (self.raw.get("kernel") or {}).get("includes") or []]

    def host_defines(self) -> dict[str, str]:
        return dict((self.raw.get("host") or {}).get("defines") or {})

    def kernel_defines(self) -> dict[str, str]:
        return dict((self.raw.get("kernel") or {}).get("defines") or {})

    def erase_qualifiers(self) -> list[str]:
        return list((self.raw.get("kernel") or {}).get("erase_qualifiers") or [])

    def dtype_variants(self) -> dict[str, Any]:
        return dict((self.raw.get("kernel") or {}).get("dtype_variants") or {})

    def force_includes(self) -> list[str]:
        return [self.resolve_path(p) for p in (self.raw.get("kernel") or {}).get("force_include") or []]

    def base_flags(self) -> list[str]:
        flags = list(self.raw.get("base_flags") or [])
        std = self.raw.get("std") or "c++17"
        target = self.raw.get("target") or "aarch64-linux-gnu"
        out = list(flags)
        if "-std=c++17" not in " ".join(out):
            out += [f"-std={std}"]
        if "--target" not in " ".join(out):
            out += [f"--target={target}"]
        return out

    def host_args(self) -> list[str]:
        args = list(self.base_flags())
        for d, v in self.host_defines().items():
            args.append(f"-D{d}" if v == "" else f"-D{d}={v}")
        for p in self.sysroot_includes():
            args += ["-isystem", p]
        for p in self.host_includes():
            args += ["-I", p]
        return args

    def to_dict(self) -> dict[str, Any]:
        """Pickle-safe snapshot for ProcessPool workers."""
        return {
            "raw": self.raw,
            "cann_root": self.cann_root,
            "ops_root": self.ops_root,
            "compat_root": self.compat_root,
            "op_dir": self.op_dir,
            "arch_dir": self.arch_dir,
            "repo_root": self.repo_root,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BuildContext":
        return cls(
            raw=dict(data.get("raw") or {}),
            cann_root=str(data.get("cann_root") or ""),
            ops_root=str(data.get("ops_root") or ""),
            compat_root=str(data.get("compat_root") or ""),
            op_dir=str(data.get("op_dir") or ""),
            arch_dir=require_architecture(data.get("arch_dir")),
            repo_root=str(data.get("repo_root") or ""),
        )

    def kernel_args(self, dtype_variant: str | None = None) -> list[str]:
        args = list(self.base_flags())
        for q in self.erase_qualifiers():
            if q in FUNCTION_LIKE_QUALIFIERS:
                args.append(f"-D{q}(...)=")
            else:
                args.append(f"-D{q}=")
        for d, v in self.kernel_defines().items():
            args.append(f"-D{d}" if v == "" else f"-D{d}={v}")
        dv = self.dtype_variants()
        if dtype_variant:
            macro = dv.get("macro") or "ORIG_DTYPE_QUERY"
            args.append(f"-D{macro}={dtype_variant}")
            for name, val in (dv.get("dt_enum_defines") or {}).items():
                args.append(f"-D{name}={val}")
        for fi in self.force_includes():
            args += ["-include", fi]
        for p in self.sysroot_includes():
            args += ["-isystem", p]
        for p in self.kernel_includes():
            args += ["-I", p]
        return args
