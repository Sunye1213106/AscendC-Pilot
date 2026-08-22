# -*- coding: utf-8 -*-
"""CLI intake gates: operator --project, architecture, and existing .uo CodeMap.

Two start modes (Spec SSOT):
- ``requires_architecture`` (uo-init / uo-update): ``arch*`` folders distinguish
  implementations. No such folders → product slot ``default`` (one implementation).
- ``requires_uo_product`` (tg-*/ce-*/uo-query/uo-investigate): architecture comes
  from an existing ``.uo``. Missing CodeMap is a human fork, not a search problem:
  the product path is determined (``.ascendc-pilot/<arch>/uo/<op>.<arch>.uo``).
  Query workflows offer ``/uo-init`` or answer-from-source; TG/CE still require
  ``/uo-init``. Never Glob/dir the tree to find a ``.uo``.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

from ascendc_pilot.paths import is_under_pilot_checkout, opencode_home, pilot_checkout_root
from uo_init.source_layout import (
    ARCH_DIR_RE,
    UNIFIED_ARCH_DIR,
    is_product_architecture,
    match_on_disk_architecture,
)

_ARCH_TOKEN = re.compile(r"\barch[0-9A-Za-z._-]+\b", re.I)

LAST_PROJECT_CACHE = opencode_home() / "ascendc-last-project"
HARNESS_BIN_CACHE = opencode_home() / "ascendc-harness-bin"

# Host Driver cannot pop AskQuestion with zero options (ses_fe7f).
PROJECT_SWITCH_OPTIONS = [
    {"label": "我已换到算子目录或空目录，请重新贴 PR / 再试", "value": "retry_elsewhere"},
    {"label": "停止本次目标", "value": "stop"},
]
ARCHITECTURE_FALLBACK_OPTIONS = [
    {"label": "稍后手工指定 architecture 再试", "value": "retry"},
    {"label": "停止本次目标", "value": "stop"},
]


def _last_project_cache_path() -> Path:
    """Prefer the intake wrapper's LAST_PROJECT_CACHE so tests can monkeypatch it."""
    mod = sys.modules.get("ascendc_pilot.intake")
    if mod is not None:
        override = getattr(mod, "LAST_PROJECT_CACHE", None)
        if override is not None:
            return Path(override)
    return LAST_PROJECT_CACHE


def _workflows_need_arch() -> frozenset[str]:
    from ascendc_pilot.workflows import workflows_needing_architecture

    return workflows_needing_architecture()


def _workflows_need_operator() -> frozenset[str]:
    from ascendc_pilot.workflows import workflows_needing_project

    return workflows_needing_project()


def _workflows_need_uo() -> frozenset[str]:
    from ascendc_pilot.workflows import workflows_needing_uo_product

    return workflows_needing_uo_product()


def looks_like_operator_package(root: Path | str | None) -> bool:
    """True when root has op_host / op_kernel style operator layout."""
    if root is None:
        return False
    path = Path(root).expanduser().resolve()
    if not path.is_dir():
        return False
    return (path / "op_host").is_dir() or (path / "op_kernel").is_dir()


def is_pilot_harness_root(root: Path | str | None) -> bool:
    """True when root is the AscendC-Pilot checkout (engines/pilot present)."""
    if root is None:
        return False
    path = Path(root).expanduser().resolve()
    try:
        if path == pilot_checkout_root():
            return True
    except Exception:
        pass
    return (path / "pilot" / "ascendc_pilot").is_dir() and (path / "engines").is_dir()


def _is_usable_operator(root: Path | str | None) -> bool:
    """Operator package that is not the Pilot checkout (or a path under it)."""
    if root is None or not str(root).strip():
        return False
    path = Path(root).expanduser()
    try:
        path = path.resolve()
    except OSError:
        return False
    if is_pilot_harness_root(path):
        return False
    try:
        if is_under_pilot_checkout(path):
            return False
    except Exception:
        pass
    return looks_like_operator_package(path)


def _env_operator() -> Path | None:
    for name in ("ASCENDC_PROJECT_ROOT", "UO_OP_DIR"):
        raw = (os.environ.get(name) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        try:
            path = path.resolve()
        except OSError:
            continue
        if _is_usable_operator(path):
            return path
    return None


def _explicit_basename(explicit: Path | str | None) -> str:
    text = str(explicit or "").strip().replace("\\", "/").rstrip("/")
    if not text:
        return ""
    return Path(text).name


def _explicit_is_weak(explicit: Path | str | None, resolved: Path) -> bool:
    """True when --project is a Host-cwd artifact, not a chosen operator dir.

    Bare names and paths under the Pilot checkout are the lethal OpenCode case:
    ``pilot_cli`` ``uo-query --project flash_attention_score_grad`` from the Host checkout
    resolves to ``<Pilot>/flash_attention_score_grad`` (missing / not an operator).
    Existing non-operator dirs outside the checkout stay explicit so intake can
    AskQuestion instead of silently swapping in last-project cache.
    """
    raw = Path(str(explicit or "").strip())
    try:
        if not raw.expanduser().is_absolute():
            return True
    except OSError:
        return True
    if is_pilot_harness_root(resolved):
        return True
    try:
        if is_under_pilot_checkout(resolved):
            return True
    except Exception:
        pass
    return not resolved.exists()


def _fallback_operator(
    *,
    explicit: Path | str | None = None,
    allow_last_project: bool = True,
) -> Path | None:
    cached = read_last_project_cache() if allow_last_project else None
    name = _explicit_basename(explicit)
    if cached is not None and name and name.lower() == cached.name.lower():
        return cached
    env_path = _env_operator() if allow_last_project else None
    if env_path is not None:
        return env_path
    cwd = Path.cwd().resolve()
    if _is_usable_operator(cwd):
        return cwd
    if cached is not None:
        return cached
    return None


def _count_sources(dir_path: Path) -> int:
    if not dir_path.is_dir():
        return 0
    n = 0
    for p in dir_path.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".cpp", ".cc", ".cxx", ".h", ".hpp", ".c"}:
            n += 1
    return n


