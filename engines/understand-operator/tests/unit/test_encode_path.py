# -*- coding: utf-8 -*-
"""Which functions a run must have entered before the key is encoded.

The answer decides whether a member written in one of them counts as written
by the time it is read, so getting it wrong either invents initial values or
erases real ones.
"""
from __future__ import annotations

from uo_init.clang_walk import PathCond
from uo_init.derive_key_fields import Const, KeyFieldDeriver
from uo_init.expr_ir import Ref


class _Site:
    """A recorded call, as much of one as reachability looks at."""

    def __init__(self, caller: str, line: int = 0, conditions=()):
        self.caller = caller
        self.line = line
        self.path_conditions = tuple(conditions)


class _IR:
    """A call graph and nothing else."""

    def __init__(self, sites: dict[str, list[_Site]]):
        self._sites = sites

    def calls_to(self, callee: str) -> list[_Site]:
        return list(self._sites.get(callee, ()))


def _deriver(sites: dict[str, list[_Site]], encode: str = "GetTilingKey"):
    d = KeyFieldDeriver(host_ir=_IR(sites), resolver=None, var_model=None)
    d._encode_fn = encode
    d._encode_path_cache = None
    d._reach_cache.clear()
    return d


def _guard(text: str, kind: str = "if") -> PathCond:
    return PathCond(text, False, "f.cpp", 1, kind=kind)


def test_the_function_holding_the_encoding_always_counts_as_entered():
    d = _deriver({})
    assert d._encode_path() == {"GetTilingKey"}


def test_a_chain_of_single_callers_is_walked_all_the_way_up():
    d = _deriver(
        {
            "GetTilingKey": [_Site("DoOpTiling")],
            "DoOpTiling": [_Site("DoTiling")],
        }
    )
    assert d._encode_path() == {"GetTilingKey", "DoOpTiling", "DoTiling"}


def test_a_driver_that_also_logs_the_key_is_still_known_to_have_run():
    """The shape that broke the single-caller walk.

    One driver computes the key and then dumps it, so the encoding has two
    call sites and neither alone implies the driver. Both roads start at the
    driver, which is what makes it a dominator.
    """
    d = _deriver(
        {
            "GetTilingKey": [_Site("DoTiling", 129), _Site("DumpTilingInfo", 167)],
            "DumpTilingInfo": [_Site("DoTiling", 130)],
        }
    )
    assert d._encode_path() == {"GetTilingKey", "DoTiling"}


def test_two_ways_in_imply_nothing_between_them():
    """Called from a driver or from a test harness: neither is guaranteed."""
    d = _deriver(
        {
            "GetTilingKey": [_Site("DoTiling"), _Site("RunStandalone")],
        }
    )
    assert d._encode_path() == {"GetTilingKey"}


def test_a_shared_step_on_every_way_in_still_counts():
    d = _deriver(
        {
            "GetTilingKey": [_Site("Encode")],
            "Encode": [_Site("PathA"), _Site("PathB")],
            "PathA": [_Site("Driver")],
            "PathB": [_Site("Driver")],
        }
    )
    assert d._encode_path() == {"GetTilingKey", "Encode", "Driver"}


def test_a_cycle_in_the_call_graph_does_not_hang_or_over_claim():
    d = _deriver(
        {
            "GetTilingKey": [_Site("Helper")],
            "Helper": [_Site("GetTilingKey")],
        }
    )
    assert d._encode_path() == {"GetTilingKey"}


def test_callers_that_cannot_reach_the_encoding_are_not_ways_in():
    """Hundreds of registry accessors have no callers and no bearing here."""
    sites = {
        "GetTilingKey": [_Site("DoTiling")],
        "SomeUnrelatedAccessor": [],
    }
    d = _deriver(sites)
    assert d._encode_path() == {"GetTilingKey", "DoTiling"}


def test_an_entry_reached_only_through_the_driver_is_not_a_second_way_in():
    d = _deriver(
        {
            "GetTilingKey": [_Site("Inner")],
            "Inner": [_Site("Driver")],
            "Driver": [],
        }
    )
    assert "Driver" in d._encode_path()


class TestReached:
    """`_reached` answers "did this function run", as a condition."""

    def test_the_entry_of_the_encode_path_simply_ran(self):
        d = _deriver({"GetTilingKey": [_Site("DoTiling")]})
        assert isinstance(d._reached("DoTiling", 0), Const)
        assert d._always_runs("DoTiling", 0)

    def test_an_unguarded_call_from_something_that_ran_also_ran(self):
        d = _deriver(
            {
                "GetTilingKey": [_Site("DoTiling")],
                "GetShapeAttrsInfo": [_Site("DoTiling", 102)],
            }
        )
        assert d._always_runs("GetShapeAttrsInfo", 0)

    def test_a_rejected_input_bailing_out_earlier_does_not_make_the_call_optional(self):
        """`if (ret != SUCCESS) return ret;` before the call.

        Every run that reaches the encoding got past it, so the call happened.
        Read as an ordinary guard, a driver calling its hooks in a fixed order
        looks like it might skip all but the first one.
        """
        d = _deriver(
            {
                "GetTilingKey": [_Site("DoTiling")],
                "DoOpTiling": [
                    _Site(
                        "DoTiling",
                        113,
                        [_guard("ret != ge::GRAPH_SUCCESS", kind="bailout")],
                    )
                ],
            }
        )
        assert d._always_runs("DoOpTiling", 0)

    def test_a_guard_nobody_could_read_keeps_the_call_conditional(self):
        d = _deriver(
            {
                "GetTilingKey": [_Site("DoTiling")],
                "MaybeCalled": [_Site("DoTiling", 200, [_guard("", kind="if")])],
            }
        )
        reached = d._reached("MaybeCalled", 0)
        assert not d._always_runs("MaybeCalled", 0)
        assert isinstance(reached, Ref)

    def test_a_function_nothing_calls_and_nothing_reaches_is_not_assumed_to_run(self):
        """The unsound default this replaced: no callers did not mean "entry"."""
        d = _deriver({"GetTilingKey": [_Site("DoTiling")]})
        assert not d._always_runs("SomeOrphanHelper", 0)
