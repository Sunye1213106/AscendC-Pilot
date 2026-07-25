from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engines" / "understand-operator"
docs = ENGINE / "uo" / "scripts" / "cann_doc_evidence.py"
text = docs.read_text(encoding="utf-8")

if "PACKAGED_REG_CATALOG_PATH" not in text:
    text = text.replace(
        'PACKAGED_CATALOG_PATH = Path(__file__).resolve().parents[1] / "resources" / "cann_api_catalog.yaml"\n',
        'PACKAGED_CATALOG_PATH = Path(__file__).resolve().parents[1] / "resources" / "cann_api_catalog.yaml"\n'
        'PACKAGED_REG_CATALOG_PATH = Path(__file__).resolve().parents[1] / "resources" / "cann_reg_api_catalog.yaml"\n',
        1,
    )

    marker = '\n\ndef packaged_doc_evidence_bundle('
    helper = '''

def load_packaged_reg_contracts() -> dict[str, dict[str, Any]]:
    # Load official AscendC::Reg contracts without collapsing same-name Memory APIs.
    payload = read_yaml(PACKAGED_REG_CATALOG_PATH) or {}
    rows = payload.get("contracts") or []
    out: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        symbol = str(item.get("symbol_or_macro") or "").strip()
        kind = str(item.get("symbol_kind") or "").casefold()
        if not symbol or kind not in {"macro", "function", "method", "interface", "api"}:
            continue
        if not str(item.get("document_url") or "").startswith("https://www.hiascend.com/"):
            continue
        if float(item.get("confidence") or 0.0) < 0.9:
            continue
        out[f"Reg::{symbol}"] = item
    return out
'''
    if marker not in text:
        raise SystemExit("packaged bundle marker missing")
    text = text.replace(marker, helper + marker, 1)

    old = '''    items = [
        _version_gate(dict(item), cann_version)
        for item in load_packaged_contracts().values()
    ]
'''
    new = '''    packaged_items = list(load_packaged_contracts().values()) + list(load_packaged_reg_contracts().values())
    items = [
        _version_gate(dict(item), cann_version)
        for item in packaged_items
    ]
'''
    if old not in text:
        raise SystemExit("packaged items block missing")
    text = text.replace(old, new, 1)
    text = text.replace(
        '        "catalog_source": PACKAGED_CATALOG_PATH.as_posix(),\n',
        '        "catalog_sources": [PACKAGED_CATALOG_PATH.as_posix(), PACKAGED_REG_CATALOG_PATH.as_posix()],\n',
        1,
    )
    text = text.replace(
        'BUILTIN_CONTRACTS.update(load_packaged_contracts())\n',
        'BUILTIN_CONTRACTS.update(load_packaged_contracts())\nBUILTIN_CONTRACTS.update(load_packaged_reg_contracts())\n',
        1,
    )

docs.write_text(text, encoding="utf-8")

test = ENGINE / "tests" / "test_cann_api_catalog.py"
t = test.read_text(encoding="utf-8")
t = t.replace(
    'from uo.scripts.cann_doc_evidence import load_packaged_contracts, packaged_doc_evidence_bundle\n',
    'from uo.scripts.cann_doc_evidence import (\n'
    '    load_packaged_contracts,\n'
    '    load_packaged_reg_contracts,\n'
    '    packaged_doc_evidence_bundle,\n'
    ')\n',
    1,
)
addition = '''

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
'''
if "test_packaged_reg_catalog_has_high_frequency_fag_symbols" not in t:
    t += addition
test.write_text(t, encoding="utf-8")

print("patched official Reg API catalog integration")
