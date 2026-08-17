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

#: Measuring perception means performing it, so this file costs what it
#: measures -- minutes, against the real operator and CANN trees. It carries
#: the same markers as the other clang-heavy files so the day-to-day run
#: skips it rather than being paced by the one test that is supposed to be
#: slow. Nothing here is meaningful against a smaller input: a toy operator
#: finishing quickly says nothing about whether this one still does.
pytestmark = [pytest.mark.requires_cann, pytest.mark.requires_fag]


@pytest.fixture(scope="module")
def perception(fag_dir, cann_root, ops_root, arch_dir):
    """Everything the analysis can see, built once, timed."""
    from uo_init.extract_bundle import extract_host_bundle

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
    """Extract product is host IR ∥ kernel IR over a scoped operator tree."""
    spec = perception["spec"]
    assert spec.scope is not None
    assert spec.host_targets, "no host tiling translation unit"
    assert spec.kernel_targets, "no kernel entry: branch map unread"
    assert perception.get("host_ir") is not None
    assert perception.get("kernel_ir") is not None


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


def test_the_kernel_ir_is_built(perception):
    kernel = perception["kernel_ir"]
    assert kernel is not None
    assert perception.get("host_ir") is not None
    assert set(perception) >= {"spec", "host_ir", "kernel_ir", "timing"}
    assert "decl_facts" not in perception
    assert "api_contract" not in perception
    assert "metrics" not in perception
    assert "families" not in perception
    assert kernel.branches, "no compile-time branches found in the kernel"


@pytest.mark.requires_cann
@pytest.mark.requires_fag
def test_extract_host_bundle_is_the_only_extract_product(perception):
    """uo-extract-v1 is host_ir + kernel_ir; no families/fold/key_bind sidecars."""
    timing = perception.get("timing") or {}
    assert float(perception["_elapsed"]) < BUDGET
    assert "total_seconds" in timing or timing
    kernel = perception["kernel_ir"]
    assert len(list(getattr(kernel, "variants", None) or [])) <= 1
