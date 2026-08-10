from __future__ import annotations

from testcase_agent.closure.certificate import validate


def _certificate() -> dict:
    return {
        "proof_scope": {
            "target_dimensions": ["Layout"],
            "relevant_functions": ["SetLayout"],
            "assignments": ["file.cpp:10"],
            "guards": ["file.cpp:8"],
        },
        "assumptions": [],
        "completeness_evidence": {
            "assignment_sites_complete": True,
            "call_closure_complete": True,
            "alias_state_exact": True,
            "macro_context_complete": True,
        },
        "counterexample_strategy": {"finite_D": "enumerate", "boundary_replay": "required"},
    }


def test_certificate_requires_complete_scope_and_evidence() -> None:
    assert validate({"certificate": _certificate()})["ok"] is True
    bad = _certificate()
    bad["completeness_evidence"]["alias_state_exact"] = False
    result = validate({"certificate": bad})
    assert result["ok"] is False
    assert "completeness_evidence.alias_state_exact_not_true" in result["errors"]
