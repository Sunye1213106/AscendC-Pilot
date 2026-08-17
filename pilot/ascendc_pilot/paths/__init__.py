"""Canonical local artifact paths under <op_src>/.ascendc-pilot/<arch>/."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

AGENT_DIR = ".ascendc-pilot"
LEGACY_AGENT_DIR = ".ascendc-agent"
UO_SUBDIR = "uo"
TG_SUBDIR = "tg"
CE_SUBDIR = "ce"
MEMORY_SUBDIR = "memory"
RUNS_SUBDIR = "runs"
CONTEXT_SUBDIR = "context"
STATE_SUBDIR = "state"
LOCAL_SUBDIR = "local"
CACHE_SUBDIR = "cache"

#: Env vars that may name the operator source root (project / op_src).
PROJECT_ENV_VARS = ("ASCENDC_PROJECT_ROOT", "UO_OP_DIR")
ARCH_ENV_VARS = ("UO_ARCH", "ASCENDC_ARCH")


def pilot_checkout_root() -> Path:
    """The AscendC-Pilot repository checkout (this package lives under pilot/)."""
    # .../pilot/ascendc_pilot/paths/__init__.py → parents[3] = AscendC-Pilot
    return Path(__file__).resolve().parents[3]


def is_under_pilot_checkout(path: Path) -> bool:
    """True when ``path`` resolves inside the AscendC-Pilot checkout."""
    try:
        Path(path).expanduser().resolve().relative_to(pilot_checkout_root())
        return True
    except ValueError:
        return False


def opencode_home() -> Path:
    """OpenCode config root (respects ``XDG_CONFIG_HOME``)."""
    xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg:
        return Path(xdg).expanduser() / "opencode"
    return Path.home() / ".config" / "opencode"


def opencode_plugin_root() -> Path:
    """Installed OpenCode runtime bundle (plugin + generated skills/agents)."""
    return opencode_home() / "ascendc-pilot-plugin"


def resolve_operator_root(
    explicit: str | os.PathLike[str] | Path | None = None,
    *,
    allow_pilot_checkout: bool = False,
) -> Path:
    """Resolve the operator source directory that owns ``.ascendc-pilot/``.

    Resolution order: explicit argument → ``ASCENDC_PROJECT_ROOT`` /
    ``UO_OP_DIR`` → fail. Results that land inside the AscendC-Pilot
    checkout are rejected unless ``allow_pilot_checkout`` is set (tests only).
    """
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit).expanduser())
    for name in PROJECT_ENV_VARS:
        raw = os.environ.get(name)
        if raw:
            candidates.append(Path(raw).expanduser())

    if not candidates:
        raise ValueError(
            "operator root unresolved: pass --project / ASCENDC_PROJECT_ROOT / "
            "UO_OP_DIR (must be the analysed operator source directory, not "
            "the AscendC-Pilot checkout)"
        )

    for cand in candidates:
        root = cand.resolve()
        if not root.is_dir():
            continue
        if not allow_pilot_checkout and is_under_pilot_checkout(root):
            # Allow the checkout itself only when explicitly opted in for tests.
            if root == pilot_checkout_root() or (root / "pilot" / "ascendc_pilot").is_dir():
                raise ValueError(
                    f"refusing to use AscendC-Pilot checkout as operator root: {root}. "
                    "Pass the analysed operator source directory "
                    "(the one containing op_host/ and op_kernel/)."
                )
        return root

    raise ValueError(
        "operator root unresolved: none of the candidates is an existing directory: "
        + ", ".join(str(c) for c in candidates)
    )


def require_architecture(value: str | None) -> str:
    """Return a non-empty architecture name or raise a typed error."""
    arch = (value or "").strip()
    if not arch:
        raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE")
    return arch


def resolve_arch(explicit: str | None = None) -> str:
    """Architecture subdirectory name under ``.ascendc-pilot/``.

    Resolution order: explicit argument → ``UO_ARCH`` / ``ASCENDC_ARCH`` → fail.
    Never invents a default architecture.
    """
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    for name in ARCH_ENV_VARS:
        raw = (os.environ.get(name) or "").strip()
        if raw:
            return raw
    raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE: architecture required")


def discover_arch(project_root: Path | str) -> str:
    """Resolve arch for path helpers without an explicit argument.

    Order:
    1. ``UO_ARCH`` / ``ASCENDC_ARCH`` env (same-process / explicit override)
    2. ``.ascendc-pilot/control/active_run.yaml`` (durable cross-process pointer)
    3. Sole ``.ascendc-pilot/<arch>/state/workflow.yaml``
    4. Fail closed (missing or ambiguous)
    """
    try:
        return resolve_arch(None)
    except ValueError:
        pass

    from ascendc_pilot.active_run import active_architecture

    pinned = active_architecture(project_root)
    if pinned:
        return pinned

    root = Path(project_root).expanduser().resolve() / AGENT_DIR
    if not root.is_dir():
        raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE: architecture required")
    candidates = sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir()
        and (
            (p / STATE_SUBDIR / "workflow.yaml").is_file()
            or any((p / STATE_SUBDIR / "slots").glob("*/workflow.yaml"))
        )
    )
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE: architecture required")
    raise ValueError(
        "ARCHITECTURE_AMBIGUOUS: multiple architectures "
        f"{candidates}; pass --architecture or set active_run via acp start"
    )


def try_discover_arch(project_root: Path | str) -> str:
    """Like ``discover_arch`` but empty string instead of raising."""
    try:
        return discover_arch(project_root)
    except ValueError:
        return ""


def artifact_root(
    op_src: Path | str,
    arch: str | None = None,
    *,
    allow_pilot_checkout: bool = False,
) -> Path:
    """``<op_src>/.ascendc-pilot/<arch>/`` — all durable products live here."""
    root = Path(op_src).expanduser().resolve()
    if not allow_pilot_checkout and is_under_pilot_checkout(root):
        if root == pilot_checkout_root() or (root / "pilot" / "ascendc_pilot").is_dir():
            raise ValueError(
                f"refusing artifact_root under AscendC-Pilot checkout: {root}"
            )
    return root / AGENT_DIR / (
        resolve_arch(arch) if arch else discover_arch(root)
    )


def agent_root(
    project_root: Path,
    arch: str | None = None,
    *,
    allow_pilot_checkout: bool = True,
) -> Path:
    """Backward-compatible alias for ``artifact_root``.

    ``allow_pilot_checkout`` defaults True so existing unit tests that use a
    tmp_path or the checkout as ``project_root`` keep working; production
    callers should use ``artifact_root`` / ``resolve_operator_root``.
    """
    return artifact_root(
        project_root, arch, allow_pilot_checkout=allow_pilot_checkout
    )


def uo_root(
    project_root: Path,
    op_name: str | None = None,
    *,
    arch: str | None = None,
) -> Path:
    """Arch-scoped UO tree: ``<op>/.ascendc-pilot/<arch>/uo/``.

    Holds both the durable ``*.uo`` CodeMap product and transient work
    (``ir/``, ``checks/``, …). Multi-arch analysis uses sibling ``<arch>/`` dirs.
    """
    del op_name
    return agent_root(project_root, arch) / UO_SUBDIR


def uo_product_root(project_root: Path, *, arch: str | None = None) -> Path:
    """CodeMap product directory (same as arch-scoped ``uo_root``).

    Historical name kept for callers; products live under
    ``.ascendc-pilot/<arch>/uo/``, not a top-level sibling ``uo/``.
    """
    return uo_root(project_root, arch=arch)


def uo_codemap_path(
    project_root: Path,
    op_name: str,
    *,
    arch: str | None = None,
) -> Path:
    """``<op>/.ascendc-pilot/<arch>/uo/<op_name>.<arch>.uo``."""
    root = Path(project_root).expanduser().resolve()
    arch_name = (
        resolve_arch(arch) if (arch and str(arch).strip()) else discover_arch(root)
    )
    safe = (op_name or "operator").replace("/", "_").replace("\\", "_")
    return uo_root(root, arch=arch_name) / f"{safe}.{arch_name}.uo"


def migrate_top_level_uo_products(project_root: Path) -> dict[str, object]:
    """Refuse leftover ``.ascendc-pilot/uo/*.uo``; they are not products.

    Automatic move into ``<arch>/uo/`` is disabled. Callers must relocate
    or delete the files. Empty leftover directories are ignored.
    """
    root = Path(project_root).expanduser().resolve()
    legacy = root / AGENT_DIR / UO_SUBDIR
    if not legacy.is_dir():
        return {"ok": True, "migrated": False, "moved": []}
    leftover = [p for p in sorted(legacy.glob("*.uo")) if p.is_file()]
    if leftover:
        return {
            "ok": False,
            "error": "legacy_top_level_uo",
            "message": (
                "top-level .ascendc-pilot/uo/*.uo is not a product; "
                "move into .ascendc-pilot/<arch>/uo/ or delete. "
                "Automatic migrate is disabled."
            ),
            "paths": [p.name for p in leftover],
        }
    return {"ok": True, "migrated": False, "moved": []}


def tg_root(
    project_root: Path,
    op_name: str | None = None,
    *,
    arch: str | None = None,
) -> Path:
    del op_name
    return agent_root(project_root, arch) / TG_SUBDIR


def ce_root(
    project_root: Path,
    op_name: str | None = None,
    *,
    arch: str | None = None,
) -> Path:
    del op_name
    return agent_root(project_root, arch) / CE_SUBDIR


def memory_root(project_root: Path, *, arch: str | None = None) -> Path:
    return agent_root(project_root, arch) / MEMORY_SUBDIR


def runs_root(project_root: Path, *, arch: str | None = None) -> Path:
    return agent_root(project_root, arch) / RUNS_SUBDIR


def context_root(project_root: Path, *, arch: str | None = None) -> Path:
    return agent_root(project_root, arch) / CONTEXT_SUBDIR


def state_root(project_root: Path, *, arch: str | None = None) -> Path:
    return agent_root(project_root, arch) / STATE_SUBDIR


def migrate_legacy_agent_dir(project_root: Path, *, arch: str | None = None) -> dict[str, object]:
    """Normalize ``.ascendc-pilot/<arch>/`` layout. Never silently merge legacy dirs.

    ``.ascendc-agent`` and top-level ``.ascendc-pilot/uo/*.uo`` are refused.
    Flat control-plane dirs already under ``.ascendc-pilot/`` may still nest
    under ``<arch>/`` (same modern tree, not a second authority).
    """
    root = Path(project_root).expanduser().resolve()
    legacy = root / LEGACY_AGENT_DIR
    modern = root / AGENT_DIR
    if legacy.exists():
        return {
            "ok": False,
            "error": "legacy_agent_dir",
            "message": (
                ".ascendc-agent is retired; move contents to "
                ".ascendc-pilot/<arch>/ manually. Automatic merge is disabled."
            ),
        }

    leftover = migrate_top_level_uo_products(root)
    if leftover.get("ok") is False:
        return leftover

    if not modern.exists():
        return {"ok": True, "migrated": False, "root": ""}

    arch_name = (
        resolve_arch(arch) if (arch and str(arch).strip()) else discover_arch(root)
    )
    target = modern / arch_name
    product_uo = modern / UO_SUBDIR
    has_codemap_product = product_uo.is_dir() and any(product_uo.glob("*.uo"))
    flat_control = (modern / TG_SUBDIR, modern / STATE_SUBDIR, modern / CONTEXT_SUBDIR)
    # After product migrate, leftover top-level uo/ is YAML work (move under arch).
    flat_yaml_uo = product_uo.is_dir() and not has_codemap_product
    if (any(p.exists() for p in flat_control) or flat_yaml_uo) and not target.exists():
        target.mkdir(parents=True, exist_ok=True)
        move_names = [
            TG_SUBDIR, CE_SUBDIR, MEMORY_SUBDIR,
            RUNS_SUBDIR, CONTEXT_SUBDIR, STATE_SUBDIR,
        ]
        if flat_yaml_uo:
            move_names.insert(0, UO_SUBDIR)
        for name in move_names:
            src = modern / name
            if src.exists() and not (target / name).exists():
                shutil.move(str(src), str(target / name))
        return {"ok": True, "migrated": True, "root": str(target)}

    ctx = target / CONTEXT_SUBDIR
    old_params = ctx / "harness_params.yaml"
    new_params = ctx / "pilot_params.yaml"
    if old_params.exists() and not new_params.exists():
        old_params.rename(new_params)
    elif old_params.exists() and new_params.exists():
        old_params.unlink()
    (target / CE_SUBDIR).mkdir(parents=True, exist_ok=True)
    return {"ok": True, "migrated": False, "root": str(target)}


def ensure_control_layout(project_root: Path, *, arch: str | None = None) -> Path:
    """Create only control-plane dirs: state / context / runs."""
    result = migrate_legacy_agent_dir(project_root, arch=arch)
    if result.get("ok") is False:
        raise ValueError(f"{result.get('error')}: {result.get('message')}")
    root = agent_root(project_root, arch)
    for rel in (STATE_SUBDIR, CONTEXT_SUBDIR, RUNS_SUBDIR):
        (root / rel).mkdir(parents=True, exist_ok=True)
    return root


def ensure_uo_layout(project_root: Path, *, arch: str | None = None) -> Path:
    root = ensure_control_layout(project_root, arch=arch)
    (root / UO_SUBDIR).mkdir(parents=True, exist_ok=True)
    return root / UO_SUBDIR


def ensure_tg_layout(project_root: Path, *, arch: str | None = None) -> Path:
    root = ensure_control_layout(project_root, arch=arch)
    (root / TG_SUBDIR).mkdir(parents=True, exist_ok=True)
    return root / TG_SUBDIR


def ensure_closure_layout(project_root: Path, *, arch: str | None = None) -> Path:
    tg = ensure_tg_layout(project_root, arch=arch)
    for rel in ("closure", "replay"):
        (tg / rel).mkdir(parents=True, exist_ok=True)
    return tg / "closure"


def ensure_ce_layout(project_root: Path, *, arch: str | None = None) -> Path:
    root = ensure_control_layout(project_root, arch=arch)
    ce = root / CE_SUBDIR
    ce.mkdir(parents=True, exist_ok=True)
    for rel in ("intent", "impact", "verify", "review"):
        (ce / rel).mkdir(parents=True, exist_ok=True)
    return ce


def ensure_memory_layout(project_root: Path, *, arch: str | None = None) -> Path:
    root = ensure_control_layout(project_root, arch=arch)
    for rel in (f"{MEMORY_SUBDIR}/candidate", f"{MEMORY_SUBDIR}/stable"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    return root / MEMORY_SUBDIR


def ensure_agent_layout(project_root: Path, *, arch: str | None = None) -> Path:
    """Backward-compatible full layout.

    Prefer ``ensure_control_layout`` / ``ensure_uo_layout`` / ``ensure_tg_layout``
    at workflow entry points so unused product trees are not pre-created.
    """
    result = migrate_legacy_agent_dir(project_root, arch=arch)
    if result.get("ok") is False:
        raise ValueError(f"{result.get('error')}: {result.get('message')}")
    root = agent_root(project_root, arch)
    for rel in (
        UO_SUBDIR,
        TG_SUBDIR,
        CE_SUBDIR,
        f"{MEMORY_SUBDIR}/candidate",
        f"{MEMORY_SUBDIR}/stable",
        RUNS_SUBDIR,
        CONTEXT_SUBDIR,
        STATE_SUBDIR,
        f"{TG_SUBDIR}/closure",
        f"{TG_SUBDIR}/replay",
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)
    return root


def global_memory_root() -> Path:
    return Path.home() / ".ascendc-pilot" / "global-memory"
