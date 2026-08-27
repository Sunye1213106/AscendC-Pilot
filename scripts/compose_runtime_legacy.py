#!/usr/bin/env python3
"""Compose Policy/Capability/Action/Prompt/Agent → generated/<host>/{skills,agents,prompts}."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import sys
import time
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

# Forbidden patterns in Action METHOD / task prompts (must not own workflow).
_FORBIDDEN_PATTERNS = [
    re.compile(r"(?i)while\s*\(.*phase"),
    re.compile(r"(?i)announce\s+passed"),
    re.compile(r"(?i)declare\s+(the\s+)?workflow\s+passed"),
    re.compile(r"(?i)自行宣布\s*(done|passed)"),
    re.compile(r"(?i)\bpython\s+.*\b(tg-init|tg-plan|tg-solve|build_layered_kb)\b"),
]

# Unique model-facing documents. Compose injects POLICY.md itself — there is
# no paraphrase layer. Playbooks that are not a policy stay under invariants/.
COMPOSE_POLICY_IDS: tuple[str, ...] = (
    "pilot-control",
    "human-voice",
    "evidence",
    "semantic-grounding",
    "code-access",
    "source-authority",
    "output-quality",
)
# host-runtime-contract.md stays on disk: human/CI. Not composed.

CHILD_POLICY_IDS: tuple[str, ...] = (
    "evidence",
    "output-quality",
    "semantic-grounding",
    "code-access",
)
QUERY_CHILD_IDS: frozenset[str] = frozenset({"uo-query"})
QUERY_CHILD_POLICY_IDS: tuple[str, ...] = ("code-access",)

def listed_skill_ids(repo: Path | None = None) -> tuple[str, ...]:
    """Every ``skills/<id>/SKILL.md``. Not a closed set of five."""
    root = Path(repo) if repo is not None else Path(__file__).resolve().parents[1]
    skills = root / "skills"
    if not skills.is_dir():
        return ()
    return tuple(sorted(p.parent.name for p in skills.glob("*/SKILL.md")))


# Import-time snapshot; compose/validate should call listed_skill_ids(repo).
COGNITIVE_SKILL_IDS: tuple[str, ...] = listed_skill_ids()

# Control-plane skill: Primary-invocable map of slash I/O + pipelines.
# Not a sixth cognitive skill. Never disable-model-invocation.
CONTROL_PLANE_SKILL_IDS: tuple[str, ...] = ()

ROUTER_SKILLS = frozenset(
    {
        "bind-init",
        "test-plan",
        "solve",
        "standalone-review",
        "certify",
        "proof-review",
        "source-proof",
    }
)

# LLM child agents Primary may spawn via OpenCode Task. Deterministic engines
# are not in this set. Plugin must not widen this ceiling to task: allow.
OPENCODE_PRIMARY_TASK_ALLOW: tuple[str, ...] = (
    "uo-query",
    "uo-heal-analyst",
    "uo-gap-investigator",
    "tg-analyst",
    "ce-analyst",
    "ce-applier",
    "ce-reviewer",
)


def opencode_primary_task_permission() -> dict[str, str]:
    perm: dict[str, str] = {"*": "ask"}
    for name in OPENCODE_PRIMARY_TASK_ALLOW:
        perm[name] = "allow"
    return perm


def opencode_isolated_primary_permission(
    *,
    bash_perm: Any,
    edit_perm: Any,
    write_perm: Any,
) -> dict[str, Any]:
    """AscendC-Pilot Tab permission bag.

    Do **not** set top-level ``*: deny``. OpenCode treats ``*`` as a tool glob;
    it matches ``read`` / ``glob`` / ``grep`` and can deny Primary reads even
    when those keys are ``allow``. Isolation from Build/Plan is a separate
    agent bag (plugin denies ``pilot_run`` / ``pilot_cli`` on native tabs), not a
    shared wildcard. Grep/Read/Glob stay allow so the controller can inspect.
    Tool name collision with OpenCode protocol is handled by not registering a
    plugin tool of that name; do not mention the protocol CLI in this bag.
    """
    return {
        "bash": bash_perm,
        "grep": "allow",
        "glob": "allow",
        "list": "allow",
        "read": "allow",
        "external_directory": "allow",
        "task": opencode_primary_task_permission(),
        "pilot_cli": "allow",
        "pilot_run": "allow",
        "skill": "allow",
        "question": "allow",
        "todowrite": "allow",
        "edit": edit_perm,
        "write": write_perm,
        "webfetch": "ask",
        "websearch": "ask",
        "lsp": "ask",
    }


# Checklist spec for the TG engine — not an LLM Tab / Task actor.
OPENCODE_SKIP_HOST_AGENT_IDS: frozenset[str] = frozenset()

# Slash / discovery entry metadata. Body is generated from Spec; no skills/workflows source.
# Editorial discovery prose only. cognitive_skill_id / requires_* live on Workflow Spec.
WORKFLOW_ENTRIES: dict[str, dict[str, str]] = {
    "uo-init": {
        "command_description": "建立算子知识库（Operator CodeMap / .uo）",
        "description": (
            "首次构建 AscendC 算子知识库 / Operator CodeMap（`.uo`）。"
            "semantic residual 留在 unresolved.yaml，不由 LLM 写入 canonical UO。"
            "用户要求建库、建 CodeMap、索引/分析算子时使用。禁止改用外部 MCP/通用代码图谱。"
        ),
    },
    "uo-update": {
        "command_description": "刷新已有算子知识库（增量更新 CodeMap）",
        "description": (
            "在已有 `.uo` 上按工作区 / diff / PR 变更做确定性增量更新：检测变更、按层 "
            "（host / kernel / compile / commit）选择性重建，不是再跑一遍 `uo-init`。"
            "common / 头文件变更可能扩成全量抽取。没有 `.uo` 时先 `uo-init`。"
            "用户要求刷新知识库、增量更新已有 UO/CodeMap 时使用；禁止改用外部 MCP 重新索引。"
        ),
    },
    "uo-query": {
        "command_description": "查询算子知识库（Command：直接查或委派）",
        "description": (
            "CodeMap 查询 Command，不是 Host 工作流。不要 `pilot_run`。"
            "init 先于调查；调查综合测试意图。"
        ),
    },
    "uo-investigate": {
        "command_description": "调查知识库 gap（unresolved residual）",
        "description": (
            "调查算子知识库 / `.uo` 中保留的 unresolved semantic residual：分类根因、指出 "
            "deterministic engine 缺什么能力。不修改 canonical `.uo`。用户问某个 gap 为何未闭合、"
            "或要改进 analyzer 时使用。"
        ),
    },
    "ce-review": {
        "command_description": "双轴审查 git/PR diff；结论只留在对话",
        "description": (
            "只读审查已有代码改动：GitCode PR、工作区 diff 或 base...head。"
            "无 diff 则停。Spec 轴对照当前 `{slug}_plan.md`（没有计划则从 PR/diff 索引推断粗意图并验收完成度）；"
            "Standards 轴对照仓规范。两轴并行子代理。结论留在对话，不写 ce/review。"
            "建议修改走 /ce-plan 或 /ce-apply；建议测试走 /tg-plan。用 `pilot_run`。"
        ),
    },
    "ce-plan": {
        "command_description": "把需求写成 {slug}_plan.md",
        "description": (
            "自己有需求时使用：用 UO 语义 + 用户「改什么 / 实现什么」，边问边写出 "
            "`.ascendc-pilot/<arch>/ce/plan/{slug}_plan.md`（实现分析 / 分步计划 / 明确 todo / 测试内容）。"
            "不以 PR 为输入。正式产物只有 markdown。去改码用 /ce-apply。用 `pilot_run`。"
        ),
    },
    "ce-apply": {
        "command_description": "按当前计划 markdown 的未完成 todo 改码",
        "description": (
            "按当前 `{slug}_plan.md` 未完成 todo 改 `op_host/` / `op_kernel/` / `common/` / `test_script/`，一次一条。"
            "也可按 `/tg-plan` 的 `test_harness_gap` 说明书生成或修改测试脚本（含随机数生成器）。"
            "没有未完成 todo 且没有 gap 说明书则先 /ce-plan。不内嵌双轴审查。apply 不查图。"
            "用 `pilot_run`。"
        ),
    },
    "handoff": {
        "command_description": "写出可带走的会话交接 markdown",
        "description": (
            "把当前会话整理为 `.ascendc-pilot/<arch>/session_handoff.md`："
            "只引用已有产物路径，写明下一条 slash。换窗口或交给同事时使用。不占锁。用 `pilot_run`。"
        ),
    },
    "tg-init": {
        "command_description": "测试前置：写出一份绑定测试脚本与 CodeMap 的 init.yaml",
        "description": (
            "测试前置：用 `.uo` + 可选测试脚本写出一份 `tg/init.yaml`。"
            "有脚本仓则绑定脚本输入变量与算子/UO 变量；无仓则用输入 API `kind=default_input`。"
            "算子仓内 tests/ 未确认不得当作 script_repo。无 `.uo` 时先 `uo-init`。用 `pilot_run`。"
        ),
    },
    "tg-plan": {
        "command_description": "白盒测试规划，只落 tg/plan.md",
        "description": (
            "白盒测试规划，只落一份 `tg/plan.md`（散文 + YAML 变量表）。"
            "强制 `init.yaml`；未指定方向则独立变量 = TilingKey 维。"
            "direction 是第一轮提示；evidence 是 Host 运行命中尺。缺列则 test_harness_gap。"
            "向用户说明批准后进入求解的后果。"
        ),
    },
    "tg-solve": {
        "command_description": "定向构造 cases、Host 回放、写 worklog，直到 Open 为空",
        "description": (
            "按已批准 plan 定向构造可执行 cases，Host 动态回放（无 NPU），引理闭合，写 worklog，直到 open 为空。"
            "test_harness_gap 未落地禁止开始。TG 永不改算子仓。向用户报告求解进度。"
        ),
    },
}

# Capability id → repo-relative directory (tools / pilot runtime / gates).
CAPABILITY_DIRS: dict[str, str] = {
    "source-reading": "tools/source/source-reading",
    "source-navigation": "tools/source/source-navigation",
    "readonly-source-search": "tools/source/readonly-source-search",
    "kb-query": "tools/codemap/kb-query",
    "structured-ir-query": "tools/codemap/structured-ir-query",
    "action-scratch": "pilot/runtime/action-scratch",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None or not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _require_skill_frontmatter(text: str, *, path: Path | None = None) -> tuple[dict[str, Any], str]:
    """Parse skill frontmatter. BOMs stripped; leading spaces are NOT stripped.

    Cursor/Composer only recognize frontmatter when the first character is ``---``.
    """
    text = text.lstrip("\ufeff")
    label = path.as_posix() if path else "<skill>"
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        raise ValueError(f"invalid skill frontmatter (must start with ---): {label}")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"invalid skill frontmatter (unclosed fence): {label}")
    meta: dict[str, Any] = {}
    if yaml is not None:
        loaded = yaml.safe_load(parts[1]) or {}
        if isinstance(loaded, dict):
            meta = loaded
    if not meta.get("name"):
        raise ValueError(f"skill frontmatter missing name: {label}")
    if not meta.get("description"):
        raise ValueError(f"skill frontmatter missing description: {label}")
    body = parts[2].lstrip("\n")
    # Body must not re-introduce a YAML frontmatter fence at the start of a line.
    if re.search(r"(?m)^---\s*$", body):
        raise ValueError(f"skill body must not contain frontmatter fence: {label}")
    return meta, body


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Best-effort split for non-skill markdown; skills should use _require_skill_frontmatter."""
    text = text.lstrip("\ufeff")
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, Any] = {}
    if yaml is not None:
        loaded = yaml.safe_load(parts[1]) or {}
        if isinstance(loaded, dict):
            meta = loaded
    return meta, parts[2].lstrip("\n")


