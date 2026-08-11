"""Local Extension discovery — operator-specific capability escape hatch.

Extensions live only under ``<op>/.ascendc-pilot/<arch>/local/<interface>/``.
They must never write back into AscendC-Pilot source or mutate canonical ``.uo``.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

#: Allowed Local Extension interfaces (schema-backed).
KNOWN_INTERFACES = frozenset(
    {
        "case_builder",
        "replay_parser",
        "tilingdata_decoder",
        "runtime_launcher",
        "golden_provider",
    }
)

# Directory name on disk uses kebab-case; interface id uses snake_case.
_INTERFACE_DIR = {
    "case_builder": "case-builder",
    "replay_parser": "replay-parser",
    "tilingdata_decoder": "tilingdata-decoder",
    "runtime_launcher": "runtime-launcher",
    "golden_provider": "golden-provider",
}


class LocalCapabilityRequired(Exception):
    """Generic engine cannot proceed; a Local Extension is required."""

    def __init__(
        self,
        interface: str,
        *,
        reason: str = "",
        detail: str = "",
        operator_root: Path | None = None,
        arch: str = "",
    ) -> None:
        self.interface = interface
        self.reason = reason or "LOCAL_CAPABILITY_REQUIRED"
        self.detail = detail
        self.operator_root = operator_root
        self.arch = arch
        msg = (
            f"LOCAL_CAPABILITY_REQUIRED interface={interface}"
            + (f" reason={reason}" if reason else "")
            + (f" detail={detail}" if detail else "")
        )
        super().__init__(msg)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "code": "LOCAL_CAPABILITY_REQUIRED",
            "interface": self.interface,
            "reason": self.reason,
            "detail": self.detail,
            "operator_root": str(self.operator_root or ""),
            "arch": self.arch,
        }


@dataclass(frozen=True)
class LocalExtension:
    interface: str
    version: int
    root: Path
    manifest: dict[str, Any]
    implementation: Path

    @property
    def reason_code(self) -> str:
        reason = self.manifest.get("reason") or {}
        if isinstance(reason, dict):
            return str(reason.get("code") or "")
        return ""


def _load_yaml(path: Path) -> dict[str, Any]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return doc if isinstance(doc, dict) else {}


def _validate_manifest(doc: dict[str, Any], *, path: Path, interface: str) -> None:
    schema = str(doc.get("schema") or "")
    if not schema.startswith("ascendc-pilot-local-extension/"):
        raise ValueError(f"{path}: schema must be ascendc-pilot-local-extension/vN")
    iface = str(doc.get("interface") or "").strip()
    if iface != interface:
        raise ValueError(f"{path}: interface {iface!r} != requested {interface!r}")
    if iface not in KNOWN_INTERFACES:
        raise ValueError(f"{path}: unknown interface {iface!r}")
    try:
        version = int(doc.get("version") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{path}: version must be int") from exc
    if version < 1:
        raise ValueError(f"{path}: version must be >= 1")


class LocalExtensionRegistry:
    """Discover / validate / load Local Extensions for one workspace."""

    def __init__(self, local_root: Path, *, operator_root: Path | None = None, arch: str = "") -> None:
        self.local_root = Path(local_root)
        self.operator_root = operator_root
        self.arch = arch

    @classmethod
    def from_operator_root(
        cls,
        operator_root: Path,
        *,
        arch: str | None = None,
    ) -> "LocalExtensionRegistry":
        from .workspace import OperatorWorkspace

        ws = OperatorWorkspace.resolve(operator_root, arch=arch, allow_pilot_checkout=True)
        return cls(ws.local_root, operator_root=ws.operator_root, arch=ws.arch)

    def extension_dir(self, interface: str) -> Path:
        if interface not in KNOWN_INTERFACES:
            raise ValueError(f"unknown interface: {interface}")
        return self.local_root / _INTERFACE_DIR[interface]

    def discover(self, interface: str) -> LocalExtension | None:
        root = self.extension_dir(interface)
        manifest_path = root / "manifest.yaml"
        if not manifest_path.is_file():
            return None
        doc = _load_yaml(manifest_path)
        _validate_manifest(doc, path=manifest_path, interface=interface)
        impl = root / "implementation.py"
        if not impl.is_file():
            # Accept legacy alias names used during migration.
            for alt in ("parser.py", "decoder.py", "case_builder.py"):
                cand = root / alt
                if cand.is_file():
                    impl = cand
                    break
            else:
                raise ValueError(f"{root}: missing implementation.py")
        return LocalExtension(
            interface=interface,
            version=int(doc["version"]),
            root=root,
            manifest=doc,
            implementation=impl,
        )

    def get_extension(self, interface: str, *, required: bool = False) -> LocalExtension | None:
        ext = self.discover(interface)
        if ext is None and required:
            raise LocalCapabilityRequired(
                interface,
                reason="EXTENSION_MISSING",
                detail=f"expected under {self.extension_dir(interface)}",
                operator_root=self.operator_root,
                arch=self.arch,
            )
        return ext

    def load_module(self, interface: str, *, module_name: str | None = None) -> Any:
        """Import the extension implementation module."""
        ext = self.get_extension(interface, required=True)
        assert ext is not None
        name = module_name or f"ascendc_pilot_local_{interface}"
        if name in sys.modules:
            del sys.modules[name]
        spec = importlib.util.spec_from_file_location(name, ext.implementation)
        if spec is None or spec.loader is None:
            raise LocalCapabilityRequired(
                interface,
                reason="EXTENSION_LOAD_FAILED",
                detail=f"spec_from_file_location failed for {ext.implementation}",
                operator_root=self.operator_root,
                arch=self.arch,
            )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception as exc:
            raise LocalCapabilityRequired(
                interface,
                reason="EXTENSION_LOAD_FAILED",
                detail=str(exc),
                operator_root=self.operator_root,
                arch=self.arch,
            ) from exc
        return mod