def discover_architectures(root: Path | str | None) -> list[str]:
    """List arch* dirs under op_host / op_kernel (no invented fallback names)."""
    if root is None:
        return []
    path = Path(root).expanduser().resolve()
    found: list[str] = []
    for side in ("op_host", "op_kernel"):
        base = path / side
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            name = child.name
            if child.is_dir() and ARCH_DIR_RE.fullmatch(name):
                if name not in found:
                    found.append(name)
    return found


def architecture_from_intent(intent: str, known_archs: list[str] | tuple[str, ...]) -> str:
    """Return the unique on-disk ``arch*`` named in an answer/init turn, else ``""``.

    Never invents an architecture. Long side questions that mention arch35
    (「先别建库，问 arch35…」) must not silently pin.
    """
    from ascendc_pilot.goal_turn import is_architecture_pin_turn

    names = [str(a).strip() for a in known_archs if str(a).strip()]
    if not names:
        return ""
    raw = str(intent or "").strip()
    if not raw:
        return ""
    allowed_l = {a.lower(): a for a in names}
    compact = re.sub(r"\s+", "", raw).strip().lower()
    exact = allowed_l.get(compact)
    if exact:
        return exact
    if re.fullmatch(r"(?:arch[0-9A-Za-z._-]+|dav[_-]?9201|9201)", compact, re.I):
        mapped = match_on_disk_architecture(compact, names)
        if mapped in set(names):
            return mapped
    if not is_architecture_pin_turn(raw):
        return ""
    found: list[str] = []
    for token in _ARCH_TOKEN.findall(raw):
        hit = allowed_l.get(token.lower())
        if not hit:
            mapped = match_on_disk_architecture(token, names)
            hit = mapped if mapped in set(names) else None
        if hit and hit not in found:
            found.append(hit)
    if len(found) == 1:
        return found[0]
    return ""


def describe_architectures(root: Path | str | None) -> list[dict[str, str]]:
    """Structured AskQuestion options derived only from on-disk arch* folders."""
    path = Path(root).expanduser().resolve() if root else None
    names = discover_architectures(path) if path else []
    options: list[dict[str, str]] = []
    for name in names:
        bits: list[str] = []
        for side in ("op_host", "op_kernel"):
            d = path / side / name  # type: ignore[operator]
            if d.is_dir():
                bits.append(f"{side}/{name}: {_count_sources(d)} sources")
        for side in ("op_host", "op_kernel"):
            shared = 0
            base = path / side  # type: ignore[operator]
            if base.is_dir():
                for f in base.iterdir():
                    if f.is_file() and f.suffix.lower() in {".cpp", ".h", ".hpp", ".c"}:
                        shared += 1
            if shared:
                bits.append(f"{side}/* shared: {shared} files")
        options.append(
            {
                "label": name,
                "description": "; ".join(bits) if bits else f"found under op_host|op_kernel/{name}",
            }
        )
    return options


def _list_dir_names(dir_path: Path, *, max_entries: int = 64) -> list[str]:
    if not dir_path.is_dir():
        return []
    names: list[str] = []
    try:
        for child in sorted(dir_path.iterdir(), key=lambda p: p.name.lower()):
            if child.name.startswith("."):
                continue
            suffix = "/" if child.is_dir() else ""
            names.append(f"{child.name}{suffix}")
            if len(names) >= max_entries:
                names.append("…")
                break
    except OSError:
        return []
    return names