def _assert_generated_skill(path: Path, *, expected_actions: int | None = None) -> None:
    text = path.read_text(encoding="utf-8")
    meta, body = _require_skill_frontmatter(text, path=path)
    if expected_actions is not None:
        if "BEGIN GENERATED ACTIONS" not in body or "END GENERATED ACTIONS" not in body:
            raise ValueError(f"generated skill missing Actions table: {path}")
        section = body.split("BEGIN GENERATED ACTIONS", 1)[1].split("END GENERATED ACTIONS", 1)[0]
        found = len(re.findall(r"^\|\s*`([a-z0-9_]+)`\s*\|", section, flags=re.M))
        if found != expected_actions:
            raise ValueError(
                f"generated skill action count mismatch for {path}: "
                f"expected {expected_actions}, found {found}"
            )
    _ = meta  # name/description already validated


def _dump_frontmatter(meta: dict[str, Any]) -> str:
    if yaml is None:
        lines = ["---"]
        for k, v in meta.items():
            lines.append(f"{k}: {v}")
        lines.append("---\n")
        return "\n".join(lines)
    body = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{body}\n---\n"


def _repo_paths(repo: Path) -> dict[str, Path]:
    return {
        "skills": repo / "skills",
        "prompts": repo / "prompts",
        "agents": repo / "agents",
        "policies": repo / "pilot" / "policies",
        "hosts": repo / "adapters" / "hosts",
        "out": repo / "generated",
    }


def _capability_dir(repo: Path, cid: str) -> Path:
    rel = CAPABILITY_DIRS.get(cid)
    if not rel:
        return repo / "tools" / "_unknown" / cid
    return repo / Path(rel)


def _read_policy(repo: Path, pid: str) -> str:
    p = repo / "pilot" / "policies" / pid / "POLICY.md"
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def _start_requirements_line(repo: Path) -> str:
    """Project Spec start modes into model-facing prose."""
    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows import (  # noqa: WPS433
        workflows_needing_architecture,
        workflows_needing_project,
        workflows_needing_uo_product,
    )

    arch = "/".join(sorted(workflows_needing_architecture()))
    uo = "/".join(sorted(workflows_needing_uo_product()))
    proj = "/".join(sorted(workflows_needing_project()))
    return (
        f"6. `{arch}` 启动必须同时有算子目录（`--project`）与 architecture。"
        f"`{uo}` 以已有 `.uo` 为准：无 `.uo` → `UO_PRODUCT_REQUIRED`，禁止 Glob 找产物。"
        f"查询 AskQuestion：先 `uo-init` 或源码作答；TG/CE 先 `uo-init`。"
        f"需要算子目录的 workflow：`{proj}`。`uo-query` 禁止 `pilot_run`（拆路见 pilot-control）。"
    )


def _cognitive_skill_for(repo: Path, wid: str) -> str:
    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows import cognitive_skill_id  # noqa: WPS433

    return cognitive_skill_id(wid)


def _read_invariant_pack(
    repo: Path, *, for_primary: bool = True, agent_id: str = ""
) -> str:
    """Concatenate the unique policy documents into model context.

    POLICY.md is the document. There is no second, shorter copy to drift.
    Workflow-id lists that change with the spec are appended by compose, not
    written into the policy file.
    """
    if for_primary:
        pids: tuple[str, ...] = COMPOSE_POLICY_IDS
        parts: list[str] = [
            "遵守下列策略。不要另搜其它副本。",
            "",
        ]
    elif str(agent_id) in QUERY_CHILD_IDS:
        pids = QUERY_CHILD_POLICY_IDS
        parts = [
            "按 stub 指针读文件。只做本 Action。不要自己 finalize。",
            "",
        ]
    else:
        pids = CHILD_POLICY_IDS
        parts = [
            "按 stub 指针读文件。只做本 Action。不要自己 finalize。",
            "",
        ]
    for pid in pids:
        text = _read_policy(repo, pid).rstrip()
        if text:
            parts.append(text)
            parts.append("")
    if for_primary:
        parts.append(_start_requirements_line(repo))
        parts.append("")
        context = repo / "agents" / "CONTEXT.md"
        if context.is_file():
            parts.append(context.read_text(encoding="utf-8").rstrip())
            parts.append("")
    return "\n".join(parts).rstrip() + "\n"


_CHILD_CONTEXT_DROP_PREFIXES = (
    "**简单查询**",
    "**复杂查询**",
    "**clone 事实**",
)

_QUERY_CHILD_CONTEXT_DROP_PREFIXES = _CHILD_CONTEXT_DROP_PREFIXES + (
    "**`{slug}_plan.md`**",
    "**ce-apply**",
    "**两轴**",
    "**Planning Context**",
    "**Open**",
    "**replay / derived**",
    "**init.yaml**",
    "**plan.md**",
    "**cases 表**",
    "**worklog.md**",
    "**session_handoff.md**",
)


def _child_context_glossary(text: str, *, agent_id: str = "") -> str:
    """Keep ubiquitous language; drop primary routing bullets from child packs."""
    prefixes = (
        _QUERY_CHILD_CONTEXT_DROP_PREFIXES
        if agent_id in QUERY_CHILD_IDS
        else _CHILD_CONTEXT_DROP_PREFIXES
    )
    keep: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if any(stripped.startswith(p) for p in prefixes):
            continue
        keep.append(line)
    return "\n".join(keep).rstrip()


