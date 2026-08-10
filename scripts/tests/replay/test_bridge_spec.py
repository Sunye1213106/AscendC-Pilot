# -*- coding: utf-8 -*-
"""The spec, and what it refuses to leave unsaid.

The old bridge asserted a mapping in the forward direction and had no way to
express "the derivation reads this and nothing sets it" -- that came out as an
absent dictionary key, which an evaluator cannot tell from a variable nobody
modelled. Most of these tests are about that distinction surviving.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from replay import bridge_spec as S
from replay import inputs as I
from replay.adapter import ADAPTER
from replay.materialized import (
    ROLE_INPUT, ROLE_OUTPUT, ContextValue, MaterializedAttr, MaterializedCase,
    MaterializedTensor, default_spec)


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "bridge_spec.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def case(**kw) -> MaterializedCase:
    base = dict(
        case_id="c",
        inputs=(MaterializedTensor(name="query", present=True, dims=(2, 8, 4),
                                   dtype=27),
                MaterializedTensor(name="seq_len", present=True, dims=(3,),
                                   values=(10, 20, 15), read_by_value=True),
                MaterializedTensor(name="atten_mask", present=False)),
        outputs=(MaterializedTensor(name="dq", present=True, dims=(2, 8),
                                    role=ROLE_OUTPUT),),
        attrs=(MaterializedAttr(name="head_num", kind="i", value=8),),
        context=(ContextValue("VAR_SESSION_DETERMINISTIC", True),),
    )
    base.update(kw)
    return MaterializedCase(**base)


# --- what the file has to say -------------------------------------------


def test_a_variable_bound_to_nothing_needs_a_reason(tmp_path):
    """An unexplained gap is the thing this file exists to prevent."""
    path = write(tmp_path, """
        operator: X
        unbound:
          VAR_TDF_THING: {root: TILING_DATA}
        """)

    with pytest.raises(S.SpecError, match="unbound with no reason"):
        S.BridgeSpec.load(path)


def test_a_variable_cannot_be_both_bound_and_unbound(tmp_path):
    path = write(tmp_path, """
        operator: X
        bindings:
          VAR_ATTR_N: {root: ATTRIBUTE, kind: attr, attr: n}
        unbound:
          VAR_ATTR_N: {root: ATTRIBUTE, reason: cannot decide}
        """)

    with pytest.raises(S.SpecError, match="both bound and unbound"):
        S.BridgeSpec.load(path)


def test_a_reading_nobody_implements_is_refused(tmp_path):
    path = write(tmp_path, """
        operator: X
        bindings:
          VAR_X: {root: INPUT_SHAPE, kind: tensor_vibes, tensor: query}
        """)

    with pytest.raises(S.SpecError, match="tensor_vibes"):
        S.BridgeSpec.load(path)


def test_an_axis_reading_has_to_name_its_axis(tmp_path):
    path = write(tmp_path, """
        operator: X
        bindings:
          VAR_X: {root: INPUT_SHAPE, kind: tensor_axis, tensor: query}
        """)

    with pytest.raises(S.SpecError, match="reads an axis and names none"):
        S.BridgeSpec.load(path)


# --- reading a case ------------------------------------------------------


def bind_one(kind: str, operand: str, **kw):
    spec = S.BridgeSpec(operator="X", arch="a", bindings=(
        S.Binding(var="V", root="R", kind=kind, operand=operand, **kw),))
    return S.bind(spec, case())["V"]


def test_each_reading_takes_the_quantity_it_names():
    assert bind_one(S.TENSOR_NUMEL, "query") == 64
    assert bind_one(S.TENSOR_RANK, "query") == 3
    assert bind_one(S.TENSOR_AXIS, "query", axis=1) == 8
    assert bind_one(S.TENSOR_AXIS_LAST, "query") == 4
    assert bind_one(S.TENSOR_DTYPE, "query") == 27
    assert bind_one(S.TENSOR_PRESENCE, "query") is True


def test_the_value_readings_read_the_contents_not_the_extent():
    assert bind_one(S.TENSOR_VALUES, "seq_len") == [10, 20, 15]
    assert bind_one(S.TENSOR_VALUE_LAST, "seq_len") == 15
    assert bind_one(S.TENSOR_VALUE_SECOND, "seq_len") == 20
    assert bind_one(S.TENSOR_VALUE_MAX, "seq_len") == 20


def test_an_absent_tensor_answers_none_and_not_zero():
    """Guards test the pointer before the extent, so folding the two flips
    the branch that handles a missing optional."""
    assert bind_one(S.TENSOR_PRESENCE, "atten_mask") is False
    assert bind_one(S.TENSOR_NUMEL, "atten_mask") is None
    assert bind_one(S.TENSOR_RANK, "atten_mask") is None
    assert bind_one(S.TENSOR_DTYPE, "atten_mask") is None


def test_an_axis_past_the_end_is_a_question_with_no_answer():
    assert bind_one(S.TENSOR_AXIS, "query", axis=7) is None


def test_an_output_is_readable_too():
    assert bind_one(S.TENSOR_NUMEL, "dq") == 16


def test_a_name_spelled_differently_is_still_the_same_tensor():
    """The definition says `seq_len`, a case might say `seqLen`."""
    spec = S.BridgeSpec(operator="X", arch="a", bindings=(
        S.Binding(var="V", root="R", kind=S.TENSOR_VALUE_LAST,
                  operand="seq_len"),))
    renamed = case(inputs=(MaterializedTensor(
        name="seqLen", present=True, dims=(3,), values=(10, 20, 15),
        read_by_value=True),))

    assert S.bind(spec, renamed)["V"] == 15


def test_a_binding_the_case_cannot_answer_is_an_error_not_a_gap():
    """The spec and the generator disagreeing about the signature is a break,
    and a missing key would have looked like an unknown."""
    spec = S.BridgeSpec(operator="X", arch="a", bindings=(
        S.Binding(var="V", root="R", kind=S.TENSOR_NUMEL, operand="nope"),))

    with pytest.raises(S.SpecError, match="does not carry"):
        S.bind(spec, case())


def test_the_context_comes_from_the_case_or_from_the_spec():
    """The session's flag varies per case; the architecture does not."""
    spec = S.BridgeSpec(operator="X", arch="a", bindings=(
        S.Binding(var="VAR_SESSION_DETERMINISTIC", root="SESSION_OPTION",
                  kind=S.CONTEXT),
        S.Binding(var="VAR_PLATFORM_ARCH", root="PLATFORM_ARCH",
                  kind=S.CONTEXT, value=35)))
    env = S.bind(spec, case())

    assert env["VAR_SESSION_DETERMINISTIC"] is True
    assert env["VAR_PLATFORM_ARCH"] == 35


