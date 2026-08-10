# -*- coding: utf-8 -*-
"""A domain with no input must not certify as a domain with nothing wrong.

Every per-domain invariant forbids something: an excluded branch a witness
reached, an unsound grade, a soft-graded exclusion. When the domain loads no
view at all it has no rows, so each of those holds without checking anything and
the certificate reads "kernel ok" for an operator whose kernel view was never
built. That is how a gap=0 certificate was once issued on the host domain alone.
"""

from __future__ import annotations

from pathlib import Path

from testcase_agent.closure import report as REP


def test_missing_view_fails_the_establishment_check():
    chk = REP._domain_established(
        "kernel", {"source": {"kind": "missing", "reason": "no view built"}}
    )
    assert chk["ok"] is False
    assert "not_established" in chk["detail"]
    assert "vacuously" in chk["detail"], "must say why zero rows is not a pass"


def test_present_view_passes_and_records_where_it_came_from():
    chk = REP._domain_established(
        "tilingdata", {"source": {"kind": "yaml", "path": "/uo/views/tilingdata.yaml"}}
    )
    assert chk["ok"] is True
    assert "/uo/views/tilingdata.yaml" in chk["detail"]


def test_a_domain_that_reports_no_source_is_not_established():
    """Silence must not be an easier way to pass than saying "missing"."""
    assert REP._domain_established("kernel", {})["ok"] is False
    assert REP._domain_established("kernel", {"source": {}})["ok"] is False


def test_establishment_checks_gate_the_certificate():
    """Computing a check and then not reading it is the bug this prevents."""
    import inspect

    src = inspect.getsource(REP.certify_invariants)
    assert '"I0_kernel"' in src
    assert '"I0_tilingdata"' in src
    # And they must sit in the required tuple, not merely be computed.
    required_block = src.split("required = (")[1].split(")")[0]
    assert "I0_kernel" in required_block
    assert "I0_tilingdata" in required_block


def test_view_source_distinguishes_absent_from_present(tmp_path: Path):
    from testcase_agent.closure.kernel_domain import view_source

    assert view_source(None)["kind"] == "missing"
    assert view_source(tmp_path, "views/kernel.yaml")["kind"] == "missing"

    (tmp_path / "views").mkdir()
    (tmp_path / "views" / "kernel.yaml").write_text("branches: []\n", encoding="utf-8")
    got = view_source(tmp_path, "views/kernel.yaml")
    assert got["kind"] == "yaml"
    assert got["path"].endswith("kernel.yaml")


def test_db_projection_counts_as_a_source(tmp_path: Path):
    """The graph DB is the product authority; a view served from it is real."""
    from testcase_agent.closure.kernel_domain import view_source

    (tmp_path / "indexes").mkdir()
    (tmp_path / "indexes" / "kb_graph.sqlite").write_bytes(b"")
    assert view_source(tmp_path, "views/kernel.yaml")["kind"] == "db"