def _read_capability(repo: Path, cid: str) -> tuple[dict[str, Any], str]:
    d = _capability_dir(repo, cid)
    return _load_yaml(d / "capability.yaml"), (d / "METHOD.md").read_text(encoding="utf-8") if (d / "METHOD.md").is_file() else ""


def _scan_forbidden(path: Path, text: str, errors: list[str]) -> None:
    for i, line in enumerate(text.splitlines(), 1):
        low = line.lower()
        if "must not" in low or "禁止" in line or "不得" in line or "勿" in line:
            continue
        for pat in _FORBIDDEN_PATTERNS:
            if pat.search(line):
                errors.append(f"forbidden pattern {pat.pattern!r} in {path.as_posix()}:{i}")


_NUMBERED_STEP = re.compile(r"(?m)^\s*\d+\.\s+\S")


def _prompt_repeats_method_procedure(method: str, prompt: str) -> bool:
    """LLM Action prompts must not restate METHOD numbered procedures."""
    method_steps = {line.strip() for line in method.splitlines() if _NUMBERED_STEP.match(line)}
    if len(method_steps) < 2:
        return False
    prompt_steps = {line.strip() for line in prompt.splitlines() if _NUMBERED_STEP.match(line)}
    return len(method_steps & prompt_steps) >= 2


_DOMAIN_HARNESS_PATTERNS = [
    re.compile(r"\brun_id\b", re.I),
    re.compile(r"\baction_id\b", re.I),
    re.compile(r"\bfinalize\b", re.I),
    re.compile(r"\badvance\b", re.I),
    re.compile(r"\bacp\s+start\b", re.I),
    re.compile(r"\bacp\s+next\b", re.I),
]


def validate_domain_skills(repo: Path) -> list[str]:
    """Lint model-facing cognitive skills: frontmatter, line budget, no harness leakage."""
    errors: list[str] = []
    skills_root = repo / "skills"
    errors.extend(_lint_skill_bundle(skills_root, listed_skill_ids(repo), kind="cognitive"))
    errors.extend(_lint_skill_bundle(skills_root, CONTROL_PLANE_SKILL_IDS, kind="control-plane"))
    return errors


def _lint_skill_bundle(skills_root: Path, skill_ids: tuple[str, ...], *, kind: str) -> list[str]:
    errors: list[str] = []
    for skill_id in skill_ids:
        skill_md = skills_root / skill_id / "SKILL.md"
        if not skill_md.is_file():
            errors.append(f"missing {kind} skill: skills/{skill_id}/SKILL.md")
            continue
        text = skill_md.read_text(encoding="utf-8")
        try:
            meta, body = _require_skill_frontmatter(text, path=skill_md)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not str(meta.get("name") or "").strip():
            errors.append(f"{skill_md.as_posix()}: missing frontmatter name")
        if not str(meta.get("description") or "").strip():
            errors.append(f"{skill_md.as_posix()}: missing frontmatter description")
        n_lines = len(text.splitlines())
        if n_lines < 80 and skill_id not in ROUTER_SKILLS:
            errors.append(
                f"DOMAIN_SKILL_TOO_SHORT {skill_md.as_posix()}: {n_lines} lines < 80"
            )
        if n_lines > 200:
            errors.append(
                f"DOMAIN_SKILL_TOO_LONG {skill_md.as_posix()}: {n_lines} lines > 200"
            )
        gotchas = skills_root / skill_id / "references" / "gotchas.md"
        del gotchas
        for i, line in enumerate(body.splitlines(), 1):
            for pat in _DOMAIN_HARNESS_PATTERNS:
                if pat.search(line):
                    errors.append(
                        f"DOMAIN_HARNESS_LEAK {skill_md.as_posix()}:{i}: "
                        f"pattern {pat.pattern!r} belongs in Harness, not Skill"
                    )
    return errors


def _entry_skill_shell(wid: str, *, skill_id: str = "", host: str = "") -> str:
    """Thin slash entry body (orchestration pointer only)."""
    lines = [
        f"# {wid}",
        "",
        "Pilot 工作流入口。编排由 Primary Todo 拥有。阶段与 lease 由 Spec 拥有。",
        "",
    ]
    if skill_id:
        if host == "opencode":
            lines.append(f"领域方法：`cognitive-skills/{skill_id}/SKILL.md`。")
        else:
            lines.append(f"领域方法：`skills/{skill_id}/SKILL.md`。")
        lines.append("")
    if wid == "uo-query":
        run_via = (
            "Command，不是 Host 工作流。禁止 `pilot_run`。"
            "拆路与冲突核对见主控策略（pilot-control），不要读 Skill 路由手册。"
        )
    else:
        run_via = (
            "用 Host 工具 `pilot_run` 运行（workflow + project + architecture）。"
        )
    lines.extend(
        [
            run_via,
            "",
            "## Actions",
            "",
            "<!-- BEGIN GENERATED ACTIONS -->",
            "",
            "<!-- END GENERATED ACTIONS -->",
            "",
        ]
    )
    return "\n".join(lines)



def _glob_prefix(pattern: str) -> str:
    """Return the literal directory prefix before the first glob metachar."""
    norm = pattern.replace("\\", "/").strip("/")
    parts: list[str] = []
    for part in norm.split("/"):
        if any(ch in part for ch in "*?["):
            break
        parts.append(part)
    return "/".join(parts)


def _scopes_conflict(a: str, b: str) -> bool:
    """True if two write_scopes may overlap (exact, equal, or prefix containment)."""
    if a == b:
        return True
    pa, pb = _glob_prefix(a), _glob_prefix(b)
    if not pa or not pb:
        # Broad globs like ``**`` or ``*`` — treat as conflicting unless both are runs scratch.
        return not (a.startswith("runs") and b.startswith("runs"))
    if pa == pb:
        return True
    return pa.startswith(pb + "/") or pb.startswith(pa + "/")


def _scope_overlap_errors(producer_writes: set[str], referee_writes: set[str]) -> list[str]:
    errors: list[str] = []
    for p in sorted(producer_writes):
        if str(p).removeprefix("pilot:").startswith("runs"):
            continue
        for r in sorted(referee_writes):
            if str(r).removeprefix("pilot:").startswith("runs"):
                continue
            if _scopes_conflict(str(p), str(r)):
                errors.append(f"producer/referee write_scopes overlap: {p!r} vs {r!r}")
    return errors


def sync_action_yaml_mirrors(repo: Path) -> list[str]:
    """No-op: Action identity lives only in Workflow Spec (no skills/actions source tree)."""
    del repo
    return []


def sync_skill_action_markers(repo: Path) -> list[str]:
    """No-op: workflow entry Skills are generated from Spec + WORKFLOW_ENTRIES."""
    del repo
    return []


def check_skill_action_markers(repo: Path) -> list[str]:
    """Verify every slash workflow has an entry description and Spec actions."""
    errors: list[str] = []
    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows import WORKFLOWS  # noqa: WPS433

    for wid, meta in WORKFLOWS.items():
        if meta.get("reserved") or not meta.get("slash"):
            continue
        entry = WORKFLOW_ENTRIES.get(wid)
        if not entry or not str(entry.get("description") or "").strip():
            errors.append(f"SKILL_ENTRY_MISSING {wid}: add WORKFLOW_ENTRIES description")
            continue
        if "skill_id" in entry or "cognitive_skill_id" in entry:
            errors.append(
                f"SKILL_ENTRY_LEGACY_SKILL_ID {wid}: Skill is per Action, not a workflow family"
            )
        expected = {str(a.get("id")) for a in (meta.get("actions") or []) if isinstance(a, dict)}
        if not expected:
            errors.append(f"SKILL_ACTION_SET_DRIFT {wid}: Spec has no actions")
    return errors


def sync_sources(repo: Path) -> list[str]:
    """Write path: Spec is authority."""
    errors: list[str] = []
    errors.extend(sync_action_yaml_mirrors(repo))
    errors.extend(sync_skill_action_markers(repo))
    return errors


