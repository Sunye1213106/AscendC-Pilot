# -*- coding: utf-8 -*-
"""Load locked platform constants from CANN ``platform_config/*.ini``.

Compilation target (arch / SKU) is fixed for a uo-init run, so ``aicNum`` /
``l2_size`` are not free variables — they are closed constants from the INI.
"""
from __future__ import annotations

import configparser
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# arch_dir short name → NpuArch number in INI (`NpuArch=3510`).
ARCH_TO_NPU_ARCH = {
    "arch35": 3510,
    "arch22": 2201,
    "arch32": 3202,
    "arch50": 5001,
}

# Default SKU when the run only names an arch (FAG arch35 probe).
DEFAULT_SKU_BY_ARCH = {
    "arch35": "Ascend950PR_9589",  # Server, cube_core_cnt=32
    "arch22": "Ascend910B2",
}

_PLATFORM_DIR_RE = re.compile(r"platform_config$", re.I)


@dataclass(frozen=True)
class PlatformProfile:
    soc_version: str
    npu_arch: int
    cube_core_cnt: int
    vector_core_cnt: int
    ai_core_cnt: int
    l2_size: int
    memory_size: int
    ini_path: str

    @property
    def aic_num(self) -> int:
        return self.cube_core_cnt or self.ai_core_cnt


def find_platform_config_dirs(cann_root: str | Path) -> list[Path]:
    root = Path(cann_root)
    if not root.is_dir():
        return []
    found: list[Path] = []
    for p in root.rglob("platform_config"):
        if p.is_dir() and _PLATFORM_DIR_RE.search(p.name):
            found.append(p)
    # Prefer runtime package paths when several trees exist.
    found.sort(key=lambda p: (0 if "npu-runtime" in str(p).lower() else 1, str(p)))
    return found


def _parse_ini(path: Path) -> PlatformProfile | None:
    cp = configparser.ConfigParser()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # INI files use `#` comments; ConfigParser needs them stripped or allow.
    cleaned = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    try:
        cp.read_string(cleaned)
    except configparser.Error:
        return None
    if "SoCInfo" not in cp and "version" not in cp:
        return None

    def _get(section: str, key: str, default: str = "0") -> str:
        if section in cp and key in cp[section]:
            return cp[section][key].strip()
        return default

    soc = _get("version", "SoC_version", path.stem)
    try:
        npu = int(_get("version", "NpuArch", "0"))
    except ValueError:
        npu = 0
    try:
        cube = int(_get("SoCInfo", "cube_core_cnt", "0"))
        vec = int(_get("SoCInfo", "vector_core_cnt", "0"))
        ai = int(_get("SoCInfo", "ai_core_cnt", "0"))
        l2 = int(_get("SoCInfo", "l2_size", "0"))
        mem = int(_get("SoCInfo", "memory_size", "0"))
    except ValueError:
        return None
    return PlatformProfile(
        soc_version=soc,
        npu_arch=npu,
        cube_core_cnt=cube,
        vector_core_cnt=vec,
        ai_core_cnt=ai,
        l2_size=l2,
        memory_size=mem,
        ini_path=str(path).replace("\\", "/"),
    )


def list_profiles(
    cann_root: str | Path,
    *,
    npu_arch: int | None = None,
) -> list[PlatformProfile]:
    out: list[PlatformProfile] = []
    seen: set[str] = set()
    for d in find_platform_config_dirs(cann_root):
        for ini in sorted(d.glob("*.ini")):
            prof = _parse_ini(ini)
            if prof is None:
                continue
            if npu_arch is not None and prof.npu_arch != npu_arch:
                continue
            if prof.soc_version in seen:
                continue
            seen.add(prof.soc_version)
            out.append(prof)
    return out


def load_platform_profile(
    cann_root: str | Path,
    *,
    arch_dir: str = "arch35",
    platform_sku: str | None = None,
) -> PlatformProfile:
    """Resolve a locked SKU profile or raise if the INI cannot be found."""
    npu = ARCH_TO_NPU_ARCH.get(arch_dir)
    sku = platform_sku or DEFAULT_SKU_BY_ARCH.get(arch_dir)
    profiles = list_profiles(cann_root, npu_arch=npu)
    if sku:
        for p in profiles:
            if p.soc_version == sku or p.soc_version.startswith(sku):
                return p
        # Allow bare stem match against filename when SoC_version differs.
        for p in profiles:
            if Path(p.ini_path).stem == sku:
                return p
    if profiles:
        # Prefer the arch default if listed among NpuArch matches, else first.
        pref = DEFAULT_SKU_BY_ARCH.get(arch_dir)
        for p in profiles:
            if pref and p.soc_version == pref:
                return p
        return profiles[0]
    raise FileNotFoundError(
        f"no platform_config INI under {cann_root} for arch={arch_dir} sku={sku!r}"
    )


def cube_core_domain(profiles: Iterable[PlatformProfile]) -> list[int]:
    vals = sorted({p.aic_num for p in profiles if p.aic_num > 0})
    return vals
