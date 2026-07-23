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


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
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
        "skills": repo / "skills-src",
        "prompts": repo / "prompts-src",
        "agents": repo / "agents-src",
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


def validate(repo: Path) -> list[str]:
    """Static validation; returns list of error strings."""
    paths = _repo_paths(repo)
    skills = paths["skills"]
    prompts = paths["prompts"]
    agents = paths["agents"]
    errors: list[str] = []

    sys.path.insert(0, str(repo / "harness"))
    from ascendc_harness.workflows.specs import WORKFLOWS  # noqa: WPS433

    # Collect write scopes by role for overlap check
    producer_writes: set[str] = set()
    referee_writes: set[str] = set()
    for ag_path in agents.glob("*.yaml"):
        meta = _load_yaml(ag_path)
        role = str(meta.get("role") or "")
        scopes = {str(x) for x in (meta.get("write_scopes") or [])}
        if role == "producer":
            producer_writes |= scopes
        elif role == "referee":
            referee_writes |= scopes
    overlap = producer_writes & referee_writes
    # Allow shared runs/** scratch if both declare it — still flag exact same product globs excluding runs
    bad = {x for x in overlap if not str(x).startswith("runs")}
    if bad:
        errors.append(f"producer/referee write_scopes overlap: {sorted(bad)}")

    for wid, meta in WORKFLOWS.items():
        if meta.get("reserved") or not meta.get("slash"):
            continue
        skill_md = skills / "workflows" / wid / "SKILL.md"
        if not skill_md.is_file():
            errors.append(f"missing workflow skill: {skill_md}")
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
            if agent_id and agent_id != "ascendc-agent":
                if not (agents / f"{agent_id}.yaml").is_file():
                    errors.append(f"{wid}/{aid}: missing agent {agent_id}")

    # operator workflow skill required
    if not (skills / "workflows" / "operator" / "SKILL.md").is_file():
        errors.append("missing workflows/operator/SKILL.md")

    return errors


def _compose_skill_body(skills: Path, wid: str, meta: dict[str, Any]) -> str:
    src = skills / "workflows" / wid / "SKILL.md"
    raw = src.read_text(encoding="utf-8") if src.is_file() else f"# {wid}\n"
    _, body = _split_frontmatter(raw)
    # Inject harness-control policy summary once
    hc = _read_policy(skills, "harness-control")
    if "## Composed: harness-control" not in body and hc:
        body = body.rstrip() + "\n\n## Composed: harness-control\n\n" + hc + "\n"
    # Index composed refs
    lines = ["\n## Composition index\n", "| action_id | policies | capabilities | method | prompt | agent |", "|---|---|---|---|---|---|"]
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
    return body.rstrip() + "\n" + "\n".join(lines) + "\n"


def _compose_agent_md(repo: Path, agent_meta: dict[str, Any]) -> str:
    skills = repo / "skills-src"
    aid = agent_meta.get("id", "agent")
    role = agent_meta.get("role", "")
    reads = "\n".join(f"- `{x}`" for x in (agent_meta.get("read_scopes") or [])) or "- (none)"
    writes = "\n".join(f"- `{x}`" for x in (agent_meta.get("write_scopes") or [])) or "- (none)"
    forbidden = "\n".join(f"- {x}" for x in (agent_meta.get("forbidden") or []))
    hc = _read_policy(skills, "harness-control")
    lang = _read_policy(skills, "language")
    front: dict[str, Any] = {
        "name": aid,
        "description": agent_meta.get("description") or aid,
    }
    if agent_meta.get("mode") == "primary":
        front["mode"] = "primary"
        front["permission"] = {
            "bash": {"*": "deny", "harness *": "allow"},
            "edit": {"*": "ask"},
            "write": {"*": "ask"},
        }
    else:
        front["type"] = "subagent"

    body = f"""# Agent: {aid}

## Role

You are a `{role}` for AscendC Agent Harness.

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

1. the current Harness Action;
2. the composed Policies;
3. the composed Capabilities;
4. the task Prompt;
5. the declared Output Contract.

When these sources conflict, follow the Harness Action and source-authority Policy.

## Composed: harness-control

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

    sys.path.insert(0, str(repo / "harness"))
    from ascendc_harness.workflows.specs import WORKFLOWS  # noqa: WPS433

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
        meta, _ = _split_frontmatter((src / "SKILL.md").read_text(encoding="utf-8"))
        overrides = dict(host_meta.get("skill_defaults") or {})
        per_skill = (host_meta.get("skills") or {}).get(wid) or {}
        if isinstance(per_skill, dict):
            overrides.update(per_skill)
        meta = {**meta, **overrides}
        wf_meta = WORKFLOWS.get(wid) or {}
        body = _compose_skill_body(skills, wid, wf_meta) if wid != "operator" else _split_frontmatter((src / "SKILL.md").read_text(encoding="utf-8"))[1]
        if wid == "operator":
            hc = _read_policy(skills, "harness-control")
            body = body.rstrip() + "\n\n## Composed: harness-control\n\n" + hc + "\n"
        dest = out_skills / wid
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "SKILL.md").write_text(_dump_frontmatter(meta) + "\n" + body.lstrip("\n"), encoding="utf-8")
        # Copy action methods referenced by this workflow as sidecars
        for a in wf_meta.get("actions") or []:
            mid = a.get("action_method_id")
            if not mid:
                continue
            _, method = _read_action(skills, str(mid))
            if not method:
                continue
            folder = str(mid).split("/", 1)[-1]
            adir = dest / "actions" / folder
            adir.mkdir(parents=True, exist_ok=True)
            (adir / "METHOD.md").write_text(method, encoding="utf-8")
            ayaml, _ = _read_action(skills, str(mid))
            if ayaml:
                if yaml is not None:
                    (adir / "action.yaml").write_text(
                        yaml.safe_dump(ayaml, allow_unicode=True, sort_keys=False),
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


def compose_all(repo: Path, *, hosts: list[str] | None = None) -> dict[str, Any]:
    skills = repo / "skills-src"
    hosts_dir = skills / "hosts"
    host_names = hosts or [p.stem for p in hosts_dir.glob("*.yaml")]
    errors = validate(repo)
    if errors:
        return {"ok": False, "errors": errors}
    all_compiled: list[str] = []
    for host in host_names:
        result = compose_host(repo, host)
        all_compiled.extend(result.get("compiled") or [])
    return {"ok": True, "compiled": all_compiled, "out_root": (repo / "generated").as_posix()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compose compositional sources → generated/<host>/")
    parser.add_argument("--repo", type=Path, default=None)
    parser.add_argument("--host", action="append", default=[])
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    repo = args.repo or Path(__file__).resolve().parents[1]
    if args.validate_only:
        errors = validate(repo)
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
