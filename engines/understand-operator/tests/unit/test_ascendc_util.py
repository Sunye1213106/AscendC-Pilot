# -*- coding: utf-8 -*-
from uo_init.semantics.ascendc_util import cann_util_api_names, is_cann_util_api
from uo_init.semantics import registry as semreg


def test_util_catalog_includes_ceildiv_getsortlen_arithprogression() -> None:
    names = cann_util_api_names()
    assert "CeilDiv" in names
    assert "GetSortLen" in names
    assert "ArithProgression" in names or "Arange" in names
    assert is_cann_util_api("CeilDiv")
    assert is_cann_util_api("GetSortLen")
    assert is_cann_util_api("AscendC::CeilDiv")


def test_registry_classifies_util_spellings() -> None:
    semreg.load_registry.cache_clear()
    cat, engine, conf = semreg.classify("CeilDiv")
    assert cat == "util"
    assert engine == "SCALAR"
    assert conf == "confirmed"
    cat2, _, _ = semreg.classify("GetSortLen")
    assert cat2 == "util"