def scan_operator_directory(root: Path | str | None) -> dict[str, Any]:
    """Fast operator-layout scan for agent arch selection (no repo archaeology).

    Scopes to ``op_host`` / ``op_kernel`` only. Returns a compact JSON summary the
    agent should read, then AskQuestion from ``architecture_option_details``.
    """
    if root is None:
        return {
            "ok": False,
            "error": "project_required",
            "message_zh": "需要 --project 算子目录",
        }
    path = Path(root).expanduser().resolve()
    if not path.is_dir():
        return {
            "ok": False,
            "error": "project_not_dir",
            "project": str(path),
            "message_zh": f"路径不是目录：{path}",
        }
    if is_pilot_harness_root(path):
        return {
            "ok": False,
            "error": "pilot_checkout_forbidden",
            "project": str(path),
            "message_zh": "禁止把 AscendC-Pilot 仓根当作算子目录",
        }
    if not looks_like_operator_package(path):
        return {
            "ok": False,
            "error": "not_operator_package",
            "project": str(path),
            "top_level": _list_dir_names(path),
            "message_zh": "未找到 op_host/ 或 op_kernel/；请确认 --project 指向算子包",
        }

    details = describe_architectures(path)
    arches = [str(o.get("label") or "") for o in details if o.get("label")]
    layout = {
        "top_level": _list_dir_names(path),
        "op_host": _list_dir_names(path / "op_host"),
        "op_kernel": _list_dir_names(path / "op_kernel"),
    }
    ask_options = [
        {
            "label": str(o.get("label") or ""),
            "description": str(o.get("description") or ""),
        }
        for o in details
    ]
    pinned: list[str] = []
    try:
        from ascendc_pilot.run_resume import load_pr_architecture_pin

        pinned = load_pr_architecture_pin(path)
    except Exception:  # noqa: BLE001
        pinned = []
    unique_pin = len(pinned) == 1 and pinned[0] in arches
    unified = not arches
    if unified:
        slot = UNIFIED_ARCH_DIR
        out: dict[str, Any] = {
            "ok": True,
            "project": str(path),
            "op_name": path.name,
            "layout": layout,
            "architectures": [],
            "architecture_options": [],
            "architecture_option_details": [],
            "architecture": slot,
            "selected_by": "unified_implementation",
            "unified_implementation": True,
            "ask_question": None,
            "message_zh": (
                "未扫到 arch* 目录：按一套源码一起构建，产物槽是 "
                f"`{slot}`。不要发明 arch35。"
            ),
            "suggested_command": (
                f'pilot_run workflow=uo-init project="{path}" architecture={slot}'
            ),
        }
        return out
    out: dict[str, Any] = {
        "ok": True,
        "project": str(path),
        "op_name": path.name,
        "layout": layout,
        "architectures": arches,
        "architecture_options": arches,
        "architecture_option_details": details,
        "ask_question": None
        if unique_pin
        else (
            {
                "header": "选择架构",
                "question": "请选择要建立知识库的目标架构（选项来自算子目录 op_host|op_kernel/arch*）：",
                "options": ask_options,
            }
            if arches
            else None
        ),
        "message_zh": (
            f"changed-files 已唯一确定 architecture `{pinned[0]}`。"
            "请将该值用于后续 `pilot_run`；不要再询问架构。"
            if unique_pin
            else (
                f"扫描到 {len(arches)} 个 architecture：{', '.join(arches)}。"
                "阅读 layout 后用 AskQuestion 选项原样提问；禁止 Glob 仓根或翻 cmake/classify_rule。"
            )
        ),
        "suggested_command": (
            f'pilot_run workflow=uo-init project="{path}" architecture={pinned[0]}'
            if unique_pin
            else f'pilot_run workflow=uo-init project="{path}" architecture=<arch*>'
        ),
    }
    if unique_pin:
        out["architecture"] = pinned[0]
        out["selected_by"] = "pr_changed_files"
    return out


def parse_uo_product_name(path: Path) -> dict[str, str]:
    """Parse ``<op>.<arch>.uo`` filename into op_name / architecture."""
    stem = path.name[: -len(path.suffix)] if path.suffix == ".uo" else path.stem
    parts = stem.rsplit(".", 1)
    if len(parts) == 2 and is_product_architecture(parts[1]):
        return {"op_name": parts[0], "architecture": parts[1], "path": str(path)}
    return {"op_name": stem, "architecture": "", "path": str(path)}


def discover_uo_products(root: Path | str | None) -> list[dict[str, str]]:
    """List finalized CodeMap products under ``.ascendc-pilot/<arch>/uo/*.uo``.

    Top-level ``.ascendc-pilot/uo/*.uo`` is not a product and is not listed.
    """
    if root is None:
        return []
    base = Path(root).expanduser().resolve() / ".ascendc-pilot"
    if not base.is_dir():
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    search_dirs: list[Path] = []
    for child in sorted(base.iterdir()):
        if child.is_dir() and is_product_architecture(child.name):
            search_dirs.append(child / "uo")
    for product_dir in search_dirs:
        if not product_dir.is_dir():
            continue
        for path in sorted(product_dir.glob("*.uo")):
            if not path.is_file():
                continue
            key = path.resolve().as_posix()
            if key in seen:
                continue
            seen.add(key)
            out.append(parse_uo_product_name(path))
    return out


def describe_uo_products(root: Path | str | None) -> list[dict[str, str]]:
    """AskQuestion options derived from existing ``.uo`` products."""
    options: list[dict[str, str]] = []
    for item in discover_uo_products(root):
        arch = item.get("architecture") or ""
        op_name = item.get("op_name") or ""
        label = arch or Path(item["path"]).name
        options.append(
            {
                "label": label,
                "description": f"{op_name}.{arch}.uo" if arch else Path(item["path"]).name,
                "architecture": arch,
                "op_name": op_name,
                "path": item["path"],
            }
        )
    return options


