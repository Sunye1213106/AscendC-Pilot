# -*- coding: utf-8 -*-
"""Full perception, from nothing, inside five minutes.

The budget is what keeps the scope honest. Perception is allowed to widen --
it has to, since a file left out does not merely cost detail but makes
whatever the operator reads from it look undefined -- and the only thing
stopping that widening from becoming a twenty-minute wait is measuring it.

Five minutes is the point past which a person stops running the tool. It is
not an estimate of how long the work takes: the run this was written against
finishes in about eighty-five seconds, so a failure here means something grew
by a factor of three, not that the margin was thin.

Cold in the sense that matters: nothing is carried over from an earlier run.
The operating system's file cache stays warm, which is what a second run in a
day looks like anyway.
"""
from __future__ import annotations

import time

import pytest

from uo_init import scope_scan as sscan

#: Seconds. Above this the tool stops being usable interactively.
BUDGET = 300.0


@pytest.fixture(scope="module")
def perception(fag_dir, cann_root, ops_root, arch_dir):
    """Everything the analysis can see, built once, timed."""
    from uo_init.assemble_kb import extract_host_bundle

    started = time.perf_counter()
    bundle = extract_host_bundle(
        op_dir=str(fag_dir),
        cann_root=str(cann_root),
        ops_root=str(ops_root),
        arch_dir=arch_dir,
    )
    bundle["_elapsed"] = time.perf_counter() - started
    return bundle


def test_full_perception_fits_the_budget(perception):
    elapsed = perception["_elapsed"]
    assert elapsed < BUDGET, (
        f"cold full perception took {elapsed:.0f}s, over the {BUDGET:.0f}s budget"
    )


def test_perception_reaches_every_layer(perception):
    """A budget met by looking at less is not the point.

    Each of these is a layer that was outside the analysis before: the API
    states which inputs may arrive together, the declarations pair the dtypes,
    and the kernel says which dimension decides which code.
    """
    spec = perception["spec"]
    assert spec.scope is not None
    assert spec.host_targets, "no host tiling translation unit"
    assert spec.api_targets, "no API translation unit: input contract unread"
    assert spec.kernel_targets, "no kernel entry: branch map unread"
    assert spec.decl_targets, "no definition translation unit"


def test_shared_headers_the_operator_includes_are_in_scope(perception):
    """The reason scope cannot be a name match.

    A domain keeps common headers beside its operators. They carry no operator
    name yet are compiled into it, and dropping them is what made reads from
    them look undefined.
    """
    scope = perception["spec"].scope
    shared = [f for f in scope.files if f.shared]
    assert shared, "no shared file reached: the include closure found nothing"


def test_one_architecture_at_a_time(perception, arch_dir):
    """A run models one hardware generation; the others' sources contradict
    it."""
    scope = perception["spec"].scope
    for f in scope.files:
        others = [
            p
            for p in (s.lower() for s in f.path.parts)
            if sscan.ARCH_SEGMENT_RE.match(p) and p != arch_dir
        ]
        assert not others, f"{f.path} belongs to {others}, not {arch_dir}"


def test_the_declared_interface_is_read(perception):
    facts = perception["decl_facts"]
    assert facts.params, "no declared parameters"
    # The dtype lists are columns: entry i of every parameter is one supported
    # combination. Without them a query dtype looks independent of the key's.
    assert facts.combinations, "no dtype combinations: the columns did not line up"


def test_the_api_states_what_it_refuses(perception):
    contract = perception["api_contract"]
    assert contract.premises, "no premises: the API layer refuses nothing?"
    ungrounded = [p for p in contract.premises if not p.is_grounded]
    assert not ungrounded, (
        "premises that reached no declared parameter: "
        + "; ".join(f"{p.text} ({p.unresolved})" for p in ungrounded[:5])
    )


def test_the_kernel_branch_map_is_built(perception):
    kernel = perception["kernel_ir"]
    assert kernel is not None
    assert kernel.branches, "no compile-time branches found in the kernel"
    # Parsing once per dtype variant only pays for itself if the variants
    # actually compile different code.
    assert len(kernel.variants) > 1
    assert kernel.variant_only(), (
        "every branch compiles under every dtype variant, so the extra parses "
        "bought nothing -- check the dtype macro is reaching the parse"
    )


def test_the_closure_is_not_paid_for_unless_asked(perception):
    """It is five sixths of the run and key derivation reads none of it."""
    assert perception["metrics"] is None
    assert perception["gap"] is None