def validate(repo: Path) -> list[str]:
    """Static validation (read-only); returns list of error strings. Does not write files."""
    paths = _repo_paths(repo)
    skills = paths["skills"]
    prompts = paths["prompts"]
    agents = paths["agents"]

    errors: list[str] = []
    errors.extend(check_skill_action_markers(repo))
    errors.extend(validate_domain_skills(repo))
    for rel in (
        "knowledge/ascendc/precision.md",
        "knowledge/ascendc/performance.md",
        "knowledge/ascendc/cross-layer-contracts.md",
        "knowledge/ascendc/synchronization.md",
        "skills/test-plan/references/evidence.md",
        "skills/certify/references/precision-neighborhood.md",
        "skills/certify/references/performance-neighborhood.md",
        "skills/source-proof/references/proof-certificate.md",
        "skills/proof-review/SKILL.md",
    ):
        if not (repo / rel).is_file():
            errors.append(f"AUTHORITY_FILE_MISSING {rel}")

    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows import WORKFLOWS  # noqa: WPS433

    # Collect write scopes by role for overlap / containment check
    producer_writes: set[str] = set()
    referee_writes: set[str] = set()
    for ag_path in agents.glob("*.yaml"):
        meta = _load_yaml(ag_path)
        role = str(meta.get("role") or "")
        scopes = {str(x) for x in (meta.get("write_scopes") or [])}
        aid = str(meta.get("id") or ag_path.stem)
        mode = str(meta.get("mode") or "").strip().lower()
        if mode and mode not in {"primary", "subagent", "all"}:
            errors.append(f"agent {aid}: invalid mode {mode!r} (expected primary|subagent)")
        if meta.get("type") is not None:
            errors.append(
                f"agent {aid}: OpenCode uses mode not type; remove type={meta.get('type')!r}"
            )
        kind = str(meta.get("kind") or "").strip().lower()
        if kind and kind not in {"deterministic_engine"}:
            errors.append(
                f"agent {aid}: invalid kind {kind!r} "
                f"(expected empty or deterministic_engine)"
            )
        if role in {"producer", "referee", "readonly_analyst", "deterministic_engine"} and not mode:
            # Defaulted to subagent at compose time; warn as error to keep sources explicit.
            if aid != "ascendc-pilot":
                errors.append(f"agent {aid}: missing mode (use mode: subagent)")
        if kind == "deterministic_engine" and role != "deterministic_engine":
            errors.append(
                f"agent {aid}: kind=deterministic_engine requires role=deterministic_engine"
            )
        if role == "producer":
            producer_writes |= scopes
        elif role == "referee":
            referee_writes |= scopes
    bad = _scope_overlap_errors(producer_writes, referee_writes)
    errors.extend(bad)

    # Note: generated/ OpenCode frontmatter is validated after compose (see validate_generated).
    # Pre-compose validate only checks sources so install can regenerate stale trees.

    for wid, meta in WORKFLOWS.items():
        if meta.get("reserved") or meta.get("alias_of") or not meta.get("slash"):
            continue
        entry = WORKFLOW_ENTRIES.get(wid)
        if not entry or not str(entry.get("description") or "").strip():
            errors.append(f"missing WORKFLOW_ENTRIES for {wid}")
        for action in meta.get("actions") or []:
            if not isinstance(action, dict):
                continue
            aid = action.get("id")
            for pid in action.get("policy_ids") or []:
                if not (repo / "pilot" / "policies" / pid / "POLICY.md").is_file():
                    errors.append(f"{wid}/{aid}: missing policy {pid}")
            for cid in action.get("capability_ids") or []:
                if not (_capability_dir(repo, str(cid)) / "capability.yaml").is_file():
                    errors.append(f"{wid}/{aid}: missing capability {cid}")
            mid = str(action.get("skill_id") or action.get("action_method_id") or "").strip()
            tpid = action.get("task_prompt_id")
            mode = str(action.get("execution_mode") or "")
            if mode == "subagent" and tpid:
                if "/" in mid:
                    mid = mid.rsplit("/", 1)[-1]
                mp = skills / mid / "SKILL.md"
                if not mid or not mp.is_file() or not mp.read_text(encoding="utf-8").strip():
                    errors.append(f"{wid}/{aid}: missing SKILL.md for {mid!r}")
            elif mode in {"deterministic", "primary_interactive"} and mid:
                errors.append(f"{wid}/{aid}: {mode} Action must omit skill_id")
            if tpid:
                p = prompts / "tasks" / f"{tpid}.md"
                # tpid is domain/name
                if "/" in str(tpid):
                    dom, name = str(tpid).split("/", 1)
                    p = prompts / "tasks" / dom / f"{name}.md"
                if not p.is_file():
                    errors.append(f"{wid}/{aid}: missing task prompt {tpid}")
                else:
                    prompt_text = p.read_text(encoding="utf-8")
                    _scan_forbidden(p, prompt_text, errors)
                    sid = str(action.get("skill_id") or action.get("action_method_id") or "").strip()
                    if "/" in sid:
                        sid = sid.rsplit("/", 1)[-1]
                    if sid == "ce-plan-draft" and mode == "subagent":
                        mp = skills / sid / "SKILL.md"
                        if mp.is_file():
                            method_text = mp.read_text(encoding="utf-8")
                            if _prompt_repeats_method_procedure(method_text, prompt_text):
                                errors.append(
                                    f"{wid}/{aid}: task prompt repeats SKILL numbered procedure"
                                )
            # Semantic / interactive actions need role + context + output contract
            if action.get("role_id") in {
                "producer",
                "referee",
                "readonly_analyst",
                "controller",
            } or action.get("execution_mode") in {"subagent", "primary_interactive"}:
                if not action.get("output_contract_id"):
                    errors.append(f"{wid}/{aid}: missing output_contract_id")
            agent_id = action.get("agent_id")
            if agent_id and agent_id != "ascendc-pilot":
                if not (agents / f"{agent_id}.yaml").is_file():
                    errors.append(f"{wid}/{aid}: missing agent {agent_id}")
            # Primary must not be declared as subagent execution.
            if action.get("execution_mode") == "subagent" and agent_id == "ascendc-pilot":
                errors.append(f"{wid}/{aid}: primary agent cannot use subagent execution_mode")

    return errors


def _action_yaml_drift(wid: str, action: dict[str, Any], ayaml: dict[str, Any]) -> list[str]:
    """Fail when source action.yaml diverges from Workflow Spec identity fields."""
    errors: list[str] = []
    aid = str(action.get("id") or "")
    comparisons = {
        "id": action.get("id"),
        "workflow_id": wid,
        "agent_id": action.get("agent_id"),
        "role_id": action.get("role_id"),
        "execution_mode": action.get("execution_mode"),
        "task_prompt_id": action.get("task_prompt_id"),
        "output_contract_id": action.get("output_contract_id"),
    }
    # capabilities / policies lists
    if action.get("capability_ids") is not None:
        comparisons["capabilities"] = list(action.get("capability_ids") or [])
    if action.get("policy_ids") is not None:
        comparisons["policies"] = list(action.get("policy_ids") or [])
    for field, spec_value in comparisons.items():
        yaml_value = ayaml.get(field)
        if field in {"capabilities", "policies"}:
            yaml_value = list(yaml_value or [])
            spec_value = list(spec_value or [])
        if yaml_value in (None, "") and spec_value in (None, "", []):
            continue
        if yaml_value != spec_value:
            errors.append(
                "ACTION_METADATA_DRIFT "
                f"{wid}/{aid} field={field} "
                f"spec_value={spec_value!r} action_yaml_value={yaml_value!r}"
            )
    checker_req = bool(action.get("checker_required", True))
    yaml_checker = bool(((ayaml.get("checker") or {}) if isinstance(ayaml.get("checker"), dict) else {}).get("required", True))
    if yaml_checker != checker_req:
        errors.append(
            "ACTION_METADATA_DRIFT "
            f"{wid}/{aid} field=checker.required "
            f"spec_value={checker_req!r} action_yaml_value={yaml_checker!r}"
        )
    referee_req = bool(action.get("referee_required", False))
    yaml_ref = bool(((ayaml.get("referee") or {}) if isinstance(ayaml.get("referee"), dict) else {}).get("required", False))
    if yaml_ref != referee_req:
        errors.append(
            "ACTION_METADATA_DRIFT "
            f"{wid}/{aid} field=referee.required "
            f"spec_value={referee_req!r} action_yaml_value={yaml_ref!r}"
        )
    return errors


