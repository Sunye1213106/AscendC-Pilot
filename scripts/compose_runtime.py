#!/usr/bin/env python3
"""Compose Policy/Capability/Action/Prompt/Agent → generated/<host>/{skills,agents,prompts}."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
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
        if "## Composition index" not in body:
            raise ValueError(f"generated skill missing Composition index: {path}")
        section = body.split("## Composition index", 1)[1]
        # Stop at next H2 so Action runtime index is not double-counted.
        section = re.split(r"\n##\s+", section, maxsplit=1)[0]
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
        "out": repo / "generated",
    }


def _read_policy(skills: Path, pid: str) -> str:
    p = skills / "policies" / pid / "POLICY.md"
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def _read_capability(skills: Path, cid: str) -> tuple[dict[str, Any], str]:
    d = skills / "capabilities" / cid
    return _load_yaml(d / "capability.yaml"), (d / "METHOD.md").read_text(encoding="utf-8") if (d / "METHOD.md").is_file() else ""


def _read_action(skills: Path, method_id: str) -> tuple[dict[str, Any], str]:
    # method_id like uo-init/key-resolution
    parts = method_id.split("/", 1)
    if len(parts) != 2:
        return {}, ""
    d = skills / "actions" / parts[0] / parts[1]
    return _load_yaml(d / "action.yaml"), (d / "METHOD.md").read_text(encoding="utf-8") if (d / "METHOD.md").is_file() else ""


def _scan_forbidden(path: Path, text: str, errors: list[str]) -> None:
    for i, line in enumerate(text.splitlines(), 1):
        low = line.lower()
        if "must not" in low or "禁止" in line or "不得" in line or "勿" in line:
            continue
        for pat in _FORBIDDEN_PATTERNS:
            if pat.search(line):
                errors.append(f"forbidden pattern {pat.pattern!r} in {path.as_posix()}:{i}")


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
        if str(p).startswith("runs"):
            continue
        for r in sorted(referee_writes):
            if str(r).startswith("runs"):
                continue
            if _scopes_conflict(str(p), str(r)):
                errors.append(f"producer/referee write_scopes overlap: {p!r} vs {r!r}")
    return errors


def validate(repo: Path) -> list[str]:
    """Static validation; returns list of error strings."""
    paths = _repo_paths(repo)
    skills = paths["skills"]
    prompts = paths["prompts"]
    agents = paths["agents"]
    errors: list[str] = []

    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows.specs import WORKFLOWS  # noqa: WPS433

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
        if role in {"producer", "referee", "readonly_analyst", "deterministic_engine"} and not mode:
            # Defaulted to subagent at compose time; warn as error to keep sources explicit.
            if aid != "ascendc-pilot":
                errors.append(f"agent {aid}: missing mode (use mode: subagent)")
        if role == "producer":
            producer_writes |= scopes
        elif role == "referee":
            referee_writes |= scopes
    bad = _scope_overlap_errors(producer_writes, referee_writes)
    errors.extend(bad)

    # Note: generated/ OpenCode frontmatter is validated after compose (see validate_generated).
    # Pre-compose validate only checks sources so install can regenerate stale trees.

    for wid, meta in WORKFLOWS.items():
        if meta.get("reserved") or not meta.get("slash"):
            continue
        skill_md = skills / "workflows" / wid / "SKILL.md"
        if not skill_md.is_file():
            errors.append(f"missing workflow skill: {skill_md}")
        else:
            try:
                _require_skill_frontmatter(skill_md.read_text(encoding="utf-8"), path=skill_md)
            except ValueError as exc:
                errors.append(str(exc))
        for action in meta.get("actions") or []:
            if not isinstance(action, dict):
                continue
            aid = action.get("id")
            for pid in action.get("policy_ids") or []:
                if not (skills / "policies" / pid / "POLICY.md").is_file():
                    errors.append(f"{wid}/{aid}: missing policy {pid}")
            for cid in action.get("capability_ids") or []:
                if not (skills / "capabilities" / cid / "capability.yaml").is_file():
                    errors.append(f"{wid}/{aid}: missing capability {cid}")
            mid = action.get("action_method_id")
            if mid:
                _, method = _read_action(skills, str(mid))
                if not method:
                    errors.append(f"{wid}/{aid}: missing action method {mid}")
                else:
                    _scan_forbidden(Path(str(mid)), method, errors)
            tpid = action.get("task_prompt_id")
            if tpid:
                p = prompts / "tasks" / f"{tpid}.md"
                # tpid is domain/name
                if "/" in str(tpid):
                    dom, name = str(tpid).split("/", 1)
                    p = prompts / "tasks" / dom / f"{name}.md"
                if not p.is_file():
                    errors.append(f"{wid}/{aid}: missing task prompt {tpid}")
                else:
                    _scan_forbidden(p, p.read_text(encoding="utf-8"), errors)
            # Semantic actions need role + context + output contract
            if action.get("role_id") in {"producer", "referee", "readonly_analyst"}:
                if not action.get("context_profile_id"):
                    errors.append(f"{wid}/{aid}: missing context_profile_id")
                if not action.get("output_contract_id"):
                    errors.append(f"{wid}/{aid}: missing output_contract_id")
            agent_id = action.get("agent_id")
            if agent_id and agent_id != "ascendc-pilot":
                if not (agents / f"{agent_id}.yaml").is_file():
                    errors.append(f"{wid}/{aid}: missing agent {agent_id}")

    # operator workflow skill required
    if not (skills / "workflows" / "operator" / "SKILL.md").is_file():
        errors.append("missing workflows/operator/SKILL.md")

    return errors


def _replace_actions_table(body: str, meta: dict[str, Any]) -> str:
    """Replace human Actions table with Workflow Spec authority (single source)."""
    rows = [
        "| action_id | 名称 | method | agent | role |",
        "|---|---|---|---|---|",
    ]
    for a in meta.get("actions") or []:
        if not isinstance(a, dict):
            continue
        rows.append(
            "| `{id}` | {label} | `{method}` | `{agent}` | `{role}` |".format(
                id=a.get("id"),
                label=a.get("label_zh") or a.get("id") or "",
                method=a.get("action_method_id") or "-",
                agent=a.get("agent_id") or "human",
                role=a.get("role_id") or "-",
            )
        )
    table = "## Actions\n\n" + "\n".join(rows) + "\n"
    # Replace existing ## Actions section through next H2, or append.
    if re.search(r"(?m)^## Actions\s*$", body):
        return re.sub(
            r"(?ms)^## Actions\s*\n.*?(?=^## |\Z)",
            table + "\n",
            body,
            count=1,
        )
    return body.rstrip() + "\n\n" + table


def _compose_skill_body(skills: Path, wid: str, meta: dict[str, Any]) -> str:
    src = skills / "workflows" / wid / "SKILL.md"
    raw = src.read_text(encoding="utf-8") if src.is_file() else f"---\nname: {wid}\ndescription: {wid}\n---\n\n# {wid}\n"
    _, body = _require_skill_frontmatter(raw, path=src if src.is_file() else None)
    body = _replace_actions_table(body, meta)
    # Inject pilot-control policy summary once
    hc = _read_policy(skills, "pilot-control")
    if "## Composed: pilot-control" not in body and hc:
        body = body.rstrip() + "\n\n## Composed: pilot-control\n\n" + hc + "\n"
    # Index composed refs + runtime bundle paths
    lines = [
        "\n## Composition index\n",
        "| action_id | policies | capabilities | method | prompt | agent |",
        "|---|---|---|---|---|---|",
    ]
    runtime_lines = [
        "\n## Action runtime index\n",
        "| action_id | method_path | prompt_path | output_contract | role |",
        "|---|---|---|---|---|",
    ]
    for a in meta.get("actions") or []:
        lines.append(
            "| `{id}` | {pols} | {caps} | `{method}` | `{prompt}` | `{agent}` |".format(
                id=a.get("id"),
                pols=",".join(a.get("policy_ids") or []) or "-",
                caps=",".join(a.get("capability_ids") or []) or "-",
                method=a.get("action_method_id") or "-",
                prompt=a.get("task_prompt_id") or "-",
                agent=a.get("agent_id") or "human",
            )
        )
        mid = str(a.get("action_method_id") or "")
        folder = mid.split("/", 1)[-1] if mid else "-"
        tpid = str(a.get("task_prompt_id") or "")
        prompt_path = f"prompts/tasks/{tpid}.md" if tpid and "/" not in tpid else (
            f"prompts/tasks/{tpid}.md" if tpid else "-"
        )
        if tpid and "/" in tpid:
            dom, name = tpid.split("/", 1)
            prompt_path = f"prompts/tasks/{dom}/{name}.md"
        runtime_lines.append(
            "| `{id}` | `actions/{folder}/METHOD.md` | `{prompt}` | `{contract}` | `{role}` |".format(
                id=a.get("id"),
                folder=folder,
                prompt=prompt_path,
                contract=a.get("output_contract_id") or "-",
                role=a.get("role_id") or "-",
            )
        )
    return body.rstrip() + "\n" + "\n".join(lines) + "\n" + "\n".join(runtime_lines) + "\n"


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


def _compose_agent_md(repo: Path, agent_meta: dict[str, Any]) -> str:
    skills = repo / "skills"
    aid = agent_meta.get("id", "agent")
    role = agent_meta.get("role", "")
    reads = "\n".join(f"- `{x}`" for x in (agent_meta.get("read_scopes") or [])) or "- (none)"
    writes = "\n".join(f"- `{x}`" for x in (agent_meta.get("write_scopes") or [])) or "- (none)"
    forbidden = "\n".join(f"- {x}" for x in (agent_meta.get("forbidden") or []))
    hc = _read_policy(skills, "pilot-control")
    lang = _read_policy(skills, "language")
    front: dict[str, Any] = {
        "name": aid,
        "description": agent_meta.get("description") or aid,
    }
    if agent_meta.get("mode") == "primary":
        front["mode"] = "primary"
        front["permission"] = {
            "bash": {"*": "deny", "acp *": "allow"},
            "edit": {"*": "ask"},
            "write": {"*": "ask"},
        }
    else:
        # OpenCode recognizes mode=subagent (not type=subagent).
        front["mode"] = "subagent"

    body = f"""# Agent: {aid}

