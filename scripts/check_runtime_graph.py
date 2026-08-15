#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Static integrity check: Workflow ↔ Agent ↔ Prompt ↔ Contract ↔ Engine graph.

Fails when production forward references are missing, unused, or deprecated
prompts remain under prompts/tasks/.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PILOT = REPO / "pilot"
sys.path.insert(0, str(PILOT))

FORBIDDEN_PROD_MARKERS = re.compile(
    r"(?i)\b(deprecated|RESERVED\s*—\s*deprecated|codebase-memory|codebasememory|"
    r"stage_cbm_scope|cbm_scope|cbm_db)\b"
)
CBM_ALLOW = ("docs/history/",)
# Active-product vocabulary bans (deny-lists / history docs exempt via path rules).
BANNED_TOKEN_RE = re.compile(
    r"(?i)\b(csv_consumer(?:_root)?|scope_confirm(?:_\w+)?|stage_cbm|"
    r"cbm_queries|needs_cbm_reindex|ASCENDC_CSV_CONSUMER_ROOT)\b"
)
# Exact legacy TG Z3 product identifiers (not the Z3 library name itself).
# Include unsuffixed ``legacy_z3`` as well as ``legacy_z3_solver``.
BANNED_Z3_LEGACY_RE = re.compile(
    r"(?i)\b(z3_solve|z3-solve(?:-v1)?|legacy_z3(?:_solver)?|z3_solver_v1)\b"
)
# Silent architecture fallback patterns (not legitimate arch string uses).
ARCH35_FALLBACK_PATTERNS = (
    re.compile(r"""or\s+["']arch35["'](?!\s+in\b)"""),
    re.compile(r"""default\s*=\s*["']arch35["']"""),
    re.compile(r"""(?m)^\s*return\s+["']arch35["']\s*$"""),
)


def _scan_sqlite_product_engines(repo: Path, errors: list[str]) -> None:
    """Fail if the public UO ENGINES dict re-registers sqlite export/index."""
    path = repo / "engines" / "understand-operator" / "src" / "uo_init" / "pilot_engines.py"
    if not path.is_file():
        errors.append("missing uo_init/pilot_engines.py")
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^ENGINES: dict\[str, Any\] = \{.*?\n\}\n", text, re.M | re.S)
    if not match:
        errors.append("pilot_engines.py missing ENGINES dict")
        return
    block = match.group(0)
    for name in ("export_kb", "build_index"):
        if re.search(rf'["\']{name}["\']\s*:', block):
            errors.append(f"ENGINES must not register {name}")


def _scan_uo_scope_vocab(repo: Path, errors: list[str]) -> None:
    """Fail closed if uo-scope public CLI reintroduces checkpoint/finalize/decision."""
    cli = repo / "pilot" / "ascendc_pilot" / "cli.py"
    scope = repo / "pilot" / "ascendc_pilot" / "uo_scope.py"
    if cli.is_file():
        text = cli.read_text(encoding="utf-8", errors="replace")
        # Isolate the uo-scope parser block.
        idx = text.find('sub.add_parser(\n        "uo-scope"')
        if idx < 0:
            idx = text.find('"uo-scope"')
        chunk = text[idx : idx + 1200] if idx >= 0 else ""
        if '"checkpoint"' in chunk or '"finalize"' in chunk:
            errors.append("cli.py uo-scope must not expose checkpoint/finalize choices")
        if "--decision" in chunk:
            errors.append("cli.py uo-scope must not expose --decision")
    if scope.is_file():
        text = scope.read_text(encoding="utf-8", errors="replace")
        # Active alias map must not remap retired vocabulary.
        if re.search(r'''["']checkpoint["']\s*:\s*["']scope_validate["']''', text):
            errors.append("uo_scope.py must not alias checkpoint → scope_validate")
        if re.search(r'''["']finalize["']\s*:\s*["']scope_validate["']''', text):
            errors.append("uo_scope.py must not alias finalize → scope_validate")
        if re.search(r'''["']confirm["']\s*:\s*["']scope_validate["']''', text):
            errors.append("uo_scope.py must not alias confirm → scope_validate")