def read_last_project_cache() -> Path | None:
    cache = _last_project_cache_path()
    try:
        if not cache.is_file():
            return None
        root = Path(cache.read_text(encoding="utf-8").strip())
        if _is_usable_operator(root):
            return root.resolve()
    except Exception:
        return None
    return None


def write_last_project_cache(root: Path | str) -> None:
    path = Path(root).expanduser().resolve()
    if not _is_usable_operator(path):
        return
    cache = _last_project_cache_path()
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(str(path), encoding="utf-8")
    except Exception:
        pass


def write_harness_bin_cache(acp_bin: Path | str) -> None:
    try:
        p = Path(acp_bin).expanduser().resolve()
        if not p.is_file():
            return
        HARNESS_BIN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        HARNESS_BIN_CACHE.write_text(str(p), encoding="utf-8")
    except Exception:
        pass


def architecture_from_env() -> str:
    for name in ("UO_ARCH", "ASCENDC_ARCH"):
        raw = (os.environ.get(name) or "").strip()
        if raw:
            return raw
    return ""


def default_cli_project(
    explicit: Path | str | None = None,
    *,
    allow_last_project: bool = True,
) -> Path:
    """Resolve --project so OpenCode cwd ≠ artifact root.

    Order:
    1. explicit ``--project`` when it is a real operator (not Pilot checkout)
    2. invalid explicit (bare name, missing path, path under Pilot, non-operator)
       falls through: basename match vs last-project cache → env → cwd → cache
    3. ``ASCENDC_PROJECT_ROOT`` / ``UO_OP_DIR``
    4. cwd if it is already an operator package
    5. last-project cache (conversation-pinned operator) when cwd is anything else
       (monorepo parent, Pilot checkout, random folder)
    6. cwd (will fail intake if not an operator)

    ``allow_last_project=False`` for ``workflow=auto`` / ``goal-intake`` so a
    previous conversation cannot hijack this Goal's operator identity.

    Never returns the Pilot checkout as a successful operator root. A bare
    ``--project flash_attention_score_grad`` issued from the Host checkout must
    not resolve to ``<Pilot>/flash_attention_score_grad``.
    """
    if explicit is not None and str(explicit).strip():
        path = Path(explicit).expanduser().resolve()
        if _is_usable_operator(path):
            return path
        if _explicit_is_weak(explicit, path):
            fallback = _fallback_operator(
                explicit=explicit, allow_last_project=allow_last_project
            )
            if fallback is not None:
                return fallback
        elif allow_last_project:
            env_path = _env_operator()
            if env_path is not None:
                return env_path
        return path
    fallback = _fallback_operator(allow_last_project=allow_last_project)
    if fallback is not None:
        return fallback
    return Path.cwd().resolve()


def assert_operator_project(root: Path | str, *, action: str = "") -> dict[str, Any] | None:
    """Refuse creating/using ``.ascendc-pilot`` outside an operator package."""
    path = Path(root).expanduser().resolve()
    if _is_usable_operator(path):
        return None
    label = f" Action={action}" if action else ""
    return {
        "ok": False,
        "needs_human_decision": True,
        "decision_kind": "project",
        "reason_code": "OPERATOR_PROJECT_REQUIRED",
        "project": str(path),
        "message_zh": (
            f"拒绝在非算子目录创建/使用 .ascendc-pilot/{label}。\n"
            f"当前路径: {path}\n"
            "请把 --project 指到含 op_host/ 或 op_kernel/ 的算子目录；"
            "若只有 PR 链接，请在 OpenCode 打开算子仓或空工作区后再启动。"
        ),
        "ask_question": {
            "prompt_zh": "请确认算子源码目录（含 op_host/ 或 op_kernel/）",
            "options": list(PROJECT_SWITCH_OPTIONS),
            "allow_free_text": True,
            "field": "project",
        },
    }


def assert_operator_if_required(root: Path | str, *, action: str = "") -> dict[str, Any] | None:
    """Skip the operator fence for live workflows that declare ``requires_project=False``.

    Empty / unknown state still asserts so ``run-action prepare`` cannot land
    ``.ascendc-pilot`` on a random cwd.
    """
    from ascendc_pilot.state import load_state
    from ascendc_pilot.workflows import workflow_requires_project

    path = Path(root).expanduser().resolve()
    try:
        st = load_state(path) or {}
    except Exception:  # noqa: BLE001
        st = {}
    wid = str(st.get("workflow_id") or "").strip()
    if wid and not workflow_requires_project(wid):
        return None
    return assert_operator_project(path, action=action)


def _attach_intake_request(payload: dict[str, Any], root: Path) -> dict[str, Any]:
    from ascendc_pilot.human_interaction import KIND_INTAKE, attach_interaction_request

    return attach_interaction_request(
        payload,
        root,
        kind=KIND_INTAKE,
        decision_kind=str(payload.get("decision_kind") or "intake"),
    )


# Query-like workflows may answer from operator sources when CodeMap is absent.
# TG/CE consume the product as authority and cannot fall back to source answering.
QUERY_SOURCE_FALLBACK_WORKFLOWS = frozenset({"uo-query", "uo-investigate"})


