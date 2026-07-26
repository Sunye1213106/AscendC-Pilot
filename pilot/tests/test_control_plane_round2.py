"""Round-2 control-plane closure: scope/uo_ready/lease/patch/resume/consistency/drift."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from ascendc_pilot.actions.runtime import finalize_action, prepare_action
from ascendc_pilot.authorize.lease import load_lease, revoke_active_lease
from ascendc_pilot.gates import (
    gate_adjudicate_llm_tasks,
    gate_detect_score_post,
    gate_extract_plan_subagent,
    gate_scope_receipt,
    gate_uo_ready,
)
from ascendc_pilot.paths import agent_root, ensure_agent_layout, runs_root, uo_root
from ascendc_pilot.runs import file_sha256, issue_receipt, verify_receipt
from ascendc_pilot.spec_hashes import workflow_spec_hash
from ascendc_pilot.state import load_state, save_state, start_workflow
from ascendc_pilot.workflows.consistency import check_all
from ascendc_pilot.run_resume import (
    _classify_receipts,
    _detect_dirty_actions,
    build_run_resume_summary,
    scrub_incomplete_on_continue,
)

RUN_TEST = "RUN_TEST"


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (dict, list)):
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    else:
        path.write_text(str(data), encoding="utf-8")


def _issue(project: Path, action_id: str, *, actor_id: str = "deterministic-uo-engine") -> Path:
    st = load_state(project)
    return issue_receipt(
        project,
        actor_type="deterministic_engine",
        actor_id=actor_id,
        action_id=action_id,
        workflow_spec_hash=workflow_spec_hash(str(st.get("workflow_id") or "uo-init")),
        input_hashes={"fixture": "in"},
        output_hashes={"fixture": "out"},
        checker_result={"ok": True},
        nonce=f"nonce-{action_id}",
        _internal=True,
    )


def _scope_doc(run_id: str, **extra: object) -> dict:
    doc = {
        "status": "confirmed",
        "run_id": run_id,
        "workflow_id": "uo-init",
        "action_id": "scope_confirmation",
        "confirmed_file_list": [{"path": "a.cpp"}],
    }
    doc.update(extra)
    return doc


def _mcp(uo: Path) -> None:
    cbm = uo / "cbm"
    cbm.mkdir(parents=True, exist_ok=True)
    (cbm / "index_meta.json").write_text(
        json.dumps({"indexed_via": "mcp", "cbm_project": "x"}),
        encoding="utf-8",
    )


# --- Scope ---


def test_scope_gate_rejects_other_run_receipt(tmp_path: Path) -> None:
    state = start_workflow(tmp_path, "uo-init", phase="scope", force_phase=True)
    run_id = str(state["run_id"])
    uo = uo_root(tmp_path)
    other = uo / "runs" / "OTHER_RUN" / "scope"
    other.mkdir(parents=True)
    _write(other / "scope_confirmed.yaml", _scope_doc("OTHER_RUN"))
    _mcp(uo)
    # Current run has no scope file — must not pick OTHER_RUN
    result = gate_scope_receipt(tmp_path, uo)
    assert result["ok"] is False
    assert result.get("error") == "SCOPE_RECEIPT_MISSING"


def test_scope_gate_rejects_missing_status(tmp_path: Path) -> None:
    state = start_workflow(tmp_path, "uo-init", phase="scope", force_phase=True)
    run_id = str(state["run_id"])
    uo = uo_root(tmp_path)
    scope = uo / "runs" / run_id / "scope"
    scope.mkdir(parents=True)
    _write(
        scope / "scope_confirmed.yaml",
        {
            "run_id": run_id,
            "workflow_id": "uo-init",
            "action_id": "scope_confirmation",
            "files": [{"path": "a.cpp"}],
        },
    )
    _mcp(uo)
    result = gate_scope_receipt(tmp_path, uo)
    assert result["ok"] is False
    assert result.get("error") == "SCOPE_RECEIPT_STATUS_MISSING"


def test_scope_gate_rejects_workflow_mismatch(tmp_path: Path) -> None:
    state = start_workflow(tmp_path, "uo-init", phase="scope", force_phase=True)
    run_id = str(state["run_id"])
    uo = uo_root(tmp_path)
    scope = uo / "runs" / run_id / "scope"
    scope.mkdir(parents=True)
    _write(scope / "scope_confirmed.yaml", _scope_doc(run_id, workflow_id="uo-update"))
    _mcp(uo)
    result = gate_scope_receipt(tmp_path, uo)
    assert result["ok"] is False
    assert result.get("error") == "SCOPE_RECEIPT_WORKFLOW_MISMATCH"


def test_scope_gate_accepts_current_run_confirmed(tmp_path: Path) -> None:
    state = start_workflow(tmp_path, "uo-init", phase="scope", force_phase=True)
    run_id = str(state["run_id"])
    uo = uo_root(tmp_path)
    scope = uo / "runs" / run_id / "scope"
    scope.mkdir(parents=True)
    _write(scope / "scope_confirmed.yaml", _scope_doc(run_id))
    _mcp(uo)
    result = gate_scope_receipt(tmp_path, uo)
    assert result["ok"] is True


def test_scope_gate_reports_manifest_run_id_mismatch(tmp_path: Path) -> None:
    state = start_workflow(tmp_path, "uo-init", phase="scope", force_phase=True)
    run_id = str(state["run_id"])
    uo = uo_root(tmp_path)
    uo.mkdir(parents=True, exist_ok=True)
    _write(uo / "manifest.yaml", {"current_run_id": "UO_RUN_orphaned"})
    orphan = uo / "runs" / "UO_RUN_orphaned" / "scope"
    orphan.mkdir(parents=True)
    _write(orphan / "scope_confirmed.yaml", _scope_doc("UO_RUN_orphaned"))
    _mcp(uo)
    result = gate_scope_receipt(tmp_path, uo)
    assert result["ok"] is False
    assert result.get("error") == "SCOPE_RECEIPT_RUN_MISMATCH"
    assert run_id in str(result.get("message") or "")
    assert result.get("manifest_run_id") == "UO_RUN_orphaned"


# --- UO ready ---


def test_uo_ready_rejects_empty_integrity_status(tmp_path: Path) -> None:
    uo = tmp_path / "uo"
    (uo / "checks").mkdir(parents=True)
    (uo / "manifest.yaml").write_text("version: 1\n", encoding="utf-8")
    (uo / "checks" / "integrity.yaml").write_text("version: 1\n", encoding="utf-8")
    assert gate_uo_ready(uo).get("ok") is False


def test_uo_ready_rejects_non_pass_status(tmp_path: Path) -> None:
    uo = tmp_path / "uo"
    (uo / "checks").mkdir(parents=True)
    (uo / "manifest.yaml").write_text("version: 1\n", encoding="utf-8")
    _write(uo / "checks" / "integrity.yaml", {"status": "ok"})
    assert gate_uo_ready(uo).get("ok") is False
    _write(uo / "checks" / "integrity.yaml", {"status": "reported"})
    assert gate_uo_ready(uo).get("ok") is False


def _seed_uo_ready_artifacts(uo: Path) -> None:
    """Minimal Host→KEY closed + fresh sqlite query index for strengthened uo_ready."""
    import json
    import sqlite3

    from uo.scripts.export_kb_graph import HASH_PATHS, SCHEMA_VERSION, _source_hashes

    (uo / "ir").mkdir(parents=True, exist_ok=True)
    (uo / "indexes").mkdir(parents=True, exist_ok=True)
    _write(
        uo / "ir" / "input_derivable.yaml",
        {"version": 1, "keys": {}, "stats": {"true": 0, "false": 0, "unsolved": 0}, "status": "closed"},
    )
    _write(uo / "ir" / "input_derivable_gaps.yaml", {"version": 1, "gaps": [], "status": "closed"})
    # Touch HASH_PATHS files so source hashes are stable empty digests.
    for rel in HASH_PATHS:
        p = uo / rel
        if not p.is_file():
            p.parent.mkdir(parents=True, exist_ok=True)
            if rel.endswith(".yaml"):
                _write(p, {"version": 1})
            else:
                p.write_text("", encoding="utf-8")
    hashes = _source_hashes(uo)
    db = uo / "indexes" / "kb_graph.sqlite"
    if db.exists():
        db.unlink()
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            ("source_hashes", json.dumps(hashes, sort_keys=True)),
        )
        conn.execute(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION),
        )
        conn.commit()


def test_uo_ready_accepts_exact_pass(tmp_path: Path) -> None:
    uo = tmp_path / "uo"
    (uo / "checks").mkdir(parents=True)
    (uo / "manifest.yaml").write_text("version: 1\n", encoding="utf-8")
    _write(uo / "checks" / "integrity.yaml", {"status": "pass"})
    _seed_uo_ready_artifacts(uo)
    result = gate_uo_ready(uo)
    assert result.get("ok") is True, result


# --- Finalize session/lease ---


def _prep_adjudicate(tmp_path: Path) -> dict:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", phase="extract", force_phase=True)
    for aid in ("detect_score_pre", "extract_plan", "detect_score_post"):
        actor = "uo-semantic-resolve" if aid == "extract_plan" else "deterministic-uo-engine"
        _issue(tmp_path, aid, actor_id=actor)
    uo = uo_root(tmp_path)
    # Keep one post-semantic LLM-routed open task so adjudicate stays the active step
    # (empty tasks can auto-skip to apply_semantic_patch and break re-prepare tests).
    st = load_state(tmp_path) or {}
    run_id = str(st.get("run_id") or RUN_TEST)
    _write(
        uo / "ir" / "llm_tasks.yaml",
        {
            "version": 1,
            "total_semantic_batches": 0,
            "artifact_identity": {"run_id": run_id, "workflow_id": "uo-init"},
            "tasks": [
                {
                    "task_id": "TASK_OPEN_BC",
                    "status": "open",
                    "task_status": "open",
                    "run_id": run_id,
                    "workflow_id": "uo-init",
                    "score_phase": "post_semantic",
                    "checkpoint": "extract.post_semantic",
                    "eligible_for_adjudication": True,
                    "route": "uo-semantic-resolve",
                    "triage_category": "true_multi_candidate",
                    "resolution_class": "uo_blocking",
                    "blocking": True,
                    "severity": "blocking",
                    "semantic_status": "unresolved",
                    "type": "entrypoint_dispatch_bind",
                    "target": "edge_x",
                    "source_snapshot_hash": "snap_bc",
                    "candidate_set_hash": "cset_bc",
                    "candidates": [
                        {
                            "id": "cand_1",
                            "file_path": "op_host/a.cpp",
                            "symbol_ref": "Foo",
                            "snippet": "Foo()",
                            "start_line": 1,
                        },
                        {
                            "id": "cand_2",
                            "file_path": "op_host/b.cpp",
                            "symbol_ref": "Bar",
                            "snippet": "Bar()",
                            "start_line": 2,
                        },
                    ],
                    "allowed_actions": ["accept_edge", "reject_edge", "choose_one", "mark_missing"],
                }
            ],
        },
    )
    prep = prepare_action(tmp_path, "adjudicate_llm_tasks")
    assert prep["ok"] is True, prep
    return prep


def test_finalize_rejects_stale_prepare_nonce(tmp_path: Path) -> None:
    prep = _prep_adjudicate(tmp_path)
    st = load_state(tmp_path)
    sdir = Path(prep["session_dir"])
    session = yaml.safe_load((sdir / "session.yaml").read_text(encoding="utf-8"))
    session["prepare_nonce"] = "stale-nonce"
    _write(sdir / "session.yaml", session)
    fin = finalize_action(tmp_path, "adjudicate_llm_tasks")
    assert fin["ok"] is False
    assert fin.get("error") == "SESSION_NONCE_MISMATCH"


def test_finalize_rejects_replaced_active_action(tmp_path: Path) -> None:
    prep = _prep_adjudicate(tmp_path)
    active_path = agent_root(tmp_path) / "state" / "active_action.yaml"
    active = yaml.safe_load(active_path.read_text(encoding="utf-8"))
    active["prepare_nonce"] = "other-nonce"
    _write(active_path, active)
    fin = finalize_action(tmp_path, "adjudicate_llm_tasks")
    assert fin["ok"] is False
    assert fin.get("error") == "SESSION_NONCE_MISMATCH"


def test_finalize_rejects_revoked_lease(tmp_path: Path) -> None:
    prep = _prep_adjudicate(tmp_path)
    revoke_active_lease(tmp_path, reason="test", touch_active_action=False)
    fin = finalize_action(tmp_path, "adjudicate_llm_tasks")
    assert fin["ok"] is False
    assert fin.get("error") == "LEASE_REVOKED"


def test_finalize_rejects_lease_action_mismatch(tmp_path: Path) -> None:
    prep = _prep_adjudicate(tmp_path)
    lease = load_lease(tmp_path)
    lease["action_id"] = "apply_semantic_patch"
    _write(agent_root(tmp_path) / "state" / "action_lease.yaml", lease)
    fin = finalize_action(tmp_path, "adjudicate_llm_tasks")
    assert fin["ok"] is False
    # Tampered lease may surface as action mismatch or revoked — both fail-closed.
    assert fin.get("error") in {"LEASE_ACTION_MISMATCH", "LEASE_REVOKED"}


def test_second_prepare_invalidates_first_session(tmp_path: Path) -> None:
    prep1 = _prep_adjudicate(tmp_path)
    sdir1 = Path(prep1["session_dir"])
    nonce1 = prep1["prepare_nonce"]
    # Second prepare of same action replaces active + lease
    prep2 = prepare_action(tmp_path, "adjudicate_llm_tasks")
    assert prep2["ok"] is True
    assert prep2["prepare_nonce"] != nonce1
    # Restore first session file content but keep new active — finalize first session fails
    # Actually session path is same action dir — second prepare overwrote session.yaml.
    # Write old nonce back into session while active has new nonce.
    session = yaml.safe_load((sdir1 / "session.yaml").read_text(encoding="utf-8"))
    session["prepare_nonce"] = nonce1
    session["nonce"] = nonce1
    session["lease_id"] = prep1["lease_id"]
    _write(sdir1 / "session.yaml", session)
    fin = finalize_action(tmp_path, "adjudicate_llm_tasks")
    assert fin["ok"] is False
    assert fin.get("error") in {"SESSION_NONCE_MISMATCH", "SESSION_LEASE_MISMATCH"}


# --- Semantic patches ---


def _uo_with_open_task(tmp_path: Path, *, cand: str = "cand_1") -> Path:
    uo = tmp_path / "uo"
    (uo / "ir").mkdir(parents=True)
    _write(uo / "manifest.yaml", {"current_run_id": RUN_TEST, "workflow_id": "uo-init"})
    _write(
        uo / "ir" / "llm_tasks.yaml",
        {
            "version": 1,
            "artifact_identity": {"run_id": RUN_TEST, "workflow_id": "uo-init"},
            "active_run_id": RUN_TEST,
            "total_semantic_batches": 0,
            "tasks": [
                {
                    "task_id": "t1",
                    "run_id": RUN_TEST,
                    "workflow_id": "uo-init",
                    "status": "open",
                    "task_status": "open",
                    "severity": "blocking",
                    "blocking": True,
                    "semantic_status": "unresolved",
                    "type": "choose_edge",
                    "candidates": [{"id": cand}],
                    "allowed_actions": ["choose_one", "accept_edge", "mark_missing"],
                    "source_snapshot_hash": "snap1",
                    "candidate_set_hash": "cset1",
                }
            ],
        },
    )
    return uo


def test_adjudicate_gate_rejects_stale_snapshot(tmp_path: Path, monkeypatch) -> None:
    import sys

    eng = Path(__file__).resolve().parents[2] / "engines" / "understand-operator"
    if str(eng) not in sys.path:
        sys.path.insert(0, str(eng))
    uo = _uo_with_open_task(tmp_path)
    _write(
        uo / "ir" / "semantic_patches.yaml",
        {
            "patches": [
                {
                    "task_id": "t1",
                    "run_id": RUN_TEST,
                    "action": "accept_edge",
                    "accepted_candidate_ids": ["cand_1"],
                    "rejected_candidate_ids": [],
                    "source_snapshot_hash": "snap1",
                    "candidate_set_hash": "cset1",
                }
            ]
        },
    )
    monkeypatch.setattr(
        "uo.scripts.evidence_score._source_snapshot_hash",
        lambda _uo, run_id=None, **kw: "OTHER",
    )
    result = gate_adjudicate_llm_tasks(uo)
    assert result["ok"] is False


def test_adjudicate_gate_rejects_candidate_out_of_window(tmp_path: Path, monkeypatch) -> None:
    import sys

    eng = Path(__file__).resolve().parents[2] / "engines" / "understand-operator"
    if str(eng) not in sys.path:
        sys.path.insert(0, str(eng))
    uo = _uo_with_open_task(tmp_path)
    _write(
        uo / "ir" / "semantic_patches.yaml",
        {
            "patches": [
                {
                    "task_id": "t1",
                    "run_id": RUN_TEST,
                    "action": "accept_edge",
                    "accepted_candidate_ids": ["cand_BAD"],
                    "rejected_candidate_ids": [],
                    "source_snapshot_hash": "snap1",
                    "candidate_set_hash": "cset1",
                }
            ]
        },
    )
    monkeypatch.setattr("uo.scripts.evidence_score._source_snapshot_hash", lambda _uo, run_id=None, **kw: "snap1")
    result = gate_adjudicate_llm_tasks(uo)
    assert result["ok"] is False
    errs = result.get("validation_errors") or []
    assert any(e.get("error") == "candidate_out_of_window" for e in errs)


def test_adjudicate_gate_rejects_unknown_task(tmp_path: Path, monkeypatch) -> None:
    import sys

    eng = Path(__file__).resolve().parents[2] / "engines" / "understand-operator"
    if str(eng) not in sys.path:
        sys.path.insert(0, str(eng))
    uo = _uo_with_open_task(tmp_path)
    _write(
        uo / "ir" / "semantic_patches.yaml",
        {
            "patches": [
                {
                    "task_id": "unknown_task",
                    "run_id": RUN_TEST,
                    "action": "accept_edge",
                    "accepted_candidate_ids": ["cand_1"],
                    "source_snapshot_hash": "snap1",
                    "candidate_set_hash": "cset1",
                }
            ]
        },
    )
    monkeypatch.setattr("uo.scripts.evidence_score._source_snapshot_hash", lambda _uo, run_id=None, **kw: "snap1")
    result = gate_adjudicate_llm_tasks(uo)
    assert result["ok"] is False


def test_adjudicate_gate_and_apply_share_validation(tmp_path: Path, monkeypatch) -> None:
    import sys

    eng = Path(__file__).resolve().parents[2] / "engines" / "understand-operator"
    if str(eng) not in sys.path:
        sys.path.insert(0, str(eng))
    from uo.scripts.llm_tasks import validate_semantic_patch_set

    uo = _uo_with_open_task(tmp_path)
    patches = [
        {
            "task_id": "t1",
            "run_id": RUN_TEST,
            "action": "accept_edge",
            "accepted_candidate_ids": ["cand_1"],
            "rejected_candidate_ids": [],
            "source_snapshot_hash": "snap1",
            "candidate_set_hash": "cset1",
        }
    ]
    _write(
        uo / "ir" / "semantic_patches.yaml",
        {"artifact_identity": {"run_id": RUN_TEST, "workflow_id": "uo-init"}, "patches": patches},
    )
    monkeypatch.setattr("uo.scripts.evidence_score._source_snapshot_hash", lambda _uo, run_id=None, **kw: "snap1")
    gate = gate_adjudicate_llm_tasks(uo)
    core = validate_semantic_patch_set(
        uo, patches, "snap1", current_run_id=RUN_TEST, require_full_coverage=True, mutate=False
    )
    assert gate["ok"] is True
    assert core["ok"] is True


# --- Resume ---


def test_resume_rejects_tampered_receipt(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    path = _issue(tmp_path, "prepare_layout")
    text = path.read_text(encoding="utf-8")
    # Tamper checker_result / body without resigning
    data = yaml.safe_load(text)
    data["checker_result"] = {"ok": True, "tampered": True}
    data["hmac"] = "deadbeef"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    classified = _classify_receipts(tmp_path, load_state(tmp_path)["run_id"])
    assert "prepare_layout" not in classified["verified_receipts"]
    assert "prepare_layout" in classified["invalid_receipts"]
    summary = build_run_resume_summary(tmp_path, workflow_id="uo-init")
    assert "prepare_layout" in summary["invalid_receipts"]


def test_resume_rejects_wrong_run_receipt(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    old = load_state(tmp_path)["run_id"]
    _issue(tmp_path, "prepare_layout")
    start_workflow(tmp_path, "uo-init")
    new = load_state(tmp_path)["run_id"]
    assert new != old
    # Copy old receipt into new run dir with wrong run_id
    old_base = runs_root(tmp_path) / old / "subagents"
    new_base = runs_root(tmp_path) / new / "subagents"
    new_base.mkdir(parents=True, exist_ok=True)
    for src in old_base.glob("*.yaml"):
        data = yaml.safe_load(src.read_text(encoding="utf-8"))
        shutil.copy2(src, new_base / src.name)
    classified = _classify_receipts(tmp_path, new)
    assert "prepare_layout" not in classified["verified_receipts"]


def test_invalid_receipt_action_is_scrubbed(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", phase="extract", force_phase=True)
    st = load_state(tmp_path)
    run_id = st["run_id"]
    # Write a fake invalid receipt file
    base = runs_root(tmp_path) / run_id / "subagents"
    base.mkdir(parents=True, exist_ok=True)
    _write(
        base / "fake_extract.yaml",
        {
            "issued_by": "pilot",
            "action_id": "extract_plan",
            "run_id": run_id,
            "checker_result": {"ok": True},
            "hmac": "invalid",
        },
    )
    uo = uo_root(tmp_path)
    _write(uo / "ir" / "extract_plan.yaml", {"version": 1, "writers": []})
    dirty = _detect_dirty_actions(tmp_path, run_id, "uo-init")
    assert "extract_plan" in dirty
    scrub = scrub_incomplete_on_continue(tmp_path)
    assert "extract_plan" in scrub.get("scrubbed_actions", [])


# --- Consistency ---


def test_consistency_rejects_zero_contract_write_coverage(tmp_path: Path) -> None:
    from ascendc_pilot.workflows.specs import WORKFLOWS

    # Inject a fake producer with contract outside agent scopes
    fake = {
        "slash": "/fake",
        "phases": ["p"],
        "pipelines": {"p": ["fake_producer"]},
        "actions": [
            {
                "id": "fake_producer",
                "role_id": "producer",
                "agent_id": "uo-semantic-resolve",
                "output_contract_id": "integrity-v1",  # uo/checks/... not in semantic-resolve scopes
                "action_method_id": "uo-init/extract-plan",
                "task_prompt_id": "uo/extract-plan",
                "policy_ids": [],
                "capability_ids": [],
            }
        ],
    }
    # Use real agent file from repo via check against real root but injected workflow
    repo = Path(__file__).resolve().parents[2]
    # Copy agents into tmp so load_agent_meta can find uo-semantic-resolve scopes
    shutil.copytree(repo / "agents", tmp_path / "agents")
    (tmp_path / "skills" / "actions" / "uo-init" / "extract-plan").mkdir(parents=True)
    (tmp_path / "skills" / "actions" / "uo-init" / "extract-plan" / "METHOD.md").write_text(
        "# m\n", encoding="utf-8"
    )
    (tmp_path / "prompts" / "tasks" / "uo").mkdir(parents=True)
    (tmp_path / "prompts" / "tasks" / "uo" / "extract-plan.md").write_text("# p\n", encoding="utf-8")
    errors = check_all(tmp_path, workflows={"fake-wf": fake})
    assert any("no writable output path for contract" in e for e in errors), errors


def test_consistency_accepts_explicit_staged_merge() -> None:
    repo = Path(__file__).resolve().parents[2]
    errors = check_all(repo)
    assert not any("semantic_bind" in e and "no writable" in e for e in errors), errors
    # staged declaration present in Spec
    from ascendc_pilot.workflows.specs import WORKFLOWS

    bind = next(a for a in WORKFLOWS["tg-init"]["actions"] if a["id"] == "semantic_bind")
    assert bind.get("output_mode") == "staged"
    assert bind.get("staging_contract_id") == "semantic-bind-patch-v1"


def test_generated_drift_fails_contract_check(tmp_path: Path, monkeypatch) -> None:
    import sys

    repo = Path(__file__).resolve().parents[2]
    scripts = repo / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from compose_runtime import check_generated_drift

    # Tamper a committed generated file temporarily then restore
    target = repo / "generated" / "opencode" / "agents" / "ascendc-pilot.md"
    if not target.is_file():
        return
    original = target.read_text(encoding="utf-8")
    try:
        target.write_text(original + "\n# DRIFT_MARKER\n", encoding="utf-8")
        errors = check_generated_drift(repo, hosts=["opencode"])
        assert any(e.startswith("GENERATED_DRIFT:") for e in errors), errors
    finally:
        target.write_text(original, encoding="utf-8")


# --- Existing bugs ---


def test_detect_score_post_requires_plan_and_host(tmp_path: Path) -> None:
    uo = tmp_path / "uo"
    (uo / "ir").mkdir(parents=True)
    _write(uo / "ir" / "score_report_post.yaml", {"version": 1})
    # host only — must fail
    _write(uo / "ir" / "host_subgraph.yaml", {"version": 1})
    r = gate_detect_score_post(uo)
    assert r["ok"] is False
    assert "extract_plan.yaml" in (r.get("missing") or [])
    _write(uo / "ir" / "extract_plan.yaml", {"version": 1})
    # plan+host without kernel still fail (shared Engine/Gate contract)
    r2 = gate_detect_score_post(uo)
    assert r2["ok"] is False
    assert "kernel_subgraph.yaml" in (r2.get("missing") or [])
    _write(uo / "ir" / "kernel_subgraph.yaml", {"version": 1})
    # Post score also requires triage artifact (Phase A).
    r3 = gate_detect_score_post(uo)
    assert r3["ok"] is False
    assert "semantic_task_triage.yaml" in (r3.get("missing") or [])
    _write(uo / "ir" / "semantic_task_triage.yaml", {"version": 1, "tasks": [], "stats": {}})
    assert gate_detect_score_post(uo).get("ok") is True


def test_extract_plan_requires_actor_and_candidate_hash(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    state = start_workflow(tmp_path, "uo-init")
    uo = uo_root(tmp_path)
    cand = uo / "ir" / "extract_plan_candidates.yaml"
    _write(cand, "version: 1\nstatus: candidates\nok: true\n")
    _write(uo / "ir" / "entrypoint_graph.yaml", "version: 2\nnodes: []\n")
    _write(uo / "ir" / "operator_boundary.yaml", "version: 1\nok: true\n")
    # Missing actor/hash/run
    _write(uo / "ir" / "extract_plan.yaml", "version: 1\nwriters: []\n")
    r = gate_extract_plan_subagent(tmp_path, uo)
    assert r["ok"] is False
    sha = file_sha256(cand)
    _write(
        uo / "ir" / "extract_plan.yaml",
        {
            "version": 1,
            "actor_id": "uo-semantic-resolve",
            "run_id": state["run_id"],
            "workflow_id": "uo-init",
            "candidates_sha256": sha,
            "writers": [],
        },
    )
    assert gate_extract_plan_subagent(tmp_path, uo).get("ok") is True