## Role

You are a `{role}` for AscendC-Pilot.

{agent_meta.get('description') or ''}

## Boundaries

You may read:

{reads}

You may write:

{writes}

You must not:

{forbidden}

## Runtime Contract

At runtime, follow:

1. **First**: Read the session `prompt.md` from the prepared Action Bundle (path given by Host `task_prompt_stub` / `session_dir`). Treat it as the sole task body.
2. Then the current Pilot Action / METHOD only as referenced by that prompt;
3. the composed Policies;
4. the composed Capabilities;
5. the declared Output Contract.

When these sources conflict, follow the session `prompt.md` and Pilot Action / source-authority Policy.
Do **not** invent extra goals beyond the session prompt. Do **not** finalize the Action (primary runs `--finalize`).

## Composed: pilot-control

{hc}

## Composed: language

{lang}
"""
    return _dump_frontmatter(front) + "\n" + body


def compose_host(repo: Path, host: str) -> dict[str, Any]:
    paths = _repo_paths(repo)
    skills = paths["skills"]
    prompts_src = paths["prompts"]
    agents_src = paths["agents"]
    out_root = paths["out"] / host
    host_meta = _load_yaml(skills / "hosts" / f"{host}.yaml")

    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows.specs import WORKFLOWS  # noqa: WPS433

    if out_root.exists():
        shutil.rmtree(out_root)
    out_skills = out_root / "skills"
    out_agents = out_root / "agents"
    out_prompts = out_root / "prompts"
    out_skills.mkdir(parents=True)
    out_agents.mkdir(parents=True)
    out_prompts.mkdir(parents=True)

    compiled: list[str] = []

    # Workflow skills + operator
    workflow_ids = [wid for wid, m in WORKFLOWS.items() if m.get("slash") and not m.get("reserved")]
    workflow_ids.append("operator")
    for wid in workflow_ids:
        src = skills / "workflows" / wid
        if not (src / "SKILL.md").is_file():
            continue
        meta, src_body = _require_skill_frontmatter(
            (src / "SKILL.md").read_text(encoding="utf-8"), path=src / "SKILL.md"
        )
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
        body = _compose_skill_body(skills, wid, wf_meta) if wid != "operator" else src_body
        if wid == "operator":
            hc = _read_policy(skills, "pilot-control")
            body = body.rstrip() + "\n\n## Composed: pilot-control\n\n" + hc + "\n"
        dest = out_skills / wid
        dest.mkdir(parents=True, exist_ok=True)
        skill_out = dest / "SKILL.md"
        # Ensure composed frontmatter keeps name/description; do not indent.
        out_text = _dump_frontmatter(meta) + "\n" + body.lstrip("\n")
        if not out_text.startswith("---\n"):
            raise ValueError(f"composed skill must start with ---: {skill_out}")
        skill_out.write_text(out_text, encoding="utf-8")
        expected_n = len(wf_meta.get("actions") or []) if wid != "operator" else None
        _assert_generated_skill(skill_out, expected_actions=expected_n)
        # Copy action methods referenced by this workflow as sidecars;
        # cross-check action.yaml against Workflow Spec (single runtime authority).
        for a in wf_meta.get("actions") or []:
            mid = a.get("action_method_id")
            if not mid:
                continue
            ayaml, method = _read_action(skills, str(mid))
            if not method:
                continue
            folder = str(mid).split("/", 1)[-1]
            adir = dest / "actions" / folder
            adir.mkdir(parents=True, exist_ok=True)
            (adir / "METHOD.md").write_text(method, encoding="utf-8")
            # Spec wins for identity fields; keep method-local extras.
            merged = dict(ayaml or {})
            for key in (
                "id",
                "workflow_id",
                "role_id",
                "agent_id",
                "capabilities",
                "policies",
                "task_prompt_id",
                "context_profile_id",
                "output_contract_id",
            ):
                if key == "id" and a.get("id"):
                    merged["id"] = a["id"]
                elif key == "workflow_id":
                    merged["workflow_id"] = wid
                elif key == "role_id" and a.get("role_id"):
                    merged["role_id"] = a["role_id"]
                elif key == "agent_id" and a.get("agent_id"):
                    merged["agent_id"] = a["agent_id"]
                elif key == "capabilities" and a.get("capability_ids"):
                    merged["capabilities"] = list(a["capability_ids"])
                elif key == "policies" and a.get("policy_ids"):
                    merged["policies"] = list(a["policy_ids"])
                elif key == "task_prompt_id" and a.get("task_prompt_id"):
                    merged["task_prompt_id"] = a["task_prompt_id"]
                elif key == "context_profile_id" and a.get("context_profile_id"):
                    merged["context_profile_id"] = a["context_profile_id"]
                elif key == "output_contract_id" and a.get("output_contract_id"):
                    merged["output_contract_id"] = a["output_contract_id"]
            merged["checker"] = {"required": bool(a.get("checker_required", True))}
            merged["referee"] = {"required": bool(a.get("referee_required", False))}
            if yaml is not None:
                (adir / "action.yaml").write_text(
                    yaml.safe_dump(merged, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
        # Copy capabilities used
        caps_needed: set[str] = set()
        for a in wf_meta.get("actions") or []:
            caps_needed.update(a.get("capability_ids") or [])
        for cid in sorted(caps_needed):
            csrc = skills / "capabilities" / cid
            if csrc.is_dir():
                cdst = dest / "capabilities" / cid
                if cdst.exists():
                    shutil.rmtree(cdst)
                shutil.copytree(csrc, cdst)
        compiled.append(f"{host}/skills/{wid}")

    # Shared policies pack under each host
    pol_dst = out_skills / "_policies"
    pol_dst.mkdir(parents=True, exist_ok=True)
    for pdir in (skills / "policies").iterdir():
        if pdir.is_dir():
            d = pol_dst / pdir.name
            if d.exists():
                shutil.rmtree(d)
            shutil.copytree(pdir, d)

    # Agents
    for ag in sorted(agents_src.glob("*.yaml")):
        meta = _load_yaml(ag)
        if not meta.get("id"):
            continue
        md = _compose_agent_md(repo, meta)
        (out_agents / f"{meta['id']}.md").write_text(md, encoding="utf-8")
        compiled.append(f"{host}/agents/{meta['id']}")
    # references
    ref_src = agents_src / "references"
    if ref_src.is_dir():
        ref_dst = out_agents / "references"
        if ref_dst.exists():
            shutil.rmtree(ref_dst)
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


def validate_generated(repo: Path, *, host: str = "opencode") -> list[str]:
    """Validate composed OpenCode/host artifacts against current sources."""
    errors: list[str] = []
    out_agents = repo / "generated" / host / "agents"
    if not out_agents.is_dir():
        errors.append(f"missing generated/{host}/agents")
        return errors

    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows.specs import WORKFLOWS  # noqa: WPS433

    # Every referenced non-primary agent must have a generated md
    needed: set[str] = set()
    for wid, meta in WORKFLOWS.items():
        if meta.get("reserved") or not meta.get("slash"):
            continue
        for action in meta.get("actions") or []:
            if not isinstance(action, dict):
                continue
            agent_id = action.get("agent_id")
            if agent_id and agent_id != "ascendc-pilot":
                needed.add(str(agent_id))
            role = action.get("role_id")
            if role in {"producer", "referee", "readonly_analyst"} and not agent_id:
                errors.append(f"{wid}/{action.get('id')}: semantic role missing agent_id")
        # Skill action table must match workflow agents
        skill = repo / "generated" / host / "skills" / wid / "SKILL.md"
        if skill.is_file():
            text = skill.read_text(encoding="utf-8")
            for action in meta.get("actions") or []:
                if not isinstance(action, dict):
                    continue
                aid = str(action.get("id") or "")
                agent = str(action.get("agent_id") or "human")
                role = str(action.get("role_id") or "-")
                # Composition index row must list the workflow agent
                if aid and f"| `{aid}` |" in text:
                    # Prefer Action runtime index role column
                    if f"| `{aid}` |" in text and role != "-" and f"| `{role}` |" not in text.split(f"| `{aid}` |", 1)[-1][:200]:
                        # Soft: check composition index agent cell
                        pass
                if aid and agent and agent != "human":
                    # Fail if skill still maps this action to a different agent in the Actions table
                    m = re.search(
                        rf"\|\s*`{re.escape(aid)}`\s*\|\s*[^|]+\|\s*`[^`]+`\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|",
                        text,
                    )
                    if m:
                        table_agent, table_role = m.group(1), m.group(2)
                        if table_agent != agent:
                            errors.append(
                                f"generated/{host}/skills/{wid}: action {aid} agent "
                                f"{table_agent!r} != workflow {agent!r}"
                            )
                        if table_role != role and role != "-":
                            errors.append(
                                f"generated/{host}/skills/{wid}: action {aid} role "
                                f"{table_role!r} != workflow {role!r}"
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


def compose_all(repo: Path, *, hosts: list[str] | None = None) -> dict[str, Any]:
    skills = repo / "skills"
    hosts_dir = skills / "hosts"
    host_names = hosts or [p.stem for p in hosts_dir.glob("*.yaml")]
    errors = validate(repo)
    if errors:
        return {"ok": False, "errors": errors}
    all_compiled: list[str] = []
    for host in host_names:
        result = compose_host(repo, host)
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
    args = parser.parse_args(argv)
    repo = args.repo or Path(__file__).resolve().parents[1]
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
    result = compose_all(repo, hosts=args.host or None)
    print(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