def expected_uo_product_path(
    root: Path | str,
    *,
    architecture: str = "",
    op_name: str = "",
) -> str:
    """Determined product path. Do not Glob; this is the only location."""
    root_p = Path(root).expanduser().resolve()
    arch = (architecture or "").strip() or "<arch>"
    name = (op_name or root_p.name or "<op>").replace("/", "_").replace("\\", "_")
    return str(root_p / ".ascendc-pilot" / arch / "uo" / f"{name}.{arch}.uo")


def missing_uo_product_payload(
    *,
    root: Path | str,
    workflow_id: str,
    architecture: str = "",
    op_name: str = "",
    persist: bool = True,
) -> dict[str, Any]:
    """Human fork when the determined ``.uo`` path is empty.

    Query: ``uo-init`` (rebuild CodeMap) or ``source`` (answer from sources).
    TG/CE: ``uo-init`` only. Never search the tree for another product.
    """
    root_p = Path(root).expanduser().resolve()
    wf = (workflow_id or "").strip() or "uo-query"
    allow_source = wf in QUERY_SOURCE_FALLBACK_WORKFLOWS
    expected = expected_uo_product_path(
        root_p, architecture=architecture, op_name=op_name
    )
    options: list[dict[str, str]] = [
        {
            "label": "先 /uo-init 建立 CodeMap",
            "value": "uo-init",
            "description": "在当前算子目录重建 .uo，然后再查询/启动本工作流",
        },
    ]
    if allow_source:
        options.append(
            {
                "label": "回退到源码作答",
                "value": "source",
                "description": "本次不查 CodeMap，只读算子源码回答；禁止 Glob/dir 找 .uo",
            }
        )
    question = (
        f"未找到确定路径的 CodeMap：`{expected}`。\n"
        "不要 Glob/dir/Grep 找 `.uo`，不要猜 `--op-name`。\n"
        + (
            "请选择：先 `/uo-init` 建库，或回退到源码作答。"
            if allow_source
            else f"不能启动 `{wf}`：请先 `/uo-init` 建立 CodeMap。"
        )
    )
    ask = {
        "header": "缺少 CodeMap",
        "question": question,
        "prompt_zh": question,
        "options": options,
        "allow_free_text": False,
        "field": "next_workflow",
    }
    payload: dict[str, Any] = {
        "ok": False,
        "needs_human_decision": True,
        "decision_kind": "uo_product",
        "reason_code": "UO_PRODUCT_REQUIRED",
        "workflow_id": wf,
        "project": str(root_p),
        "architecture": (architecture or "").strip(),
        "expected_path": expected,
        "message_zh": question,
        "ask_question": ask,
        "suggested_command": (
            f'pilot_run workflow=uo-init project="{root_p}" architecture=<arch*>'
        ),
        "primary_instruction_zh": (
            "立刻用 question/AskQuestion 弹出可点选框，选项必须原样使用。"
            "若用户打断并在对话里回复，改为 interpret-user-turn，不要重问上一题。"
            "禁止 Glob/dir/tree 找 `.uo`，禁止猜 `--op-name`。"
            + (
                "选 uo-init → `pilot_run` workflow=uo-init；"
                "选 source → 只读算子源码作答，不要再调 `pilot_cli` `uo-query`。"
                if allow_source
                else "选 uo-init 后启动 `/uo-init`。"
            )
        ),
        "host_step": {
            "kind": "ask_human",
            "message_zh": question,
            "ask_question": ask,
        },
    }
    if persist:
        return _attach_intake_request(payload, root_p)
    return payload


