"""Runtime-context golden: identity + hash + tokens, not full-text snapshots."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ascendc_pilot.actions.method_bundle import parse_declared_refs
from ascendc_pilot.workflows import WORKFLOWS

REPO = Path(__file__).resolve().parents[2]
SKILLS = REPO / "skills"

_LLM_MODES = {"subagent", "primary_interactive", "primary_review"}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _llm_actions() -> list[tuple[str, dict]]:
    rows: list[tuple[str, dict]] = []
    for wid, meta in WORKFLOWS.items():
        if not isinstance(meta, dict) or meta.get("reserved"):
            continue
        for action in meta.get("actions") or []:
            if str(action.get("execution_mode") or "") not in _LLM_MODES:
                continue
            rows.append((wid, action))
    return rows


def test_runtime_context_identity_and_pollution() -> None:
    seen: list[dict] = []
    for wid, action in _llm_actions():
        sid = str(action.get("skill_id") or "").rsplit("/", 1)[-1]
        if not sid:
            continue
        skill_md = SKILLS / sid / "SKILL.md"
        assert skill_md.is_file(), f"{wid}/{action.get('id')} missing {sid}/SKILL.md"
        skill_text = skill_md.read_text(encoding="utf-8")
        refs, unauth = parse_declared_refs(skill_text, current_skill_id=sid)
        assert unauth == [], f"{sid} foreign refs {unauth}"
        row = {
            "action": f"{wid}/{action.get('id')}",
            "skill": sid,
            "skill_sha256": _sha(skill_text),
            "skill_tokens": _tokens(skill_text),
            "available_refs": [],
        }
        bodies = skill_text
        for owner, rel in refs:
            src = SKILLS / owner / "references" / rel
            assert src.is_file(), f"{sid} missing {owner}/{rel}"
            body = src.read_text(encoding="utf-8")
            bodies += "\n" + body
            row["available_refs"].append(
                {
                    "id": f"{owner}/{rel}",
                    "sha256": _sha(body),
                    "tokens": _tokens(body),
                }
            )
        seen.append(row)
        if sid == "bind-columns":
            assert "modes.precision" not in bodies
            assert "performance-testing" not in bodies
            assert "`references/construction-gotchas.md`" not in bodies
        if sid == "bind-harness":
            assert "api_arg" not in bodies
            assert "script_meta" not in bodies
        if sid == "analyze-round":
            assert "`references/search.md`" not in bodies
            assert "`references/closure-safety.md`" not in bodies
        if sid == "bind-init":
            assert row["available_refs"] == []
    assert seen, "expected LLM actions"
    assert all(r["skill_tokens"] > 0 for r in seen)