# --- observations --------------------------------------------------------


def test_an_observation_reads_its_logged_number_the_way_it_says():
    plain = S.Observation(var="V", column="c", withheld_from="D")
    flag = S.Observation(var="V", column="c", withheld_from="D",
                         reading="boolean")
    coded = S.Observation(var="V", column="c", withheld_from="D",
                          reading="boolean_constant", when_true=4, when_false=1)

    assert plain.value(5) == 5
    assert flag.value(0) is False
    assert coded.value(1) == 4
    assert coded.value(0) == 1


def test_an_observation_has_to_say_which_dimension_it_came_from(tmp_path):
    """Without it, an observation could be used to predict the field it was
    read off, where the answer is the question."""
    path = write(tmp_path, """
        operator: X
        observations:
          - variable: VAR_TDF_X
            column: x
        """)

    with pytest.raises(S.SpecError, match="names no dimension"):
        S.BridgeSpec.load(path)


def test_a_coded_observation_without_its_constants_is_refused(tmp_path):
    path = write(tmp_path, """
        operator: X
        observations:
          - variable: VAR_TDF_X
            column: x
            withheld_from: D
            reading: boolean_constant
            when_true: 4
        """)

    with pytest.raises(S.SpecError, match="when_false is unresolved"):
        S.BridgeSpec.load(path)


# --- the exported spec, against the derivation it came from --------------


def _require_exported_bridge_spec():
    from replay.package_data import active_package_dir, repo_root

    pkg = active_package_dir(repo_root())
    if not (pkg / "bridge_spec.yaml").is_file():
        pytest.skip(
            "bridge_spec.yaml missing (FAG priors purged; run export_adapter_pack)"
        )


def test_the_spec_accounts_for_every_variable_the_derivation_reads():
    """The claim the file makes. A variable in neither list is a spec that no
    longer matches the derivation it was exported from."""
    _require_exported_bridge_spec()
    from replay import bridge as B

    try:
        hd = B.derivation()
    except FileNotFoundError as exc:
        pytest.skip(str(exc))
    read = set()
    for field in hd.get("fields") or []:
        read.update(field.get("var_roots") or {})
    for premise in hd.get("premises") or []:
        read.update(premise.get("var_roots") or {})

    missing = read - default_spec().variables
    assert not missing, f"the derivation reads these and the spec is silent: {missing}"


def test_the_environment_supplies_what_is_read_and_no_more():
    """157 surplus variables used to be supplied. Harmless to the solver and
    misleading to a reader, who could not tell which ones mattered."""
    _require_exported_bridge_spec()
    spec = default_spec()
    env = ADAPTER.materialize(I.Case(), "c").build_static_env()

    assert set(env) == {b.var for b in spec.bindings}
    assert not set(env) & {u.var for u in spec.unbound}


def test_the_unbound_tiling_state_stays_unbound():
    """Supplying a guess would turn an honest unknown into a confident wrong
    answer, which is worse than the unknown."""
    _require_exported_bridge_spec()
    spec = default_spec()
    state = {u.var for u in spec.unbound if u.root == "TILING_DATA"}

    assert state
    assert all("tiling state" in u.reason for u in spec.unbound
               if u.var in state)
