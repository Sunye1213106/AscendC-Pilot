from __future__ import annotations

from uo.scripts.cann_doc_evidence import (
    load_packaged_contracts,
    load_packaged_reg_contracts,
    load_packaged_reg_logic_contracts,
    packaged_doc_evidence_bundle,
)


def test_packaged_catalog_has_official_high_frequency_symbols() -> None:
    contracts = load_packaged_contracts()
    required = {
        "DataCopy", "DataCopyPad", "CrossCoreSetFlag", "CrossCoreWaitFlag",
        "SetGlobalBuffer", "AllocTensor", "EnQue", "DeQue", "FreeTensor",
        "InitBuffer", "GetBlockIdx", "GetSubBlockIdx", "PipeBarrier",
    }
    assert required <= set(contracts)
    assert all(str(contracts[name]["document_url"]).startswith("https://www.hiascend.com/") for name in required)
    assert all(float(contracts[name]["confidence"]) >= 0.9 for name in required)


def test_packaged_bundle_is_directly_consumable() -> None:
    bundle = packaged_doc_evidence_bundle(cann_version="9.0")
    names = {item["symbol_or_macro"] for item in bundle["items"]}
    assert "DataCopy" in names
    assert "SetGlobalBuffer" in names
    assert not bundle["unresolved"]


def test_packaged_reg_catalog_has_high_frequency_fag_symbols() -> None:
    contracts = load_packaged_reg_contracts()
    symbols = {item["symbol_or_macro"] for item in contracts.values()}
    required = {
        "LoadAlign", "StoreAlign", "StoreUnAlign", "CreateMask", "UpdateMask",
        "Cast", "Add", "Sub", "Mul", "Div", "Interleave", "Select",
    }
    assert required <= symbols
    assert all(
        str(item["document_url"]).startswith("https://www.hiascend.com/")
        and float(item["confidence"]) >= 0.9
        for item in contracts.values()
    )


def test_packaged_reg_logic_catalog_has_exact_contracts() -> None:
    contracts = load_packaged_reg_logic_contracts()
    symbols = {item["symbol_or_macro"] for item in contracts.values()}
    assert {"Max", "Min", "Or"} <= symbols
    assert all(item.get("argument_counts") == [4] for item in contracts.values())
