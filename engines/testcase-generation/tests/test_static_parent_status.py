# -*- coding: utf-8 -*-

from __future__ import annotations


def test_static_parent_status_three_way(monkeypatch):
    from testcase_agent.closure import features as F
    from testcase_agent.closure import models as M

    monkeypatch.setattr(
        F,
        "_static_parents_table",
        lambda: {"PresentDim": ["a", "b"], "EmptyDim": []},
    )
    assert F.static_parent_status("PresentDim") == "present"
    assert F.static_parent_status("EmptyDim") == "explicit_empty"
    assert F.static_parent_status("MissingDim") == "missing"
    assert F.static_parents("MissingDim", ["a", "b", "c"]) == []
    assert F.static_parents("EmptyDim", ["a", "b", "c"]) == []
    assert F.static_parents("PresentDim", ["a", "c"]) == ["a"]

    assert M._verdict(0.5, 0.5, 0.9, parent_status="missing") == "kb_parent_spec_missing"
    assert M._verdict(0.5, 0.5, 0.9, parent_status="present") == "static_parents_incomplete"
    assert M._verdict(0.5, 0.88, 0.9, parent_status="present") == "skeleton_usable"