def _uo_product_gate(
    *,
    root: Path,
    workflow_id: str,
    architecture: str,
) -> dict[str, Any] | None:
    """For TG/CE/query consumers: require .uo and resolve architecture from it."""
    products = discover_uo_products(root)
    if not products:
        return missing_uo_product_payload(
            root=root,
            workflow_id=workflow_id,
            architecture=architecture,
        )

    by_arch = {
        str(p.get("architecture") or ""): p
        for p in products
        if str(p.get("architecture") or "").strip()
    }
    arches = sorted(by_arch)
    arch = (architecture or "").strip()

    if arch and arch not in by_arch:
        details = describe_uo_products(root)
        ask_opts = [
            {
                "label": o["label"],
                "value": o.get("architecture") or o["label"],
                "description": o.get("description") or "",
            }
            for o in details
        ]
        return _attach_intake_request(
            {
                "ok": False,
                "needs_human_decision": True,
                "decision_kind": "architecture",
                "reason_code": "ARCHITECTURE_NOT_IN_UO",
                "workflow_id": workflow_id,
                "project": str(root),
                "architecture": arch,
                "architecture_options": arches,
                "architecture_option_details": details,
                "uo_products": products,
                "message_zh": (
                    f"指定的 architecture={arch} 没有对应的 `.uo` CodeMap。"
                    f"已有产物: {', '.join(Path(p['path']).name for p in products)}。"
                    "请改用已有 CodeMap 的架构，或先 /uo-init 建立该架构。"
                ),
                "ask_question": {
                    "prompt_zh": "请选择已有 CodeMap 的 architecture",
                    "options": ask_opts,
                    "allow_free_text": False,
                    "field": "architecture",
                },
                "suggested_command": (
                    f'pilot_run workflow={workflow_id} project="{root}" architecture=<{",".join(arches)}>'
                    if arches
                    else f'pilot_run workflow=uo-init project="{root}" architecture=<arch*>'
                ),
            },
            root,
        )

    if not arch:
        if len(arches) == 1:
            return {
                "ok": True,
                "resolved_architecture": arches[0],
                "resolved_from": "uo_product",
                "uo_product": by_arch[arches[0]].get("path") or "",
            }
        details = describe_uo_products(root)
        ask_opts = [
            {
                "label": o["label"],
                "value": o.get("architecture") or o["label"],
                "description": o.get("description") or "",
            }
            for o in details
        ]
        return _attach_intake_request(
            {
                "ok": False,
                "needs_human_decision": True,
                "decision_kind": "architecture",
                "reason_code": "UO_ARCHITECTURE_REQUIRED",
                "workflow_id": workflow_id,
                "project": str(root),
                "architecture_options": arches,
                "architecture_option_details": details,
                "uo_products": products,
                "message_zh": (
                    f"存在多个 CodeMap，请选择要用哪一个架构: {', '.join(arches)}。"
                    "TG/CE 以 `.uo` 为准，不从源码目录另选 arch*。"
                ),
                "ask_question": {
                    "prompt_zh": "请选择已有 CodeMap 的 architecture",
                    "options": ask_opts,
                    "allow_free_text": False,
                    "field": "architecture",
                },
                "suggested_command": (
                    f'pilot_run workflow={workflow_id} project="{root}" architecture=<{",".join(arches)}>'
                ),
                "primary_instruction_zh": (
                    "选项必须来自已有 `.uo`；禁止编造未建库的 arch。"
                ),
            },
            root,
        )

    return {
        "ok": True,
        "resolved_architecture": arch,
        "resolved_from": "cli_or_env_matched_uo",
        "uo_product": (by_arch.get(arch) or {}).get("path") or "",
    }


def _workspace_engine():
    import sys

    root = Path(__file__).resolve().parents[2]
    ws = root / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import git_workspace as gw  # type: ignore[import-not-found]

    return gw


