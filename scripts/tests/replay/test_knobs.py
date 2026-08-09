# -*- coding: utf-8 -*-
"""Write-side Binding duality: Case ← desired variable value."""

from __future__ import annotations

from replay import inputs as I
from replay import obligations as O
from replay.bridge_spec import Binding
from replay.knobs import write_binding


def test_pse_presence_write_turns_pse_on():
    got = write_binding(
        I.Case(),
        Binding(var="VAR_OPT_PSE_SHIFT", root="OPTIONAL_INPUT_PRESENCE",
                kind="optional_presence", operand="pse_shift"),
        True,
    )
    assert got is not None and got.pse is True


def test_drop_presence_write_lowers_keep_prob():
    got = write_binding(
        I.Case(),
        Binding(var="VAR_OPT_DROP_MASK", root="OPTIONAL_INPUT_PRESENCE",
                kind="optional_presence", operand="drop_mask"),
        True,
    )
    assert got is not None and got.keep_prob < 1.0


def test_rope_presence_write_sets_rope_and_d():
    got = write_binding(
        I.Case(),
        Binding(var="VAR_OPT_QUERY_ROPE_IDX", root="OPTIONAL_INPUT_PRESENCE",
                kind="optional_presence", operand="query_rope"),
        True,
    )
    assert got is not None and got.rope and got.d == I.ROPE_TOTAL_D


def test_atten_mask_absence_clears_mask():
    got = write_binding(
        I.Case(atten_mask="ss"),
        Binding(var="VAR_OPT_ATTEN_MASK", root="OPTIONAL_INPUT_PRESENCE",
                kind="optional_presence", operand="atten_mask"),
        False,
    )
    assert got is not None and got.atten_mask == "none"


def test_dtype_write_accepts_name_and_code():
    b = Binding(var="VAR_DTYPE_QUERY", root="INPUT_DTYPE",
                kind="tensor_dtype", operand="query")
    by_name = write_binding(I.Case(), b, "BF16")
    by_code = write_binding(I.Case(), b, I.DT["BF16"])
    assert by_name is not None and by_name.dtype == "BF16"
    assert by_code is not None and by_code.dtype == "BF16"


def test_deterministic_context_write():
    got = write_binding(
        I.Case(),
        Binding(var="VAR_SESSION_DETERMINISTIC", root="SESSION_OPTION",
                kind="context"),
        True,
    )
    assert got is not None and got.deterministic == 1


def test_from_bindings_covers_presence_dims_without_hints():
    """Named knobs work even when special_generators would have intercepted."""
    import pytest
    from replay.package_data import active_package_dir, load_yaml, repo_root

    pkg = active_package_dir(repo_root())
    hints = load_yaml("search_hints.yaml", refresh=True) or {}
    has_named = bool(hints.get("named_bindings"))
    has_bridge = (pkg / "bridge_spec.yaml").is_file()
    if not has_named and not has_bridge:
        pytest.skip(
            "needs search_hints.named_bindings or bridge_spec "
            "(run export_adapter_pack)"
        )
    base = I.Case()
    assert any(c.pse for c in O._from_bindings(base, "IsPse", "1"))
    assert any(c.keep_prob < 1 for c in O._from_bindings(base, "IsDrop", "1"))
    assert any(c.rope for c in O._from_bindings(base, "IsRope", "1"))
    assert any(c.atten_mask != "none"
               for c in O._from_bindings(base, "IsAttenMask", "1"))
    assert O._from_bindings(base, "IsDNoEqual", "1")
    assert O._from_bindings(base, "S1TemplateNum", "128")
    assert O._from_bindings(base, "S2TemplateNum", "128")
    assert O._from_bindings(base, "DTemplateNum", "128")
    assert O._from_bindings(base, "IsNEqual", "0")
    # Host-state stays empty.
    assert O._from_bindings(base, "SplitAxis", "5") == []
