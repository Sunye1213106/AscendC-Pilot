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

#: Env vars that may name the operator source root (project / op_src).
PROJECT_ENV_VARS = ("ASCENDC_PROJECT_ROOT", "UO_OP_DIR")
ARCH_ENV_VARS = ("UO_ARCH", "ASCENDC_ARCH")


def pilot_checkout_root() -> Path:
    """The AscendC-Pilot repository checkout (this package lives under pilot/)."""
    # .../pilot/ascendc_pilot/paths/__init__.py → parents[2] = AscendC-Pilot
    return Path(__file__).resolve().parents[2]


def is_under_pilot_checkout(path: Path) -> bool:
    """True when ``path`` resolves inside the AscendC-Pilot checkout."""
    try:
        Path(path).expanduser().resolve().relative_to(pilot_checkout_root())
        return True
    except ValueError:
        return False


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
                    "(e.g. ops-transformer/.../flash_attention_score_grad)."
                )
        return root

    raise ValueError(
        "operator root unresolved: none of the candidates is an existing directory: "
        + ", ".join(str(c) for c in candidates)
    )


def resolve_arch(explicit: str | None = None) -> str:
    """Architecture subdirectory name under ``.ascendc-pilot/``."""
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    for name in ARCH_ENV_VARS:
        raw = (os.environ.get(name) or "").strip()
        if raw:
            return raw
    return "arch35"


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
    return root / AGENT_DIR / resolve_arch(arch)


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
    del op_name
    return agent_root(project_root, arch) / UO_SUBDIR


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
    """Migrate flat ``.ascendc-pilot/`` → ``.ascendc-pilot/<arch>/`` when needed.

    Also migrates ``.ascendc-agent`` → ``.ascendc-pilot`` when only legacy exists.
    """
    root = Path(project_root).expanduser().resolve()
    legacy = root / LEGACY_AGENT_DIR
    modern = root / AGENT_DIR
    arch_name = resolve_arch(arch)
    target = modern / arch_name

    if modern.exists() and legacy.exists():
        return {
            "ok": False,
            "error": "both_agent_dirs_exist",
            "message": "Both .ascendc-agent and .ascendc-pilot exist; refuse automatic merge.",
        }
    if not modern.exists() and legacy.exists():
        shutil.move(str(legacy), str(modern))

    if not modern.exists():
        return {"ok": True, "migrated": False, "root": ""}

    # Flat layout (uo/tg at top of .ascendc-pilot) → nest under <arch>/.
    flat_markers = (modern / UO_SUBDIR, modern / TG_SUBDIR, modern / STATE_SUBDIR)
    if any(p.exists() for p in flat_markers) and not target.exists():
        target.mkdir(parents=True, exist_ok=True)
        for name in (
            UO_SUBDIR, TG_SUBDIR, CE_SUBDIR, MEMORY_SUBDIR,
            RUNS_SUBDIR, CONTEXT_SUBDIR, STATE_SUBDIR,
        ):
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
    migrate_legacy_agent_dir(project_root, arch=arch)
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
    (root / CE_SUBDIR).mkdir(parents=True, exist_ok=True)
    return root / CE_SUBDIR


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
    migrate_legacy_agent_dir(project_root, arch=arch)
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
