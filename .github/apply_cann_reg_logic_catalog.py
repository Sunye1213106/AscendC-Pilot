from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engines" / "understand-operator"
docs = ENGINE / "uo" / "scripts" / "cann_doc_evidence.py"
text = docs.read_text(encoding="utf-8")

if "PACKAGED_REG_LOGIC_CATALOG_PATH" not in text:
    text = text.replace(
        'PACKAGED_REG_CATALOG_PATH = Path(__file__).resolve().parents[1] / "resources" / "cann_reg_api_catalog.yaml"\n',
        'PACKAGED_REG_CATALOG_PATH = Path(__file__).resolve().parents[1] / "resources" / "cann_reg_api_catalog.yaml"\n'
        'PACKAGED_REG_LOGIC_CATALOG_PATH = Path(__file__).resolve().parents[1] / "resources" / "cann_reg_logic_catalog.yaml"\n',
        1,
    )

    marker = '\n\ndef packaged_doc_evidence_bundle('
    helper = '''

def load_packaged_reg_logic_contracts() -> dict[str, dict[str, Any]]:
    # Load official Reg comparison/logic contracts with collision-safe keys.
    payload = read_yaml(PACKAGED_REG_LOGIC_CATALOG_PATH) or {}
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
        out[f"RegLogic::{symbol}"] = item
    return out
'''
    if marker not in text:
        raise SystemExit("packaged bundle marker missing")
    text = text.replace(marker, helper + marker, 1)

    old = '''    packaged_items = list(load_packaged_contracts().values()) + list(load_packaged_reg_contracts().values())
'''
    new = '''    packaged_items = (
        list(load_packaged_contracts().values())
        + list(load_packaged_reg_contracts().values())
        + list(load_packaged_reg_logic_contracts().values())
    )
'''
    if old not in text:
        raise SystemExit("combined packaged items block missing")
    text = text.replace(old, new, 1)
    text = text.replace(
        '        "catalog_sources": [PACKAGED_CATALOG_PATH.as_posix(), PACKAGED_REG_CATALOG_PATH.as_posix()],\n',
        '        "catalog_sources": [\n'
        '            PACKAGED_CATALOG_PATH.as_posix(),\n'
        '            PACKAGED_REG_CATALOG_PATH.as_posix(),\n'
        '            PACKAGED_REG_LOGIC_CATALOG_PATH.as_posix(),\n'
        '        ],\n',
        1,
    )
    text = text.replace(
        'BUILTIN_CONTRACTS.update(load_packaged_reg_contracts())\n',
        'BUILTIN_CONTRACTS.update(load_packaged_reg_contracts())\n'
        'BUILTIN_CONTRACTS.update(load_packaged_reg_logic_contracts())\n',
        1,
    )

docs.write_text(text, encoding="utf-8")

test = ENGINE / "tests" / "test_cann_api_catalog.py"
t = test.read_text(encoding="utf-8")
if '    load_packaged_reg_logic_contracts,\n' not in t:
    t = t.replace(
        '    load_packaged_reg_contracts,\n',
        '    load_packaged_reg_contracts,\n    load_packaged_reg_logic_contracts,\n',
        1,
    )
addition = '''

def test_packaged_reg_logic_catalog_has_exact_contracts() -> None:
    contracts = load_packaged_reg_logic_contracts()
    symbols = {item["symbol_or_macro"] for item in contracts.values()}
    assert {"Max", "Min", "Or"} <= symbols
    assert all(item.get("argument_counts") == [4] for item in contracts.values())
'''
if "test_packaged_reg_logic_catalog_has_exact_contracts" not in t:
    t += addition
test.write_text(t, encoding="utf-8")

print("patched official Reg comparison/logic catalog integration")
