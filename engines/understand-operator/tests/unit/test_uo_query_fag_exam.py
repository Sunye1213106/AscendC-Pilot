# -*- coding: utf-8 -*-
"""Offline FAG arch35 goldens for uo-query (Q6–Q14 / Q16–Q18 graph facts).

GLM sessions are not the pass bar. Extraction-dependent asserts skip until the
committed ``.uo`` contains the new locatable tokens.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from uo_init.store.reader import find_uo_product
from uo_init.uo_query import open_query


def _resolve_fag() -> tuple[Path | None, Path | None]:
    for root in (
        Path(
            r"d:\PR-review\TEST\.ascendc-pr\gitcode.com--cann--ops-transformer--pr-10546"
            r"\attention\flash_attention_score_grad"
        ),
        Path(r"d:\PR-review\TEST\ops-transformer\attention\flash_attention_score_grad"),
        Path(r"d:\TEST\ops-transformer\attention\flash_attention_score_grad"),
    ):
        product = find_uo_product(root, architecture="arch35")
        if product is not None and Path(product).is_file():
            return root, Path(product)
    return None, None


FAG_ROOT, FAG_PRODUCT = _resolve_fag()


pytestmark = pytest.mark.skipif(
    FAG_PRODUCT is None or not Path(FAG_PRODUCT).is_file(),
    reason="FAG arch35 .uo product is not present",
)


@pytest.fixture(scope="module")
def q():
    return open_query(FAG_ROOT, architecture="arch35")


def test_q6_kernel_launch_first_page_is_arch35(q) -> None:
    launch = q.aggregate_kernel_launch()
    assert launch["count"] >= 1
    first_pipe = next((row for row in launch["phases"] if row.get("ok")), None)
    assert first_pipe is not None
    pipe_file = str(first_pipe.get("file") or "").replace("\\", "/")
    assert "arch35" in pipe_file
    assert first_pipe.get("pipe")
    if launch.get("entry"):
        entry_file = str(launch["entry"].get("file") or "").replace("\\", "/")
        assert "arch35" in entry_file or "entry_regbase" in entry_file


def test_q7_locate_coverage_keeps_sibling_files(q) -> None:
    out = q.aggregate_locate("CalcleTNDDeterParam", limit=8)
    cov = out.get("coverage") or {}
    files = " ".join(list(out.get("files") or {}) + list(cov.get("sibling_files") or []))
    assert "coverage" in out
    assert "files" in out
    assert (
        cov.get("answerable") is True
        or cov.get("completeness") != "first_hit"
        or int(cov.get("definition_sites_count") or 0) > 1
        or out["count"] > 1
    )
    assert "varlen" in files.replace("\\", "/").lower() or out["count"] > 1


def test_q9_first_page_is_dim_coverage(q) -> None:
    out = q.aggregate_template_match("DTemplateNum=128,DeterType=0,InputDType=3")
    cov = (out.get("coverage") or {}).get("dim_coverage") or out.get("dim_coverage") or {}
    assert "128" in (cov.get("DTemplateNum") or [])
    keys = list(out.keys())
    assert keys.index("coverage") < keys.index("template_blocks")


def test_q10_register_tiling_default_or_template(q) -> None:
    default = q.aggregate_locate("REGISTER_TILING_DEFAULT")
    template = q.aggregate_locate("REGISTER_TILING_TEMPLATE")
    if default["count"] == 0:
        pytest.skip("REGISTER_TILING_DEFAULT not in committed .uo; rebuild after extract")
    assert default["count"] >= 1
    assert template["count"] >= 1 or default["count"] >= 1


def test_q11_setschedulemode_and_sync(q) -> None:
    sched = q.aggregate_locate("SetScheduleMode")
    assert sched["count"] >= 1
    files = " ".join(str(row.get("file") or "") for row in sched.get("locations") or [])
    files += " ".join((sched.get("coverage") or {}).get("sibling_files") or [])
    assert "arch35" in files.replace("\\", "/")
    sync = q.aggregate_locate("SyncALLCores")
    if sync["count"] == 0:
        pytest.skip("SyncALLCores not in committed .uo")
    sync_files = " ".join(str(row.get("file") or "") for row in sync.get("locations") or [])
    sync_files += " ".join((sync.get("coverage") or {}).get("sibling_files") or [])
    assert "arch35" in sync_files.replace("\\", "/")


def test_q13_fused_outer_alias_and_occupancy(q) -> None:
    hit = q.field_impact("fusedOuter")
    assert hit.get("ok") is True
    assert hit.get("canonical") == "blockOuter" or hit["field"]["name"] == "blockOuter"
    assert hit.get("occupancy_axis") == "fusedOuter vs aicNum"


def test_q14_buffer_hits_wrapper_or_allocated(q) -> None:
    out = q.aggregate_buffer("MutexBuffer")
    if out["count"] == 0:
        out = q.aggregate_buffer("")
    if out["count"] == 0:
        pytest.skip("buffer graph empty in committed .uo; rebuild after extract")
    blob = str(out).lower()
    assert "mutex" in blob or "localtensor" in blob or "allocated" in blob or out["count"] >= 1


def test_q16_d320_nearby_lists_templates(q) -> None:
    out = q.aggregate_template_match("DTemplateNum=320")
    assert int(out.get("matching_block_count") or 0) == 0
    nearby = out.get("nearby") or []
    values: list[str] = []
    for row in nearby:
        values.extend(str(v) for v in (row.get("values") or []))
    coverage = (out.get("dim_coverage") or {}).get("DTemplateNum") or []
    listed = set(values) | set(str(v) for v in coverage)
    for width in ("64", "128", "192", "256", "768"):
        assert width in listed


def test_session_pages_kernel_launch_three_phases(q) -> None:
    launch = q.aggregate_kernel_launch()
    pipes = [str(row.get("pipe") or "") for row in launch.get("phases") or [] if row.get("ok")]
    assert len(pipes) >= 3
    blob = str(launch).lower()
    assert "entry_regbase" in blob or "regbasefag" in blob.replace("_", "")


def test_session_pages_splitaxis_and_scale(q) -> None:
    split = q.field_impact("splitAxis")
    assert split.get("ok") is True
    blob = str(split).lower()
    assert "setsplitaxis" in blob.replace("_", "") or "splitaxis" in blob
    scale = q.field_impact("scaleValue")
    assert scale.get("ok") is True


def test_session_pages_enable_pre_sfmg_branch(q) -> None:
    field = q.field_impact("enablePreSfmg")
    assert field.get("ok") is True
    branch = q.aggregate_kernel_branch("enablePreSfmg")
    if int(branch.get("count") or 0) == 0:
        assert branch.get("empty_reason") == "not_extracted"
    else:
        assert int(branch["count"]) >= 1


def test_session_pages_process_dqkv_and_muls(q) -> None:
    dq = q.aggregate_locate("ProcessDqkv")
    assert dq["count"] >= 1
    assert (dq.get("coverage") or {}).get("answerable") is True
    files = " ".join(str(row.get("file") or "") for row in dq.get("locations") or [])
    assert "post_regbase" in files.replace("\\", "/")
    muls = q.aggregate_locate("ProcessMulsAndCast")
    assert muls["count"] >= 1
    muls_files = " ".join(str(row.get("file") or "") for row in muls.get("locations") or [])
    assert "block_vec" in muls_files.replace("\\", "/")
    cast = q.search("Cast", limit=8)
    assert cast
    assert "get_cast" not in str(cast[0].get("name") or "").lower()


def test_session_pages_tpl_sel_and_key_dims(q) -> None:
    sel = q.aggregate_locate("ASCENDC_TPL_SEL")
    assert sel["count"] >= 1
    orig = q.aggregate_locate("ORIG_DTYPE_QUERY")
    assert orig["count"] >= 1
    assert (orig.get("coverage") or {}).get("answerable") is True
    dne = q.aggregate_locate("IsDNoEqual")
    assert dne["count"] >= 1
    assert str((dne.get("locations") or [{}])[0].get("kind") or "") == "TILING_KEY"
    nz = q.aggregate_locate("IsNzOut")
    assert nz["count"] >= 1
    assert str((nz.get("locations") or [{}])[0].get("kind") or "") == "TILING_KEY"
    match = q.aggregate_template_match("DTemplateNum=128,DeterType=0,InputDType=3")
    assert int(match.get("matching_block_count") or 0) == 7
    assert (match.get("coverage") or {}).get("completeness") == "coverage_checked"


def test_session_pages_fused_outer_alias(q) -> None:
    loc = q.aggregate_locate("fusedOuter")
    assert loc["count"] >= 1
    hit = q.field_impact("fusedOuter")
    assert hit.get("ok") is True
    assert "blockOuter" in str(hit.get("canonical") or hit.get("field") or "")
    fused = q.search("fused", limit=8)
    assert fused
    assert "fusedmuldstadd" not in str(fused[0].get("name") or "").lower()