def _spec_action_yaml(wid: str, action: dict[str, Any], extras: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generate action.yaml body from Workflow Spec (mirror, not authority)."""
    merged = dict(extras or {})
    merged.update(
        {
            "id": action.get("id"),
            "workflow_id": wid,
            "role_id": action.get("role_id"),
            "agent_id": action.get("agent_id"),
            "execution_mode": action.get("execution_mode"),
            "capabilities": list(action.get("capability_ids") or []),
            "policies": list(action.get("policy_ids") or []),
            "task_prompt_id": action.get("task_prompt_id"),
            "output_contract_id": action.get("output_contract_id"),
            "allowed_write_paths": list(action.get("allowed_write_paths") or []),
            "forbidden_write_paths": list(action.get("forbidden_write_paths") or []),
            "allowed_read_paths": list(action.get("allowed_read_paths") or []),
            "forbidden_read_paths": list(action.get("forbidden_read_paths") or []),
            "checker": {"required": bool(action.get("checker_required", True))},
            "referee": {"required": bool(action.get("referee_required", False))},
            "generated_from": "workflow_spec",
        }
    )
    return merged


def _replace_actions_table(body: str, meta: dict[str, Any]) -> str:
    """Replace generated Actions markers with Workflow Spec authority."""
    rows = [
        "| action_id | execution_mode | agent | role | method | prompt | output_contract |",
        "|---|---|---|---|---|---|---|",
    ]
    for a in meta.get("actions") or []:
        if not isinstance(a, dict):
            continue
        rows.append(
            "| `{id}` | `{mode}` | `{agent}` | `{role}` | `{method}` | `{prompt}` | `{contract}` |".format(
                id=a.get("id"),
                mode=a.get("execution_mode") or "-",
                agent=(
                    a.get("agent_id")
                    or (
                        "engine"
                        if str(a.get("role_id") or "") == "deterministic_engine"
                        or str(a.get("execution_mode") or "") == "deterministic"
                        else "human"
                    )
                ),
                role=a.get("role_id") or "-",
                method=a.get("action_method_id") or "-",
                prompt=a.get("task_prompt_id") or "-",
                contract=a.get("output_contract_id") or "-",
            )
        )
    table = "\n".join(rows) + "\n"
    begin = "<!-- BEGIN GENERATED ACTIONS -->"
    end = "<!-- END GENERATED ACTIONS -->"
    if begin in body and end in body:
        pre, rest = body.split(begin, 1)
        _, post = rest.split(end, 1)
        return pre + begin + "\n\n" + table + "\n" + end + post
    # Fallback: replace ## Actions section, wrapping with markers.
    wrapped = f"## Actions\n\n{begin}\n\n{table}\n{end}\n"
    if re.search(r"(?m)^## Actions\s*$", body):
        return re.sub(
            r"(?ms)^## Actions\s*\n.*?(?=^## |\Z)",
            wrapped + "\n",
            body,
            count=1,
        )
    return body.rstrip() + "\n\n" + wrapped


def _compose_skill_body(repo: Path, wid: str, meta: dict[str, Any], *, host: str = "") -> str:
    del repo
    body = _entry_skill_shell(wid, skill_id="", host=host)
    body = _replace_actions_table(body, meta)
    return body.rstrip() + "\n"


# OpenCode agent frontmatter: use ``mode``, never legacy ``type: subagent``.
_OPENCODE_AGENT_ALLOWED_KEYS = frozenset(
    {
        "name",
        "description",
        "mode",
        "permission",
        "tools",
        "model",
        "temperature",
        "color",
        "hidden",
    }
)


_REPO_SEARCH_BASH_ALLOWS: dict[str, str] = {
    "grep *": "allow",
    "Grep *": "allow",
    "rg *": "allow",
    "ripgrep *": "allow",
    "findstr *": "allow",
    "Select-String *": "allow",
    "sls *": "allow",
    "tree": "allow",
    "tree *": "allow",
}

_SEARCH_CAPABILITIES = frozenset({"source-navigation", "readonly-source-search"})


def _opencode_bash_permission(
    *,
    allow_repo_search: bool = True,
    primary: bool = False,
) -> dict[str, str]:
    """OpenCode frontmatter bash rules (last match wins: default ask, then allows).

    Safe probes auto-allow. Anything else (including clone / deletes) is OpenCode
    ``ask`` so the user can confirm instead of a hard deny. Do **not** allowlist
    the harness binary. Workflows use Host ``pilot_run``; short CLI uses plugin
    ``pilot_cli``. Locate-only grep/rg is allowed; semantic lookup still prefers
    ``pilot_cli`` ``uo-query``.
    """
    perm = {
        "*": "ask",
        # Path / listing probes
        "ls": "allow",
        "ls *": "allow",
        "dir": "allow",
        "dir *": "allow",
        "pwd": "allow",
        "Get-ChildItem": "allow",
        "Get-ChildItem *": "allow",
        "gci": "allow",
        "gci *": "allow",
        "Get-Item": "allow",
        "Get-Item *": "allow",
        "gi": "allow",
        "gi *": "allow",
        "Get-Location": "allow",
        "Get-Location *": "allow",
        "gl": "allow",
        "Test-Path": "allow",
        "Test-Path *": "allow",
        "Resolve-Path": "allow",
        "Resolve-Path *": "allow",
        "cd *": "allow",
        "Set-Location *": "allow",
        "sl *": "allow",
        "Push-Location *": "allow",
        "Pop-Location": "allow",
        "Pop-Location *": "allow",
        # OpenCode matches each pipeline stage. Authorize already allows these
        # as readonly pipe tails; without them `findstr | Select-Object` is
        # denied by frontmatter before Pilot authorize runs.
        "Select-Object *": "allow",
        "select *": "allow",
        "Format-Table *": "allow",
        "ft *": "allow",
        "Format-List *": "allow",
        "fl *": "allow",
        "Where-Object *": "allow",
        "Sort-Object *": "allow",
        "Measure-Object *": "allow",
        "Group-Object *": "allow",
        "ForEach-Object *": "allow",
        "git status": "allow",
        "git status *": "allow",
        "git log": "allow",
        "git log *": "allow",
        "git rev-parse": "allow",
        "git rev-parse *": "allow",
        "git diff --name-only": "allow",
        "git diff --name-only *": "allow",
        "git diff --stat": "allow",
        "git diff --stat *": "allow",
    }
    if primary:
        perm.update(
            {
                "python *check_cann.py*": "allow",
                "python3 *check_cann.py*": "allow",
                "python *check_env.py*": "allow",
                "python3 *check_env.py*": "allow",
                "python *check_install.py*": "allow",
                "python3 *check_install.py*": "allow",
                "python *cann_extract.py* --fixup*": "allow",
                "python3 *cann_extract.py* --fixup*": "allow",
                "python -m ascendc_pilot doctor": "allow",
                "python -m ascendc_pilot doctor *": "allow",
                "python3 -m ascendc_pilot doctor": "allow",
                "python3 -m ascendc_pilot doctor *": "allow",
                "python -c *": "allow",
                "python3 -c *": "allow",
                "git": "allow",
                "git *": "allow",
                # Override ``git *`` allow: clone/worktree identity stays a user confirm.
                "git clone": "ask",
                "git clone *": "ask",
                "git worktree add": "ask",
                "git worktree add *": "ask",
            }
        )
    if allow_repo_search or primary:
        perm.update(_REPO_SEARCH_BASH_ALLOWS)
    return perm


def _agent_capability_union(repo: Path, agent_id: str) -> set[str]:
    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows import WORKFLOWS  # noqa: WPS433

    caps: set[str] = set()
    for meta in WORKFLOWS.values():
        if not isinstance(meta, dict):
            continue
        for action in meta.get("actions") or []:
            if not isinstance(action, dict):
                continue
            if str(action.get("agent_id") or "") == agent_id:
                caps.update(str(c) for c in (action.get("capability_ids") or []) if c)
    return caps


def _agent_allow_repo_search(repo: Path, agent_meta: dict[str, Any]) -> bool:
    """Locate-only Grep/Glob/bash search is allowed for every agent."""
    del repo, agent_meta
    return True


def _host_remap_skill_paths(text: str, *, host: str) -> str:
    """Rewrite ``skills/<cognitive>`` → ``cognitive-skills/<cognitive>`` for OpenCode."""
    if host != "opencode" or not text:
        return text
    out = text
    for cid in listed_skill_ids():
        token = f"\x00CS:{cid}\x00"
        # Protect already-remapped paths so ``skills/{cid}`` cannot match inside
        # ``cognitive-skills/{cid}``.
        out = out.replace(f"cognitive-skills/{cid}", token)
        out = out.replace(f"skills/{cid}", token)
        out = out.replace(token, f"cognitive-skills/{cid}")
    return out


def _project_primary_description(repo: Path, description: str, *, host: str = "") -> str:
    """Remap skill paths in agent description for the target host."""
    del repo
    return _host_remap_skill_paths(str(description or ""), host=host)


def _compose_agent_md(repo: Path, agent_meta: dict[str, Any], *, host: str = "") -> str:
    aid = agent_meta.get("id", "agent")
    read_scopes = list(agent_meta.get("read_scopes") or [])
    if host == "opencode":
        # Cognitive skills are not in OpenCode Skill discovery; agents load
        # them from the plugin-internal cognitive-skills/ tree.
        remapped: list[str] = []
        for scope in read_scopes:
            s = str(scope)
            # Namespaced: method:skills/<id> → method:cognitive-skills/<id>
            if s.startswith("method:skills/") and any(
                s.startswith(f"method:skills/{cid}") for cid in listed_skill_ids(repo)
            ):
                remapped.append("method:cognitive-" + s[len("method:") :])
            elif s.startswith("skills/") and any(
                s.startswith(f"skills/{cid}") for cid in listed_skill_ids(repo)
            ):
                remapped.append("cognitive-" + s)
            else:
                remapped.append(s)
        read_scopes = remapped
    reads = (
        "- 算子语义先 `uo-query`。读源码只打开查询结果，或当前 Action "
        "`environment_capabilities.yaml` 的 `source_scope.file_paths`，"
        "以及 packet / FOCUS 给出的 `file:line` 窗。\n"
        "- 不要把权限命名空间当成文件系统路径去 Read。"
    )
    write_scope_list = [str(x) for x in (agent_meta.get("write_scopes") or [])]
    writes = (
        "- 只写当前 Action 允许的产物（见 session `bundle.yaml` / `output_contract`）。"
        "写权限以 lease 为准。"
    )
    is_primary = agent_meta.get("mode") == "primary"
    if (
        not is_primary
        and len(write_scope_list) > 4
        and all("runs" in s.replace("\\", "/") for s in write_scope_list)
    ):
        writes = "- 只写当前 Action session 下的草稿。"
    inv_pack = _host_remap_skill_paths(
        _read_invariant_pack(repo, for_primary=is_primary, agent_id=str(aid)),
        host=host,
    )
    desc = _project_primary_description(
        repo, str(agent_meta.get("description") or aid), host=host
    )
    display_name = aid
    if host == "opencode":
        display_name = str(agent_meta.get("name_zh") or aid).strip() or aid
    front: dict[str, Any] = {
        "name": display_name,
        "description": desc,
    }
    allow_repo_search = _agent_allow_repo_search(repo, agent_meta)
    bash_perm = _opencode_bash_permission(
        allow_repo_search=allow_repo_search, primary=is_primary
    )
    grep_perm = "allow" if allow_repo_search else "ask"
    write_scopes = list(agent_meta.get("write_scopes") or [])
    # OpenCode defaults most tools to allow. Always emit edit/write explicitly.
    # edit covers write/apply_patch. Empty write_scopes → ask (lease still fences).
    if write_scopes:
        edit_perm: Any = {"*": "ask"}
        write_perm: Any = {"*": "ask"}
    else:
        edit_perm = "ask"
        write_perm = "ask"
    host_read_perm = {
        # Host transport workaround: OpenCode child worktree vs operator root.
        # Real write boundary is Pilot lease, not this frontmatter.
        "read": "allow",
        "external_directory": "allow",
    }
    if is_primary:
        front["mode"] = "primary"
        if host == "opencode":
            # Isolated from OpenCode Build/Plan defaults (those tabs keep stock rules).
            front["permission"] = opencode_isolated_primary_permission(
                bash_perm=bash_perm,
                edit_perm=edit_perm if write_scopes else {"*": "ask"},
                write_perm=write_perm if write_scopes else {"*": "ask"},
            )
            front["tools"] = {
                "pilot_run": True,
                "pilot_cli": True,
            }
        else:
            front["permission"] = {
                "bash": bash_perm,
                "grep": grep_perm,
                **host_read_perm,
                "task": opencode_primary_task_permission(),
                "pilot_cli": "allow",
                "pilot_run": "allow",
                "edit": edit_perm if write_scopes else {"*": "ask"},
                "write": write_perm if write_scopes else {"*": "ask"},
            }
    else:
        # Unknown natives / MCP default to OpenCode ask (user confirms).
        front["mode"] = "subagent"
        if host == "opencode":
            front["hidden"] = True
        child_bash: Any = bash_perm
        front["permission"] = {
            "*": "ask",
            "bash": child_bash,
            "pilot_cli": "allow",
            "pilot_run": "ask",
            "grep": grep_perm,
            "glob": "allow" if allow_repo_search else "ask",
            **host_read_perm,
            "edit": edit_perm,
            "write": write_perm,
            "task": "ask",
            "skill": "ask",
            "webfetch": "ask",
            "websearch": "ask",
            "lsp": "ask",
            "todowrite": "ask",
        }
        tools: dict[str, Any] = {
            "skill": False,
            "pilot_run": False,
            "pilot_cli": True,
        }
        front["tools"] = tools

    if aid == "uo-query":
        runtime = """## 运行时契约

execution_variant = delegated_query。

先读 stub 指出的 `prompt` / `method`。怎么查见 session `method.md`。
首次：`pilot_cli` `uo-query --project <算子绝对路径>`（无其它参数），除非 stub 已给出标识符 / `Dim=V` / `--file --line`。不要 Write `answer.yaml`。不要自己 finalize。
"""
    elif is_primary:
        runtime = """## 运行时契约

工作流用 `pilot_run`。查询用 `pilot_cli` `uo-query`（拆路见 pilot-control）。禁止 `--help`。Host 给出 Task 正文时原样派发；`plan_precheck` 后按 `pilot-control` 用原生 Task 派 Plan Owner。缺 `pilot_run` 时请用户重装插件。
"""
    else:
        runtime = """## 运行时契约

先读 stub 指出的 `prompt` / `method` / `bundle`。以 `prompt.md` 为本任务正文。只做本 Action。不要自己 finalize。查图用 `pilot_cli` `uo-query`（形态见当前查询步 method）。
"""
    body = f"""# Agent: {aid}

## 任务

{desc}

## 边界

可读：

{reads}

机器范围的**算子源码**（`op_host/**`、`op_kernel/**` 等）在 `.ascendc-pilot` 之外。
禁止整文件倒进上下文。

可写：

{writes}

写权限以 lease 与上面的可写范围为准。禁止宣布 workflow passed。

{runtime}
## Composed: policy-invariants

{inv_pack}
"""
    return _dump_frontmatter(front) + "\n" + body


def _rmtree(path: Path) -> None:
    """Remove a tree. Windows often raises WinError 145 if a file is briefly locked."""
    if not path.exists():
        return

    def _onerror(func: Any, p: str, _exc: Any) -> None:
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    last: OSError | None = None
    for attempt in range(5):
        try:
            shutil.rmtree(path, onerror=_onerror)
            return
        except OSError as exc:
            last = exc
            time.sleep(0.05 * (attempt + 1))
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        raise last or OSError(f"could not remove {path}")


def compose_host(repo: Path, host: str, *, out_root: Path | None = None) -> dict[str, Any]:
    paths = _repo_paths(repo)
    skills = paths["skills"]
    prompts_src = paths["prompts"]
    agents_src = paths["agents"]
    # Compose into out_root (default generated/<host>). Temp out_roots stay
    # isolated; Spec is the sole Action identity authority (no skills/actions/).
    if out_root is None:
        out_root = paths["out"] / host
    else:
        out_root = Path(out_root)
    host_meta = _load_yaml(paths["hosts"] / f"{host}.yaml")

    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows import WORKFLOWS, workflow_is_command  # noqa: WPS433

    if out_root.exists():
        _rmtree(out_root)
    out_skills = out_root / "skills"
    out_agents = out_root / "agents"
    out_prompts = out_root / "prompts"
    out_skills.mkdir(parents=True)
    out_agents.mkdir(parents=True)
    out_prompts.mkdir(parents=True)

    compiled: list[str] = []

    # Slash workflow shells. Instant Commands (uo-query) are not Skills:
    # they enter Primary investigation via compose_opencode_commands.
    workflow_ids = [
        wid
        for wid, m in WORKFLOWS.items()
        if m.get("slash")
        and not m.get("reserved")
        and not m.get("alias_of")
        and not workflow_is_command(wid)
    ]
    for wid in workflow_ids:
        entry = WORKFLOW_ENTRIES.get(wid) or {}
        desc = str(entry.get("description") or "").strip() or wid
        meta: dict[str, Any] = {"name": wid, "description": desc}
        overrides = dict(host_meta.get("skill_defaults") or {})
        per_skill = (host_meta.get("skills") or {}).get(wid) or {}
        if isinstance(per_skill, dict):
            overrides.update(per_skill)
        meta = {**meta, **overrides}
        # OpenCode Skill frontmatter does not honor Cursor-only keys.
        if host == "opencode":
            meta.pop("disable-model-invocation", None)
            meta.pop("disable_model_invocation", None)
        wf_meta = WORKFLOWS.get(wid) or {}
        body = _compose_skill_body(repo, wid, wf_meta, host=host)
        dest = out_skills / wid
        dest.mkdir(parents=True, exist_ok=True)
        skill_out = dest / "SKILL.md"
        # Ensure composed frontmatter keeps name/description; do not indent.
        out_text = _dump_frontmatter(meta) + "\n" + body.lstrip("\n")
        if not out_text.startswith("---\n"):
            raise ValueError(f"composed skill must start with ---: {skill_out}")
        skill_out.write_text(out_text, encoding="utf-8")
        expected_n = len(wf_meta.get("actions") or [])
        _assert_generated_skill(skill_out, expected_actions=expected_n)
        # Emit Spec-derived Action Bundle sidecars (identity only).
        for a in wf_meta.get("actions") or []:
            aid_folder = str(a.get("id") or "").replace("_", "-")
            if not aid_folder:
                continue
            adir = dest / "actions" / aid_folder
            adir.mkdir(parents=True, exist_ok=True)
            merged = _spec_action_yaml(wid, a)
            if yaml is not None:
                (adir / "action.yaml").write_text(
                    "# GENERATED from Workflow Spec — do not hand-edit identity fields\n"
                    + yaml.safe_dump(merged, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
        # Copy capabilities used
        caps_needed: set[str] = set()
        for a in wf_meta.get("actions") or []:
            caps_needed.update(a.get("capability_ids") or [])
        for cid in sorted(caps_needed):
            csrc = _capability_dir(repo, str(cid))
            if csrc.is_dir():
                cdst = dest / "capabilities" / cid
                if cdst.exists():
                    _rmtree(cdst)
                shutil.copytree(csrc, cdst)
        compiled.append(f"{host}/skills/{wid}")

    # Cognitive skills: Cursor/Codex get disable-model-invocation;
    # OpenCode does not put them in Skill discovery — only workflow entries.
    cognitive_out = (
        out_root / "cognitive-skills" if host == "opencode" else out_skills
    )
    if host == "opencode":
        if cognitive_out.exists():
            _rmtree(cognitive_out)
        cognitive_out.mkdir(parents=True, exist_ok=True)
    for skill_id in listed_skill_ids(repo):
        src = skills / skill_id
        if not (src / "SKILL.md").is_file():
            continue
        dst = cognitive_out / skill_id
        if dst.exists():
            _rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("README.md"))
        skill_md = dst / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        meta, body = _require_skill_frontmatter(text, path=skill_md)
        if host != "opencode":
            meta["disable-model-invocation"] = True
        else:
            meta.pop("disable-model-invocation", None)
        per = (host_meta.get("skills") or {}).get(skill_id) or {}
        if isinstance(per, dict):
            meta.update(per)
        skill_md.write_text(_dump_frontmatter(meta) + "\n" + body.lstrip("\n"), encoding="utf-8")
        compiled.append(
            f"{host}/cognitive-skills/{skill_id}"
            if host == "opencode"
            else f"{host}/skills/{skill_id}"
        )
    for skill_id in CONTROL_PLANE_SKILL_IDS:
        src = skills / skill_id
        if not (src / "SKILL.md").is_file():
            continue
        dst = out_skills / skill_id
        if dst.exists():
            _rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("README.md"))
        skill_md = dst / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        meta, body = _require_skill_frontmatter(text, path=skill_md)
        meta.pop("disable-model-invocation", None)
        skill_md.write_text(_dump_frontmatter(meta) + "\n" + body.lstrip("\n"), encoding="utf-8")
        compiled.append(f"{host}/skills/{skill_id}")
    shared_src = skills / "_shared"
    if shared_src.is_dir() and any(shared_src.glob("*.md")):
        # Legacy leftover: cognitive skills must be self-contained under references/.
        # Do not copy _shared into generated hosts.
        pass
    knowledge_src = repo / "knowledge"
    knowledge_dst = out_root / "knowledge"
    required_knowledge = (
        "ascendc/precision.md",
        "ascendc/performance.md",
        "ascendc/cross-layer-contracts.md",
        "ascendc/synchronization.md",
    )
    missing_knowledge = [rel for rel in required_knowledge if not (knowledge_src / rel).is_file()]
    if missing_knowledge:
        return {
            "ok": False,
            "error": "KNOWLEDGE_MISSING",
            "missing": missing_knowledge,
            "compiled": compiled,
            "out_root": out_root.as_posix(),
        }
    if knowledge_dst.exists():
        _rmtree(knowledge_dst)
    shutil.copytree(knowledge_src, knowledge_dst)
    compiled.append(f"{host}/knowledge")

    # Shared policies + short invariants under each host
    pol_dst = out_skills / "_policies"
    pol_dst.mkdir(parents=True, exist_ok=True)
    policies_src = paths["policies"]
    if policies_src.is_dir():
        for pdir in policies_src.iterdir():
            if pdir.is_dir():
                d = pol_dst / pdir.name
                if d.exists():
                    _rmtree(d)
                shutil.copytree(pdir, d)

    # Agents — skip kind=deterministic_engine (authorize identity only; not LLM-spawned).
    for ag in sorted(agents_src.glob("*.yaml")):
        meta = _load_yaml(ag)
        if not meta.get("id"):
            continue
        kind = str(meta.get("kind") or "").strip().lower()
        if kind == "deterministic_engine":
            continue
        if str(meta.get("id") or "") in OPENCODE_SKIP_HOST_AGENT_IDS:
            continue
        md = _compose_agent_md(repo, meta, host=host)
        (out_agents / f"{meta['id']}.md").write_text(md, encoding="utf-8")
        compiled.append(f"{host}/agents/{meta['id']}")
    # references
    ref_src = agents_src / "references"
    if ref_src.is_dir():
        ref_dst = out_agents / "references"
        if ref_dst.exists():
            _rmtree(ref_dst)
        shutil.copytree(ref_src, ref_dst)

    # Prompts
    if prompts_src.is_dir():
        for src in prompts_src.rglob("*"):
            if src.is_file():
                rel = src.relative_to(prompts_src)
                dst = out_prompts / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        compiled.append(f"{host}/prompts")

    return {"ok": True, "compiled": compiled, "out_root": out_root.as_posix()}


def validate_generated(
    repo: Path, *, host: str = "opencode", generated_root: Path | None = None
) -> list[str]:
    """Validate composed OpenCode/host artifacts against current sources.

    ``generated_root`` lets a read-only auditor validate a throwaway compose
    without touching the real ``generated/<host>`` tree.
    """
    errors: list[str] = []
    gen_root = Path(generated_root) if generated_root else repo / "generated" / host
    out_agents = gen_root / "agents"
    if not out_agents.is_dir():
        errors.append(f"missing generated/{host}/agents")
        return errors

    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows import WORKFLOWS  # noqa: WPS433

    # Engine-identity agents (kind=deterministic_engine) are never composed to host MD.
    engine_ids: set[str] = set()
    agents_src = repo / "agents"
    if agents_src.is_dir():
        for ag in agents_src.glob("*.yaml"):
            meta = _load_yaml(ag)
            if str(meta.get("kind") or "").strip() == "deterministic_engine":
                engine_ids.add(str(meta.get("id") or ag.stem))
            if str(meta.get("id") or ag.stem) in OPENCODE_SKIP_HOST_AGENT_IDS:
                engine_ids.add(str(meta.get("id") or ag.stem))

    # Every referenced non-primary LLM agent must have a generated md
    needed: set[str] = set()
    for wid, meta in WORKFLOWS.items():
        if meta.get("reserved") or not meta.get("slash"):
            continue
        for action in meta.get("actions") or []:
            if not isinstance(action, dict):
                continue
            agent_id = action.get("agent_id")
            if (
                agent_id
                and agent_id != "ascendc-pilot"
                and str(agent_id) not in engine_ids
                and str(action.get("execution_mode") or "") != "deterministic"
            ):
                needed.add(str(agent_id))
            role = action.get("role_id")
            if role in {"producer", "referee", "readonly_analyst"} and not agent_id:
                errors.append(f"{wid}/{action.get('id')}: semantic role missing agent_id")
        # Skill action table must match workflow agents
        skill = gen_root / "skills" / wid / "SKILL.md"
        if skill.is_file():
            text = skill.read_text(encoding="utf-8")
            for action in meta.get("actions") or []:
                if not isinstance(action, dict):
                    continue
                aid = str(action.get("id") or "")
                agent = str(
                    action.get("agent_id")
                    or (
                        "engine"
                        if str(action.get("role_id") or "") == "deterministic_engine"
                        or str(action.get("execution_mode") or "") == "deterministic"
                        else "human"
                    )
                )
                role = str(action.get("role_id") or "-")
                if aid and agent and agent != "human":
                    # Fail if skill still maps this action to a different agent in the Actions table
                    # New table: action_id | execution_mode | agent | role | method | prompt | contract
                    m = re.search(
                        rf"\|\s*`{re.escape(aid)}`\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|",
                        text,
                    )
                    if m:
                        table_mode, table_agent, table_role = m.group(1), m.group(2), m.group(3)
                        deterministic = (
                            str(action.get("role_id") or "") == "deterministic_engine"
                            or str(action.get("execution_mode") or "") == "deterministic"
                        )
                        allowed_agents = {agent}
                        if deterministic:
                            allowed_agents.add("engine")
                        if table_agent not in allowed_agents:
                            errors.append(
                                f"generated/{host}/skills/{wid}: action {aid} agent "
                                f"{table_agent!r} != workflow {agent!r}"
                            )
                        if table_role != role and role != "-":
                            errors.append(
                                f"generated/{host}/skills/{wid}: action {aid} role "
                                f"{table_role!r} != workflow {role!r}"
                            )
                        expected_mode = str(action.get("execution_mode") or "")
                        if expected_mode and table_mode != expected_mode:
                            errors.append(
                                f"generated/{host}/skills/{wid}: action {aid} execution_mode "
                                f"{table_mode!r} != workflow {expected_mode!r}"
                            )

    for agent_id in sorted(needed):
        md = out_agents / f"{agent_id}.md"
        if not md.is_file():
            errors.append(f"generated/{host}/agents missing {agent_id}.md")
            continue
        front, _ = _split_frontmatter(md.read_text(encoding="utf-8"))
        if front.get("type") is not None:
            errors.append(f"generated/{host}/agents/{agent_id}.md: illegal type=; use mode")
        if front.get("mode") not in {"subagent", "primary", "all"}:
            errors.append(
                f"generated/{host}/agents/{agent_id}.md: missing/invalid mode={front.get('mode')!r}"
            )
        unknown = sorted(set(front) - _OPENCODE_AGENT_ALLOWED_KEYS)
        if unknown:
            errors.append(
                f"generated/{host}/agents/{agent_id}.md: unknown OpenCode keys {unknown}"
            )
    return errors


_GENERATED_DRIFT_IGNORE_RES = (
    re.compile(r"(?im)^generated_at\s*[:=].*$"),
    re.compile(r"(?i)[A-Za-z]:\\[^\s\"']+"),  # Windows absolute paths
    re.compile(r"(?i)/tmp/[^\s\"']+"),
    re.compile(r"(?i)/var/folders/[^\s\"']+"),
    re.compile(r"(?i)C:\\Users\\[^\\]+\\AppData\\Local\\Temp[^\s\"']*"),
)


def _normalize_generated_text(text: str, *, tmp_root: str = "", repo_root: str = "") -> str:
    out = text.replace("\r\n", "\n")
    for pat in _GENERATED_DRIFT_IGNORE_RES:
        out = pat.sub("", out)
    if tmp_root:
        out = out.replace(tmp_root.replace("\\", "/"), "<TMP>")
        out = out.replace(tmp_root, "<TMP>")
    if repo_root:
        out = out.replace(repo_root.replace("\\", "/"), "<REPO>")
        out = out.replace(repo_root, "<REPO>")
    # Drop empty lines introduced by stripping generated_at
    lines = [ln for ln in out.split("\n") if ln.strip() != ""]
    return "\n".join(lines) + ("\n" if lines else "")


def check_generated_drift(repo: Path, *, hosts: list[str] | None = None) -> list[str]:
    """Recompose into a temp dir and compare against committed generated/ (content).

    Does not modify the workspace. Returns GENERATED_DRIFT errors with regen hint.
    """
    import tempfile

    host_list = hosts or ["opencode", "cursor", "codex"]
    errors: list[str] = []
    repo = repo.expanduser().resolve()
    src_errors = validate(repo)
    if src_errors:
        return [f"GENERATED_DRIFT: compose sources invalid: {e}" for e in src_errors[:8]]

    with tempfile.TemporaryDirectory(prefix="pilot-gen-") as tmp:
        tmp_path = Path(tmp)
        for host in host_list:
            candidate_root = tmp_path / host
            compose_host(repo, host, out_root=candidate_root)
            committed = repo / "generated" / host
            if not committed.is_dir():
                errors.append(f"GENERATED_DRIFT: missing committed generated/{host}/")
                continue
            cand_files = {
                p.relative_to(candidate_root).as_posix()
                for p in candidate_root.rglob("*")
                if p.is_file()
            }
            committed_files = {
                p.relative_to(committed).as_posix()
                for p in committed.rglob("*")
                if p.is_file()
            }
            only_cand = sorted(cand_files - committed_files)
            only_committed = sorted(committed_files - cand_files)
            for rel in only_cand[:20]:
                errors.append(f"GENERATED_DRIFT: generated/{host}/{rel} missing in repo")
            for rel in only_committed[:20]:
                errors.append(f"GENERATED_DRIFT: generated/{host}/{rel} stale (not in fresh compose)")
            for rel in sorted(cand_files & committed_files):
                left = _normalize_generated_text(
                    (candidate_root / rel).read_text(encoding="utf-8", errors="replace"),
                    tmp_root=str(tmp_path),
                    repo_root=str(repo),
                )
                right = _normalize_generated_text(
                    (committed / rel).read_text(encoding="utf-8", errors="replace"),
                    tmp_root=str(tmp_path),
                    repo_root=str(repo),
                )
                if left != right:
                    errors.append(f"GENERATED_DRIFT: generated/{host}/{rel}")
    if errors:
        errors.append(
            "GENERATED_DRIFT: run `python scripts/compose_runtime.py --repo .` to regenerate"
        )
    return errors


def compose_all(
    repo: Path,
    *,
    hosts: list[str] | None = None,
    sync: bool = True,
) -> dict[str, Any]:
    hosts_dir = repo / "adapters" / "hosts"
    host_names = hosts or [p.stem for p in hosts_dir.glob("*.yaml")]
    if sync:
        sync_errs = sync_sources(repo)
        if sync_errs:
            return {"ok": False, "errors": sync_errs}
    errors = validate(repo)
    if errors:
        return {"ok": False, "errors": errors}
    all_compiled: list[str] = []
    for host in host_names:
        result = compose_host(repo, host)
        if not result.get("ok", True):
            return {
                "ok": False,
                "errors": [
                    f"{host}: {result.get('error') or 'COMPOSE_FAILED'} "
                    f"missing={result.get('missing') or []}"
                ],
                "compiled": all_compiled,
            }
        all_compiled.extend(result.get("compiled") or [])
    gen_errors: list[str] = []
    for host in host_names:
        gen_errors.extend(validate_generated(repo, host=host))
    if gen_errors:
        return {"ok": False, "errors": gen_errors, "compiled": all_compiled}
    return {"ok": True, "compiled": all_compiled, "out_root": (repo / "generated").as_posix()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compose compositional sources → generated/<host>/")
    parser.add_argument("--repo", type=Path, default=None)
    parser.add_argument("--host", action="append", default=[])
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--validate-generated", action="store_true")
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Write action.yaml mirrors + Skill markers (and compose generated/ unless --validate-only)",
    )
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="Only sync action.yaml + Skill markers (no compose)",
    )
    args = parser.parse_args(argv)
    repo = args.repo or Path(__file__).resolve().parents[1]
    if args.sync_only or (args.sync and args.validate_only):
        errors = sync_sources(repo)
        if errors:
            print({"ok": False, "errors": errors})
            return 1
        # After sync, optionally re-validate sources (read-only).
        if args.validate_only:
            errors = validate(repo)
            if args.validate_generated:
                for host in (args.host or ["opencode", "cursor", "codex"]):
                    errors.extend(validate_generated(repo, host=host))
            if errors:
                print({"ok": False, "errors": errors})
                return 1
        print({"ok": True, "synced": True, "errors": []})
        return 0
    if args.validate_only:
        errors = validate(repo)
        if args.validate_generated:
            for host in (args.host or ["opencode", "cursor", "codex"]):
                errors.extend(validate_generated(repo, host=host))
        if errors:
            print({"ok": False, "errors": errors})
            return 1
        print({"ok": True, "errors": []})
        return 0
    # Default compose and --sync both refresh mirrors then regenerate generated/.
    result = compose_all(repo, hosts=args.host or None, sync=True)
    print(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
