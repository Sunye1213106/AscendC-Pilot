"""Unified operator workspace paths — Pilot never hardcodes an operator identity."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .paths import (
    AGENT_DIR,
    CACHE_SUBDIR,
    CE_SUBDIR,
    CONTEXT_SUBDIR,
    LOCAL_SUBDIR,
    RUNS_SUBDIR,
    STATE_SUBDIR,
    TG_SUBDIR,
    UO_SUBDIR,
    artifact_root,
    discover_arch,
    pilot_checkout_root,
    resolve_arch,
    resolve_operator_root,
    uo_codemap_path,
)


@dataclass(frozen=True)
class OperatorWorkspace:
    """Resolved roots for one operator checkout + arch.

    Callers must not assemble ``.ascendc-pilot/...`` paths themselves.
    """

    operator_root: Path
    arch: str
    pilot_root: Path
    allow_pilot_checkout: bool = False

    @classmethod
    def resolve(
        cls,
        explicit: str | Path | None = None,
        *,
        arch: str | None = None,
        allow_pilot_checkout: bool = False,
    ) -> "OperatorWorkspace":
        op_root = resolve_operator_root(
            explicit, allow_pilot_checkout=allow_pilot_checkout
        )
        arch_name = (
            resolve_arch(arch) if (arch and str(arch).strip()) else discover_arch(op_root)
        )
        return cls(
            operator_root=op_root,
            arch=arch_name,
            pilot_root=pilot_checkout_root(),
            allow_pilot_checkout=allow_pilot_checkout,
        )

    @property
    def artifact_root(self) -> Path:
        return artifact_root(
            self.operator_root,
            self.arch,
            allow_pilot_checkout=self.allow_pilot_checkout,
        )

    @property
    def uo_root(self) -> Path:
        return self.artifact_root / UO_SUBDIR

    @property
    def tg_root(self) -> Path:
        return self.artifact_root / TG_SUBDIR

    @property
    def ce_root(self) -> Path:
        return self.artifact_root / CE_SUBDIR

    @property
    def context_root(self) -> Path:
        return self.artifact_root / CONTEXT_SUBDIR

    @property
    def runs_root(self) -> Path:
        return self.artifact_root / RUNS_SUBDIR

    @property
    def state_root(self) -> Path:
        return self.artifact_root / STATE_SUBDIR

    @property
    def cache_root(self) -> Path:
        return self.artifact_root / CACHE_SUBDIR

    @property
    def local_root(self) -> Path:
        """``<op>/.ascendc-pilot/<arch>/local/`` — Local Extension tree."""
        return self.artifact_root / LOCAL_SUBDIR

    @property
    def config_local(self) -> Path:
        return self.artifact_root / "config.local.yaml"

    def codemap_path(self, op_name: str) -> Path:
        return uo_codemap_path(
            self.operator_root, op_name, arch=self.arch
        )

    def local_extension_dir(self, interface: str) -> Path:
        """Directory for one Local Extension interface (may not exist yet)."""
        safe = str(interface).strip().replace("_", "-")
        return self.local_root / safe
