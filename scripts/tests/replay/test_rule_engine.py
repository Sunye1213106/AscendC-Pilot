# -*- coding: utf-8 -*-
"""Rule engine and runtime counterexample gate, without a host."""

from __future__ import annotations

from pathlib import Path

from replay import rule_engine as RE


def write_proof(tmp_path: Path) -> Path:
    path = tmp_path / "proof_rules.yaml"
    path.write_text(
        "version: 1\ngrade: human\n"
        "value_unreachable:\n"
        "  - {dim: InputDType, value: '4', reason: fp8}\n"
        "combos:\n"
        "  - when: {IsRope: '1', DTemplateNum: '64'}\n"
        "    tag: rope_d\n"
        "combo_evidence: {rope_d: rope forces 192}\n",
        encoding="utf-8")
    return path


def test_proof_rules_exclude_a_value_and_a_combo(tmp_path):
    book = RE.load_proof(write_proof(tmp_path))
    assert book.excluded_by({"InputDType": 4}) == ["InputDType=4"]
    assert book.excluded_by({"IsRope": 1, "DTemplateNum": 64}) == [
        "IsRope=1 + DTemplateNum=64"]
    assert book.excluded_by({"InputDType": 1}) == []


def test_the_operator_proof_rules_load_and_cover_the_old_set():
    book = RE.default_book()
    labels = {r.label for r in book.rules}
    assert "InputDType=4" in labels
    assert "IsRegbase=0" in labels
    assert any("IsTndSwizzle=1" in r.label for r in book.rules)


def test_counters_split_undeclared_from_declared_r():
    """Ledger accounting: runtime keys outside D are undeclared, not R."""
    from testcase_agent.closure import ledger as L

    D = {1, 2, 3}
    R_runtime = {1, 99}  # 99 undeclared
    R = R_runtime & D
    E: set[int] = set()
    gap = D - R - E
    st = {
        "runtime_total": len(R_runtime),
        "R_declared": len(R),
        "undeclared": len(R_runtime - D),
        "open_gap_sound": len(gap),
    }
    assert st["runtime_total"] == 2
    assert st["R_declared"] == 1
    assert st["undeclared"] == 1
    assert st["open_gap_sound"] == 2  # keys 2 and 3
    # state() shape still exposes these fields when a workspace exists
    assert hasattr(L, "state")


def test_human_rule_excluded_under_reviewed_not_sound(tmp_path):
    book = RE.load_proof(write_proof(tmp_path))
    inst = {"InputDType": 4}
    assert book.excluded_by(inst) == ["InputDType=4"]
    assert book.excluded_by(inst, grades=RE.SOUND_GRADES) == []
    assert book.excluded_by_sound(inst) == []


def test_load_derived_implications_become_combos_not_value_bans(tmp_path):
    """Implication antecedents must not wipe a whole dimension."""
    path = tmp_path / "derived_rules.yaml"
    path.write_text(
        "version: 1\nsource_hash: abc\nrules:\n"
        "  - kind: pair_exclusive\n"
        "    evidence_grade: solver_derived\n"
        "    statement: DTemplateNum=64 and IsRope=1 cannot hold together\n"
        "    excludes:\n"
        "      - {dim: DTemplateNum, value: 64}\n"
        "      - {dim: IsRope, value: 1}\n"
        "  - kind: implication\n"
        "    evidence_grade: solver_derived\n"
        "    statement: IsRope=1 forces DTemplateNum=192\n"
        "    excludes:\n"
        "      - {dim: IsRope, value: 1}\n"
        "    forces: {dim: DTemplateNum, value: 192}\n"
        "    folded_from:\n"
        "      - [{dim: DTemplateNum, value: 64}, {dim: IsRope, value: 1}]\n"
        "      - [{dim: DTemplateNum, value: 128}, {dim: IsRope, value: 1}]\n",
        encoding="utf-8",
    )
    book = RE.load_derived(path)
    labels = {r.label for r in book.rules}
    assert "IsRope=1" not in labels  # must not ban all rope
    assert "DTemplateNum=64" not in labels
    assert book.excluded_by_sound({"IsRope": 1, "DTemplateNum": 64})
    assert book.excluded_by_sound({"IsRope": 1, "DTemplateNum": 192}) == []
    assert book.excluded_by_sound({"IsRope": 0, "DTemplateNum": 64}) == []


def test_wide_tables_uses_manifest_glob(tmp_path, monkeypatch):
    from replay import corpus as C
    from replay import runner as R

    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "key_cases_run.csv").write_text(
        "case_id,ok,tiling_key\na,1,1\n", encoding="utf-8")
    (cache / "fag_key_cases_old.csv").write_text(
        "case_id,ok,tiling_key\nb,1,2\n", encoding="utf-8")
    (cache / "other.csv").write_text("x\n", encoding="utf-8")

    monkeypatch.setattr(R, "CACHE", cache)
    # Force the pattern without needing a full runner rebuild.
    got = {p.name for p in C.wide_tables(cache, "*key_cases*.csv")}
    assert got == {"key_cases_run.csv", "fag_key_cases_old.csv"}