def extract_pr_url_from_intent(text: str) -> str:
    """First allowlisted PR URL in the user turn, or empty."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    try:
        return str(_workspace_engine().extract_pr_url(raw) or "")
    except Exception:  # noqa: BLE001
        return ""


def _pilot_workspace_forbidden(root: Path) -> bool:
    if is_pilot_harness_root(root):
        return True
    try:
        return is_under_pilot_checkout(root)
    except Exception:  # noqa: BLE001
        return False


def _resolve_operator_from_pr_workspace(
    root: Path, intent: str, workflow_id: str
) -> dict[str, Any] | None:
    """Checkout PR into OpenCode workspace and pin an operator, or AskQuestion.

    Returns None when intent has no PR URL (caller keeps the original operator gate).
    """
    url = extract_pr_url_from_intent(intent)
    if not url:
        return None
    if _pilot_workspace_forbidden(root):
        return {
            "ok": False,
            "needs_human_decision": True,
            "decision_kind": "project",
            "reason_code": "PILOT_CHECKOUT_FORBIDDEN",
            "workflow_id": workflow_id,
            "project": str(root),
            "pr_url": url,
            "message_zh": (
                "当前 OpenCode 工作区是 AscendC-Pilot 仓，禁止把算子源码 clone 进来。"
                "请打开算子目录、算子仓根目录，或空目录后再贴 PR。"
            ),
            "ask_question": {
                "prompt_zh": "请换到算子目录、算子仓或空工作区",
                "options": list(PROJECT_SWITCH_OPTIONS),
                "allow_free_text": True,
                "field": "project",
            },
        }
    try:
        acquire = _workspace_engine().acquire_pull_request(url, workspace_root=root)
    except Exception as exc:  # noqa: BLE001
        acquire = {
            "ok": False,
            "error": "WORKSPACE_ACQUIRE_FAILED",
            "message_zh": str(exc)[:400],
        }
    if not acquire.get("ok"):
        return {
            "ok": False,
            "needs_human_decision": True,
            "decision_kind": "project",
            "reason_code": str(acquire.get("error") or "WORKSPACE_ACQUIRE_FAILED"),
            "workflow_id": workflow_id,
            "project": str(root),
            "pr_url": url,
            "message_zh": str(
                acquire.get("message_zh")
                or "无法在当前工作区获取 PR 源码。请检查鉴权，或改用本地算子目录。"
            ),
            "ask_question": {
                "prompt_zh": "获取 PR 失败。请重试、改用本地算子目录，或换空工作区。",
                "options": [
                    {"label": "改用本地算子目录", "value": "local"},
                ],
                "allow_free_text": True,
                "field": "project",
            },
        }
    roots = [Path(p) for p in (acquire.get("operator_roots") or []) if str(p).strip()]
    if len(roots) == 1:
        return {
            "ok": True,
            "project": str(roots[0]),
            "pr_url": url,
            "worktree_head": acquire.get("worktree_head") or str(root),
        }
    if not roots:
        return {
            "ok": False,
            "needs_human_decision": True,
            "decision_kind": "project",
            "reason_code": "OPERATOR_ROOTS_EMPTY",
            "workflow_id": workflow_id,
            "project": str(root),
            "pr_url": url,
            "changed_files": list(acquire.get("changed_files") or []),
            "message_zh": (
                "这次 PR 改动没有落到含 op_host/ 或 op_kernel/ 的算子目录。"
                "请选择算子，或改用本地代码。"
            ),
            "ask_question": {
                "prompt_zh": "请选择要使用的算子目录（含 op_host/ 或 op_kernel/）",
                "options": list(PROJECT_SWITCH_OPTIONS),
                "allow_free_text": True,
                "field": "project",
            },
        }
    return {
        "ok": False,
        "needs_human_decision": True,
        "decision_kind": "project",
        "reason_code": "MULTI_OPERATOR",
        "workflow_id": workflow_id,
        "project": str(root),
        "pr_url": url,
        "operator_roots": [str(p) for p in roots],
        "message_zh": "这次改动跨多个算子目录，请选择要使用的算子。",
        "ask_question": {
            "prompt_zh": "请选择要使用的算子",
            "options": [
                {"label": p.name, "value": str(p), "description": str(p)} for p in roots
            ],
            "allow_free_text": True,
            "field": "project",
        },
    }


def prepare_workflow_start(
    *,
    project: Path | str,
    workflow_id: str,
    architecture: str = "",
    project_explicit: bool = False,
    intent: str = "",
) -> dict[str, Any]:
    """Validate start inputs and resolve architecture.

    Always returns a dict:
    - ok True → ``architecture`` is ready for Host ``pilot_run``
    - ok False → AskQuestion / needs_human_decision payload
    """
    wf = (workflow_id or "").strip()
    root = Path(project).expanduser().resolve()
    arch = (architecture or "").strip() or architecture_from_env()
    intent_text = str(intent or "").strip()
    resolved_from_intent = False

    need_op = wf in _workflows_need_operator()
    need_arch = wf in _workflows_need_arch()
    need_uo = wf in _workflows_need_uo()

    if need_op:
        if not _is_usable_operator(root):
            resolved = _resolve_operator_from_pr_workspace(root, intent_text, wf)
            if resolved is not None:
                if not resolved.get("ok"):
                    return _attach_intake_request(resolved, root)
                root = Path(str(resolved["project"])).expanduser().resolve()
            else:
                bad = assert_operator_project(root)
                if bad is not None:
                    bad["workflow_id"] = wf
                    bad["suggested_command"] = (
                        f'pilot_run workflow={wf} project="<算子目录>"'
                        + (" architecture=<arch*>" if need_arch else "")
                    )
                    return _attach_intake_request(bad, root)
        if not looks_like_operator_package(root) and not project_explicit:
            return _attach_intake_request(
                {
                    "ok": False,
                    "needs_human_decision": True,
                    "decision_kind": "project",
                    "reason_code": "OPERATOR_PROJECT_UNCLEAR",
                    "workflow_id": wf,
                    "project": str(root),
                    "message_zh": (
                        f"路径 {root} 不像算子包（缺少 op_host/ 或 op_kernel/）。"
                        "请用 AskQuestion 确认 --project"
                        + ("，再与 --architecture 一起 start。" if need_arch else " 后再 start。")
                    ),
                    "ask_question": {
                        "prompt_zh": "请确认算子源码目录",
                        "options": list(PROJECT_SWITCH_OPTIONS),
                        "allow_free_text": True,
                        "field": "project",
                    },
                },
                root,
            )

    if need_uo:
        uo_gate = _uo_product_gate(root=root, workflow_id=wf, architecture=arch)
        if uo_gate is None:
            return {"ok": True, "architecture": arch, "workflow_id": wf, "project": str(root)}
        if uo_gate.get("ok") and uo_gate.get("resolved_architecture"):
            return {
                "ok": True,
                "architecture": str(uo_gate["resolved_architecture"]),
                "resolved_from": uo_gate.get("resolved_from") or "uo_product",
                "uo_product": uo_gate.get("uo_product") or "",
                "workflow_id": wf,
                "project": str(root),
            }
        return uo_gate

    if need_arch and not arch:
        options = describe_architectures(root)
        labels = [o["label"] for o in options]
        from_intent = architecture_from_intent(intent_text, labels)
        if from_intent:
            arch = from_intent
            resolved_from_intent = True
        else:
            try:
                from ascendc_pilot.run_resume import load_pr_architecture_pin

                pin = load_pr_architecture_pin(root)
            except Exception:  # noqa: BLE001
                pin = []
            if len(pin) == 1 and pin[0] in labels:
                arch = pin[0]
                resolved_from_intent = True
        if not arch:
            try:
                from ascendc_pilot.occupancy import get_session_binding

                pinned = str((get_session_binding(root) or {}).get("architecture") or "").strip()
            except Exception:  # noqa: BLE001
                pinned = ""
            if pinned and pinned in labels:
                arch = pinned
                resolved_from_intent = True
        if not arch and not options:
            arch = UNIFIED_ARCH_DIR
            resolved_from_intent = True
        if not arch:
            ask_opts = [
                {
                    "label": o["label"],
                    "value": o["label"],
                    "description": o.get("description") or "",
                }
                for o in options
            ]
            return _attach_intake_request(
                {
                    "ok": False,
                    "needs_human_decision": True,
                    "decision_kind": "architecture",
                    "reason_code": "ARCHITECTURE_REQUIRED",
                    "workflow_id": wf,
                    "project": str(root),
                    "architecture_options": labels,
                    "architecture_option_details": options,
                    "message_zh": (
                        f"缺少 architecture，不能启动。已扫描到: {', '.join(labels)}。\n"
                        "AskQuestion 选完后，用 Host "
                        f'`pilot_run workflow={wf} project="{root}" architecture=<选中>` '
                        "一次启动（此前不会创建 run）。"
                    ),
                    "ask_question": {
                        "prompt_zh": "请选择 architecture",
                        "options": ask_opts,
                        "allow_free_text": False,
                        "field": "architecture",
                    },
                    "suggested_command": (
                        f'pilot_run workflow={wf} project="{root}" architecture=<arch*>'
                    ),
                    "primary_instruction_zh": (
                        "阅读 layout 后用 AskQuestion 选项原样提问；禁止 Glob 仓根或翻 cmake/classify_rule。"
                        "若用户已在对话里写出 arch* 或换了话题，改为 interpret-user-turn，不要重问。"
                    ),
                },
                root,
            )

    if need_arch and arch and looks_like_operator_package(root):
        known = discover_architectures(root)
        if known and arch not in known:
            matched = match_on_disk_architecture(arch, known)
            if matched in known:
                arch = matched
            else:
                details = describe_architectures(root)
                ask_opts = [
                    {
                        "label": o["label"],
                        "value": o["label"],
                        "description": o.get("description") or "",
                    }
                    for o in details
                ]
                return _attach_intake_request(
                    {
                        "ok": False,
                        "needs_human_decision": True,
                        "decision_kind": "architecture",
                        "reason_code": "ARCHITECTURE_NOT_IN_TREE",
                        "workflow_id": wf,
                        "project": str(root),
                        "architecture": arch,
                        "architecture_options": known,
                        "architecture_option_details": details,
                        "message_zh": (
                            f"指定的 architecture={arch} 不在算子仓 arch* 目录中。"
                            f"仓内仅有: {', '.join(known)}。请重新选择后再 `pilot_run`。"
                        ),
                        "ask_question": {
                            "prompt_zh": "请从算子仓实际 arch* 中选择",
                            "options": ask_opts,
                            "allow_free_text": False,
                            "field": "architecture",
                        },
                        "suggested_command": (
                            f'pilot_run workflow={wf} project="{root}" architecture=<{",".join(known)}>'
                        ),
                    },
                    root,
                )
        elif not known and arch != UNIFIED_ARCH_DIR:
            return _attach_intake_request(
                {
                    "ok": False,
                    "needs_human_decision": True,
                    "decision_kind": "architecture",
                    "reason_code": "ARCHITECTURE_NOT_IN_TREE",
                    "workflow_id": wf,
                    "project": str(root),
                    "architecture": arch,
                    "architecture_options": [UNIFIED_ARCH_DIR],
                    "message_zh": (
                        f"算子没有 arch* 目录（一套实现），产物槽是 `{UNIFIED_ARCH_DIR}`。"
                        f"不能使用 architecture={arch}。"
                    ),
                    "ask_question": {
                        "prompt_zh": "没有 arch* 目录时使用 default",
                        "options": [
                            {
                                "label": UNIFIED_ARCH_DIR,
                                "value": UNIFIED_ARCH_DIR,
                                "description": "按一套源码一起构建，不要发明 arch35",
                            }
                        ],
                        "allow_free_text": False,
                        "field": "architecture",
                    },
                    "suggested_command": (
                        f'pilot_run workflow={wf} project="{root}" '
                        f"architecture={UNIFIED_ARCH_DIR}"
                    ),
                },
                root,
            )

    out: dict[str, Any] = {
        "ok": True,
        "architecture": arch,
        "workflow_id": wf,
        "project": str(root),
    }
    if resolved_from_intent:
        out["resolved_from"] = "intent"
        out["message_zh"] = f"按 {arch} 启动。"
    return out


def start_intake_gate(
    *,
    project: Path | str,
    workflow_id: str,
    architecture: str = "",
    project_explicit: bool = False,
    intent: str = "",
) -> dict[str, Any] | None:
    """Compatibility wrapper: None when start may proceed, else AskQuestion payload.

    Prefer ``prepare_workflow_start`` when the caller needs the resolved architecture.
    """
    result = prepare_workflow_start(
        project=project,
        workflow_id=workflow_id,
        architecture=architecture,
        project_explicit=project_explicit,
        intent=intent,
    )
    if result.get("ok"):
        return None
    return result