def _scan_plugin_host_adapter(repo: Path, errors: list[str]) -> None:
    """Fail closed if OpenCode plugin reintroduces flat .ascendc-pilot/state paths."""
    plugin = repo / "opencode-plugin" / "ascendc-pilot.ts"
    if not plugin.is_file():
        errors.append("missing opencode-plugin/ascendc-pilot.ts")
        return
    text = plugin.read_text(encoding="utf-8", errors="replace")
    if "function findPilotStateFile" not in text:
        errors.append("plugin missing findPilotStateFile helper")
    if "host-context" not in text:
        errors.append("plugin must call acp host-context for active action identity")
    # Flat concatenations outside findPilotStateFile.
    for m in re.finditer(r"""["']\.ascendc-pilot["']\s*,\s*["']state["']""", text):
        before = text[: m.start()]
        fns = list(re.finditer(r"function\s+(\w+)\s*\(", before))
        if not fns or fns[-1].group(1) != "findPilotStateFile":
            errors.append(
                "plugin flat .ascendc-pilot/state path outside findPilotStateFile"
            )
            break
    # Arch-neutral control plane must remain.
    if "pending_interaction.yaml" not in text or "control" not in text:
        errors.append("plugin must keep arch-neutral control/pending_interaction path")
    if "active_run.yaml" not in text:
        errors.append("plugin must consult control/active_run.yaml for multi-arch state")


def _scan_banned_production_symbols(repo: Path, errors: list[str]) -> None:
    scan_roots = [
        repo / "pilot",
        repo / "engines",
        repo / "agents",
        repo / "prompts",
        repo / "skills",
        repo / "scripts",
    ]
    for root in scan_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".py", ".md", ".yaml", ".yml", ".json", ".ts", ".sh", ".ps1"}:
                continue
            rel = path.relative_to(repo).as_posix()
            if any(rel.startswith(a) for a in CBM_ALLOW):
                continue
            if "_pytest_tmp" in rel or "/tests/" in f"/{rel}" or rel.startswith("evals/"):
                continue
            if path.name == "check_runtime_graph.py":
                continue
            # Deny-lists that mention banned tokens to block them are allowed.
            if rel.replace("\\", "/").endswith(
                ("authorize/__init__.py", "ascendc_pilot/uo_scope.py")
            ):
                continue
            try:
                body = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if BANNED_TOKEN_RE.search(body):
                errors.append(
                    f"banned token (csv_consumer/scope_confirm/stage_cbm/"
                    f"cbm_queries/needs_cbm_reindex/ASCENDC_CSV_CONSUMER_ROOT) "
                    f"in production path: {rel}"
                )
            if BANNED_Z3_LEGACY_RE.search(body):
                errors.append(
                    f"banned legacy Z3 product id in production path: {rel}"
                )
            for pat in ARCH35_FALLBACK_PATTERNS:
                if pat.search(body):
                    errors.append(f"silent arch35 fallback pattern {pat.pattern!r} in {rel}")
                    break


