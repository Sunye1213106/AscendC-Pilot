# -*- coding: utf-8 -*-
"""CLI intake gates: operator --project, architecture, and existing .uo CodeMap.

Two start modes (Spec SSOT):
- ``requires_architecture`` (uo-init / uo-update): choose arch* from the operator tree
- ``requires_uo_product`` (tg-*/ce-*/uo-query/uo-investigate): architecture comes
  from an existing ``.uo``. Missing CodeMap is a human fork, not a search problem:
  the product path is determined (``.ascendc-pilot/<arch>/uo/<op>.<arch>.uo``).
  Query workflows offer ``/uo-init`` or answer-from-source; TG/CE still require
  ``/uo-init``. Never Glob/dir the tree to find a ``.uo``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ascendc_pilot.paths import is_under_pilot_checkout, pilot_checkout_root

LAST_PROJECT_CACHE = Path.home() / ".config" / "opencode" / "ascendc-last-project"
HARNESS_BIN_CACHE = Path.home() / ".config" / "opencode" / "ascendc-harness-bin"


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
    ``acp uo-query --project flash_attention_score_grad`` from the Host checkout
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


def _fallback_operator(*, explicit: Path | str | None = None) -> Path | None:
    cached = read_last_project_cache()
    name = _explicit_basename(explicit)
    if cached is not None and name and name.lower() == cached.name.lower():
        return cached
    env_path = _env_operator()
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
            if child.is_dir() and re.fullmatch(r"arch\d+", name):
                if name not in found:
                    found.append(name)
    return found


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
    out: dict[str, Any] = {
        "ok": True,
        "project": str(path),
        "op_name": path.name,
        "layout": layout,
        "architectures": arches,
        "architecture_options": arches,
        "architecture_option_details": details,
        "ask_question": {
            "header": "选择架构",
            "question": "请选择要建立知识库的目标架构（选项来自算子目录 op_host|op_kernel/arch*）：",
            "options": ask_options,
        }
        if arches
        else None,
        "message_zh": (
            f"扫描到 {len(arches)} 个 architecture：{', '.join(arches)}。"
            "阅读 layout 后用 AskQuestion 选项原样提问；禁止 Glob 仓根或翻 cmake/classify_rule。"
            if arches
            else "未扫到 arch* 目录；请确认算子包布局或手工提供 architecture。"
        ),
        "suggested_command": (
            f'acp start uo-init --project "{path}" --architecture <arch*>'
            if arches
            else f'acp start uo-init --project "{path}" --architecture <arch>'
        ),
    }
    if not arches:
        out["ok"] = False
        out["error"] = "ARCHITECTURE_NOT_FOUND"
        out["reason_code"] = "ARCHITECTURE_NOT_FOUND"
    return out


def parse_uo_product_name(path: Path) -> dict[str, str]:
    """Parse ``<op>.<arch>.uo`` filename into op_name / architecture."""
    stem = path.name[: -len(path.suffix)] if path.suffix == ".uo" else path.stem
    parts = stem.rsplit(".", 1)
    if len(parts) == 2 and re.fullmatch(r"arch\d+", parts[1]):
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
        if child.is_dir() and child.name.startswith("arch"):
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
    try:
        if not LAST_PROJECT_CACHE.is_file():
            return None
        root = Path(LAST_PROJECT_CACHE.read_text(encoding="utf-8").strip())
        if _is_usable_operator(root):
            return root.resolve()
    except Exception:
        return None
    return None


def write_last_project_cache(root: Path | str) -> None:
    path = Path(root).expanduser().resolve()
    if not _is_usable_operator(path):
        return
    try:
        LAST_PROJECT_CACHE.parent.mkdir(parents=True, exist_ok=True)
        LAST_PROJECT_CACHE.write_text(str(path), encoding="utf-8")
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


def default_cli_project(explicit: Path | str | None = None) -> Path:
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

    Never returns the Pilot checkout as a successful operator root. A bare
    ``--project flash_attention_score_grad`` issued from the Host checkout must
    not resolve to ``<Pilot>/flash_attention_score_grad``.
    """
    if explicit is not None and str(explicit).strip():
        path = Path(explicit).expanduser().resolve()
        if _is_usable_operator(path):
            return path
        if _explicit_is_weak(explicit, path):
            fallback = _fallback_operator(explicit=explicit)
            if fallback is not None:
                return fallback
        else:
            env_path = _env_operator()
            if env_path is not None:
                return env_path
        return path
    fallback = _fallback_operator()
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
            "请把 --project 指到含 op_host/ 或 op_kernel/ 的算子目录"
            "（对话一开始指定的那个），不要用 OpenCode 启动目录或 monorepo 父目录。"
        ),
        "ask_question": {
            "prompt_zh": "请确认算子源码目录（含 op_host/ 或 op_kernel/）",
            "options": [],
            "allow_free_text": True,
            "field": "project",
        },
    }


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
            f'acp start uo-init --project "{root_p}" --architecture <arch*>'
        ),
        "primary_instruction_zh": (
            "立刻用 question/AskQuestion 弹出可点选框，选项必须原样使用。"
            "禁止 Glob/dir/tree 找 `.uo`，禁止猜 `--op-name`。"
            + (
                "选 uo-init → `pilot_run` workflow=uo-init；"
                "选 source → 只读算子源码作答，不要再调 acp uo-query。"
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
                    f'acp start {workflow_id} --project "{root}" --architecture <{",".join(arches)}>'
                    if arches
                    else f'acp start uo-init --project "{root}" --architecture <arch*>'
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
                    f'acp start {workflow_id} --project "{root}" --architecture <{",".join(arches)}>'
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


def prepare_workflow_start(
    *,
    project: Path | str,
    workflow_id: str,
    architecture: str = "",
    project_explicit: bool = False,
) -> dict[str, Any]:
    """Validate start inputs and resolve architecture.

    Always returns a dict:
    - ok True → ``architecture`` is ready for ``acp start``
    - ok False → AskQuestion / needs_human_decision payload
    """
    wf = (workflow_id or "").strip()
    root = Path(project).expanduser().resolve()
    arch = (architecture or "").strip() or architecture_from_env()

    need_op = wf in _workflows_need_operator()
    need_arch = wf in _workflows_need_arch()
    need_uo = wf in _workflows_need_uo()

    if need_op:
        bad = assert_operator_project(root)
        if bad is not None:
            bad["workflow_id"] = wf
            bad["suggested_command"] = (
                f'acp start {wf} --project "<算子目录>"'
                + (" --architecture <arch*>" if need_arch else "")
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
                        "options": [],
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
        if not options:
            return _attach_intake_request(
                {
                    "ok": False,
                    "needs_human_decision": True,
                    "decision_kind": "architecture",
                    "reason_code": "ARCHITECTURE_NOT_FOUND",
                    "workflow_id": wf,
                    "project": str(root),
                    "architecture_options": [],
                    "message_zh": (
                        f"在 {root} 下未发现 op_host/arch* 或 op_kernel/arch*。"
                        "请检查算子目录，或 AskQuestion 手工指定 architecture。"
                    ),
                    "ask_question": {
                        "prompt_zh": "未扫到 arch* 目录，请手工输入 architecture",
                        "options": [],
                        "allow_free_text": True,
                        "field": "architecture",
                    },
                },
                root,
            )
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
                    f"缺少 --architecture，不能启动。已扫描到: {', '.join(labels)}。\n"
                    "AskQuestion 选完后，用 "
                    f'`acp start {wf} --project "{root}" --architecture <选中>` '
                    "一次启动（此前不会创建 run）。"
                ),
                "ask_question": {
                    "prompt_zh": "请选择目标 architecture（选项来自算子仓 arch* 目录）",
                    "options": ask_opts,
                    "allow_free_text": False,
                    "field": "architecture",
                },
                "suggested_command": (
                    f'acp start {wf} --project "{root}" --architecture <{",".join(labels)}>'
                ),
                "primary_instruction_zh": (
                    "先 AskQuestion；选项必须原样使用 architecture_option_details。"
                    "选完后执行 suggested_command（带齐 --project 与 --architecture 的一次 start）。"
                    "禁止编造仓内不存在的 arch。"
                ),
            },
            root,
        )

    if need_arch and arch and looks_like_operator_package(root):
        known = discover_architectures(root)
        if known and arch not in known:
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
                        f"仓内仅有: {', '.join(known)}。请重新选择后再 start。"
                    ),
                    "ask_question": {
                        "prompt_zh": "请从算子仓实际 arch* 中选择",
                        "options": ask_opts,
                        "allow_free_text": False,
                        "field": "architecture",
                    },
                    "suggested_command": (
                        f'acp start {wf} --project "{root}" --architecture <{",".join(known)}>'
                    ),
                },
                root,
            )

    return {"ok": True, "architecture": arch, "workflow_id": wf, "project": str(root)}


def start_intake_gate(
    *,
    project: Path | str,
    workflow_id: str,
    architecture: str = "",
    project_explicit: bool = False,
) -> dict[str, Any] | None:
    """Compatibility wrapper: None when start may proceed, else AskQuestion payload.

    Prefer ``prepare_workflow_start`` when the caller needs the resolved architecture.
    """
    result = prepare_workflow_start(
        project=project,
        workflow_id=workflow_id,
        architecture=architecture,
        project_explicit=project_explicit,
    )
    if result.get("ok"):
        return None
    return result