def _main() -> int:
    from ascendc_pilot.actions.engines import ENGINE_REGISTRY, OUTPUT_CONTRACT_PATHS
    from ascendc_pilot.workflows import WORKFLOWS

    errors: list[str] = []
    agents_dir = REPO / "agents"
    prompts_dir = REPO / "prompts" / "tasks"
    skills_dir = REPO / "skills"

    used_agents: set[str] = set()
    used_prompts: set[str] = set()
    used_contracts: set[str] = set()
    used_engine_actions: set[tuple[str, str]] = set()

    for wf_id, meta in WORKFLOWS.items():
        if not isinstance(meta, dict):
            continue
        for row in meta.get("agents") or []:
            if isinstance(row, dict) and row.get("id"):
                aid = str(row["id"])
                used_agents.add(aid)
                if not (agents_dir / f"{aid}.yaml").is_file():
                    errors.append(f"workflow {wf_id}: missing agents/{aid}.yaml")
        for action in meta.get("actions") or []:
            if not isinstance(action, dict):
                continue
            aid = str(action.get("id") or "")
            agent_id = str(action.get("agent_id") or "").strip()
            if agent_id:
                used_agents.add(agent_id)
                if not (agents_dir / f"{agent_id}.yaml").is_file():
                    errors.append(
                        f"workflow {wf_id} action {aid}: missing agents/{agent_id}.yaml"
                    )
            tpid = action.get("task_prompt_id")
            if tpid:
                tpid_s = str(tpid)
                used_prompts.add(tpid_s)
                if "/" not in tpid_s:
                    errors.append(
                        f"workflow {wf_id} action {aid}: bad task_prompt_id {tpid_s!r}"
                    )
                else:
                    dom, name = tpid_s.split("/", 1)
                    pp = prompts_dir / dom / f"{name}.md"
                    if not pp.is_file():
                        errors.append(
                            f"workflow {wf_id} action {aid}: missing prompt {pp.relative_to(REPO)}"
                        )
            for contract_field in ("output_contract_id", "staging_contract_id"):
                contract_id = action.get(contract_field)
                if not contract_id:
                    continue
                contract_id_s = str(contract_id)
                used_contracts.add(contract_id_s)
                if contract_id_s not in OUTPUT_CONTRACT_PATHS:
                    errors.append(
                        f"workflow {wf_id} action {aid}: unknown {contract_field} "
                        f"{contract_id_s}"
                    )
            mode = str(action.get("execution_mode") or "")
            key = (wf_id, aid)
            if key in ENGINE_REGISTRY or mode == "deterministic":
                used_engine_actions.add(key)
            if mode == "deterministic" and key not in ENGINE_REGISTRY:
                errors.append(
                    f"workflow {wf_id} action {aid}: missing ENGINE_REGISTRY entry"
                )

    # Production prompts must not be deprecated / contain CBM markers
    if prompts_dir.is_dir():
        for md in prompts_dir.rglob("*.md"):
            body = md.read_text(encoding="utf-8", errors="replace")
            if FORBIDDEN_PROD_MARKERS.search(body):
                errors.append(f"production prompt has forbidden marker: {md.relative_to(REPO)}")

    # Unused production prompts are warnings; forward refs above are authoritative.
    unused_prompts: list[str] = []
    if prompts_dir.is_dir():
        for md in prompts_dir.rglob("*.md"):
            rel = md.relative_to(prompts_dir).as_posix()
            if not rel.endswith(".md"):
                continue
            tid = rel[:-3]
            if tid not in used_prompts:
                unused_prompts.append(tid)
    for tid in unused_prompts:
        print(f"  warn: unused production prompt prompts/tasks/{tid}.md")

    # Agents: every production agent yaml must be used (allow primary + known)
    agent_allow = {"ascendc-pilot"}
    if agents_dir.is_dir():
        for yml in agents_dir.glob("*.yaml"):
            aid = yml.stem
            if aid not in used_agents and aid not in agent_allow:
                errors.append(f"unused production agent: agents/{aid}.yaml")

    unused_engine_actions = set(ENGINE_REGISTRY) - used_engine_actions
    for wf_id, action_id in sorted(unused_engine_actions):
        errors.append(f"orphan ENGINE_REGISTRY entry: {wf_id}/{action_id}")

    unused_contracts = set(OUTPUT_CONTRACT_PATHS) - used_contracts
    for contract_id in sorted(unused_contracts):
        errors.append(f"orphan OUTPUT_CONTRACT_PATHS entry: {contract_id}")

    # Skill refs from agents (skills / skill_ids lists)
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None
    if yaml and agents_dir.is_dir():
        for yml in agents_dir.glob("*.yaml"):
            meta = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
            for sk in list(meta.get("skills") or []) + list(meta.get("skill_ids") or []):
                sk_s = str(sk).strip()
                if not sk_s:
                    continue
                if not (skills_dir / sk_s / "SKILL.md").is_file():
                    errors.append(f"agent {yml.stem}: missing skill {sk_s}")

    # CBM hygiene in production trees (not docs/history)
    cbm_re = re.compile(
        r"(?i)(codebase-memory|codebasememory|stage_cbm_scope|cbm_scope|cbm_db)"
    )
    scan_roots = [
        REPO / "pilot",
        REPO / "engines",
        REPO / "agents",
        REPO / "prompts",
        REPO / "skills",
        REPO / "scripts",
    ]
    for root in scan_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".py", ".md", ".yaml", ".yml", ".json", ".ts", ".sh", ".ps1"}:
                continue
            rel = path.relative_to(REPO).as_posix()
            if any(rel.startswith(a) for a in CBM_ALLOW):
                continue
            if "_pytest_tmp" in rel or "/tests/" in f"/{rel}" or rel.startswith("evals/"):
                continue
            if path.name == "check_runtime_graph.py":
                continue
            # Deny-lists that mention CBM to block it are allowed.
            if rel.replace("\\", "/").endswith("authorize/__init__.py"):
                continue
            try:
                body = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if cbm_re.search(body):
                errors.append(f"CBM marker in production path: {rel}")

    _scan_banned_production_symbols(REPO, errors)
    _scan_plugin_host_adapter(REPO, errors)
    _scan_uo_scope_vocab(REPO, errors)
    _scan_sqlite_product_engines(REPO, errors)

    if errors:
        print(f"check_runtime_graph: {len(errors)} issue(s)")
        for e in errors[:80]:
            print(f"  - {e}")
        if len(errors) > 80:
            print(f"  ... and {len(errors) - 80} more")
        return 1
    print("check_runtime_graph: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
