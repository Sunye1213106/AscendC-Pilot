
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engines" / "understand-operator"

# Package YAML catalog with the uo package.
pyproject = ENGINE / "pyproject.toml"
text = pyproject.read_text(encoding="utf-8")
if '[tool.setuptools.package-data]' not in text:
    text += '\n[tool.setuptools.package-data]\n"uo" = ["resources/*.yaml"]\n'
    pyproject.write_text(text, encoding="utf-8")

# Load packaged symbol contracts into the existing offline evidence cache.
docs = ENGINE / "uo" / "scripts" / "cann_doc_evidence.py"
insert = '''PACKAGED_CATALOG_PATH = Path(__file__).resolve().parents[1] / "resources" / "cann_api_catalog.yaml"


def load_packaged_contracts() -> dict[str, dict[str, Any]]:
    # Load validated, machine-readable CANN symbol contracts shipped with UO.
    payload = read_yaml(PACKAGED_CATALOG_PATH) or {}
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
        out[symbol] = item
        for alias in item.get("aliases") or []:
            alias_name = str(alias or "").strip()
            if alias_name:
                alias_item = dict(item)
                alias_item["symbol_or_macro"] = alias_name
                alias_item["canonical_symbol"] = symbol
                out.setdefault(alias_name, alias_item)
    return out


def packaged_doc_evidence_bundle(
    *, cann_version: str = "latest"
) -> dict[str, Any]:
    # Return the packaged official catalog in doc_evidence.yaml shape.
    items = [
        _version_gate(dict(item), cann_version)
        for item in load_packaged_contracts().values()
    ]
    return {
        "version": 1,
        "cann_version": cann_version,
        "authority_order": ["operator_source", "target_cann_docs", "latest_docs", "other"],
        "catalog_source": PACKAGED_CATALOG_PATH.as_posix(),
        "items": [item for item in items if not item.get("unresolved")],
        "unresolved": [item for item in items if item.get("unresolved")],
    }


BUILTIN_CONTRACTS.update(load_packaged_contracts())
'''
text = docs.read_text(encoding="utf-8")
if "PACKAGED_CATALOG_PATH" not in text:
    marker = "\n\n\ndef docs_cache_dir"
    if marker not in text:
        raise SystemExit("cann_doc_evidence insertion marker missing")
    text = text.replace(marker, "\n\n\n" + insert + "\n\ndef docs_cache_dir", 1)
old = '''def _version_gate(data: dict[str, Any], requested: str) -> dict[str, Any]:
    have = str(data.get("cann_version") or "")
'''
new = '''def _version_gate(data: dict[str, Any], requested: str) -> dict[str, Any]:
    if str(data.get("version_scope") or "") == "multi_version":
        supported = {str(value) for value in data.get("cann_versions") or []}
        if requested in {"", "latest", "offline_fixture"} or not supported:
            return data
        requested_prefix = ".".join(str(requested).split(".")[:2])
        if any(str(value).startswith(requested_prefix) or requested_prefix.startswith(str(value)) for value in supported):
            return data
    have = str(data.get("cann_version") or "")
'''
if old in text:
    text = text.replace(old, new, 1)
docs.write_text(text, encoding="utf-8")

# Make call resolution contract-aware.
graph = ENGINE / "uo" / "scripts" / "function_call_graph.py"
text = graph.read_text(encoding="utf-8")
text = text.replace(
    'official_contracts: dict[str, dict[str, Any]] = field(default_factory=dict)',
    'official_contracts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)',
    1,
)
old = '''    for item in (doc_evidence or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol_or_macro") or "").strip()
        if not symbol:
            continue
        facts.official_contracts[symbol] = item
        kind = _official_contract_kind(item)
        if kind == "macro":
            facts.documented_macros.add(symbol)
        elif kind in {"function", "method", "interface", "api"}:
            facts.documented_external.add(symbol)
        for qualified in item.get("qualified_names") or []:
            root = str(qualified).split("::", 1)[0].strip()
            if root:
                facts.external_namespaces.add(root)
'''
new = '''    if not doc_evidence:
        from uo.scripts.cann_doc_evidence import packaged_doc_evidence_bundle

        doc_evidence = packaged_doc_evidence_bundle()
    for item in (doc_evidence or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol_or_macro") or "").strip()
        if not symbol:
            continue
        names = [symbol] + [str(alias or "").strip() for alias in item.get("aliases") or []]
        for name in names:
            if name:
                facts.official_contracts.setdefault(name, []).append(item)
        kind = _official_contract_kind(item)
        if kind == "macro":
            facts.documented_macros.add(symbol)
        elif kind in {"function", "method", "interface", "api"}:
            facts.documented_external.add(symbol)
        for qualified in item.get("qualified_names") or []:
            root = str(qualified).split("::", 1)[0].strip()
            if root:
                facts.external_namespaces.add(root)
'''
if old not in text:
    raise SystemExit("collect official contracts block missing")
text = text.replace(old, new, 1)

old = '''    name = site.callee_name
    if name in facts.source_macros or name in facts.compiler_macros or name in facts.documented_macros:
        if name in facts.source_macros:
            reason, confidence = "source_function_macro", "source_verified"
        elif name in facts.documented_macros:
            reason, confidence = "official_documented_macro", "documented"
        else:
            reason, confidence = "compiler_builtin_macro", "structurally_inferred"
        return _emit_target(
            site, caller, site_id, site_node, base_edge,
            node_type="CompileMacro", status="macro", reason=reason, confidence=confidence,
            contract=facts.official_contracts.get(name),
        )

    if name in facts.documented_external or name in facts.standard_external:
        reason = "official_documented_interface" if name in facts.documented_external else "standard_library_symbol"
        confidence = "documented" if name in facts.documented_external else "structurally_inferred"
        return _emit_target(
            site, caller, site_id, site_node, base_edge,
            node_type="ExternalFunction", status="external", reason=reason, confidence=confidence,
            contract=facts.official_contracts.get(name),
        )
'''
new = '''    name = site.callee_name
    if name in facts.source_macros or name in facts.compiler_macros:
        reason = "source_function_macro" if name in facts.source_macros else "compiler_builtin_macro"
        confidence = "source_verified" if name in facts.source_macros else "structurally_inferred"
        return _emit_target(
            site, caller, site_id, site_node, base_edge,
            node_type="CompileMacro", status="macro", reason=reason, confidence=confidence,
        )

    contract, contract_reason = _matching_official_contract(site, receiver_type, facts)
    if contract is not None:
        kind = _official_contract_kind(contract)
        return _emit_target(
            site, caller, site_id, site_node, base_edge,
            node_type="CompileMacro" if kind == "macro" else "ExternalFunction",
            status="macro" if kind == "macro" else "external",
            reason=contract_reason,
            confidence="documented",
            contract=contract,
        )

    if name in facts.standard_external:
        return _emit_target(
            site, caller, site_id, site_node, base_edge,
            node_type="ExternalFunction", status="external",
            reason="standard_library_symbol", confidence="structurally_inferred",
        )
'''
if old not in text:
    raise SystemExit("unindexed classification header missing")
text = text.replace(old, new, 1)

old = '''    used_external = facts.using_namespaces_by_file.get(site.file_path, set()) & facts.external_namespaces
    if used_external and not site.receiver_type_or_object:
        return _emit_target(
            site, caller, site_id, site_node, base_edge,
            node_type="ExternalFunction", status="external",
            reason="using_external_namespace_without_internal_definition",
            confidence="structurally_inferred",
        )

    if site.receiver_type_or_object:
        receiver_base = _normalize_type_name(receiver_type)
        if receiver_base and receiver_base not in facts.internal_classes and (
            _type_namespace_root(receiver_type) in facts.external_namespaces or used_external
        ):
'''
new = '''    # A using-directive expands lookup candidates; it does not prove symbol ownership.
    if site.receiver_type_or_object:
        receiver_base = _normalize_type_name(receiver_type)
        if receiver_base and receiver_base not in facts.internal_classes and (
            _type_namespace_root(receiver_type) in facts.external_namespaces
        ):
'''
if old not in text:
    raise SystemExit("broad using namespace block missing")
text = text.replace(old, new, 1)

helper = '''def _matching_official_contract(
    site: CallSite,
    receiver_type: str,
    facts: CallResolutionFacts,
) -> tuple[dict[str, Any] | None, str]:
    # Match by call style, arity, qualification, and owner type.
    hint = (site.callee_qualified_hint or "").replace(" ", "")
    has_receiver = bool((site.receiver_type_or_object or "").strip())
    for contract in facts.official_contracts.get(site.callee_name, []):
        counts = {int(value) for value in contract.get("argument_counts") or []}
        if counts and site.argument_count not in counts:
            continue
        kind = _official_contract_kind(contract)
        style = str(contract.get("call_style") or ("method" if kind == "method" else "free_function"))
        qualified = {str(value or "").replace(" ", "") for value in contract.get("qualified_names") or []}
        if kind == "macro":
            return contract, "official_contract:macro"
        if style == "method" or contract.get("receiver_types"):
            if not has_receiver:
                continue
            allowed_types = [str(value or "") for value in contract.get("receiver_types") or []]
            if not receiver_type or not any(_type_matches_scope(receiver_type, value) for value in allowed_types):
                continue
            return contract, "official_contract:receiver_type"
        if "::" in hint:
            if qualified and hint not in qualified and not any(
                hint.endswith("::" + value.split("::")[-1]) for value in qualified
            ):
                continue
            return contract, "official_contract:qualified_name"
        if bool(contract.get("allow_unqualified")):
            return contract, "official_contract:unqualified_free_function"
    return None, ""


'''
marker = "\n\ndef _emit_target("
if "def _matching_official_contract(" not in text:
    if marker not in text:
        raise SystemExit("official contract helper insertion marker missing")
    text = text.replace(marker, "\n\n" + helper + "def _emit_target(", 1)

old = '''    qualified = site.callee_qualified_hint or site.callee_name
    prefix = "MACRO" if node_type == "CompileMacro" else "EXTFN"
'''
new = '''    canonical_names = list(contract.get("qualified_names") or []) if contract else []
    qualified = str(canonical_names[0]) if canonical_names else (site.callee_qualified_hint or site.callee_name)
    prefix = "MACRO" if node_type == "CompileMacro" else "EXTFN"
'''
if old not in text:
    raise SystemExit("emit target qualified block missing")
text = text.replace(old, new, 1)

old = '''        target_node["official_contract"] = {
            "document_title": contract.get("document_title"),
            "document_url": contract.get("document_url"),
            "cann_version": contract.get("cann_version"),
            "semantic_summary": contract.get("semantic_summary"),
        }
'''
new = '''        target_node["official_contract"] = {
            "symbol_kind": contract.get("symbol_kind"),
            "qualified_names": contract.get("qualified_names") or [],
            "receiver_types": contract.get("receiver_types") or [],
            "argument_counts": contract.get("argument_counts") or [],
            "document_title": contract.get("document_title"),
            "document_url": contract.get("document_url"),
            "cann_version": contract.get("cann_version"),
            "cann_versions": contract.get("cann_versions") or [],
            "semantic_summary": contract.get("semantic_summary"),
            "source_authority": contract.get("source_authority"),
        }
'''
if old not in text:
    raise SystemExit("official contract payload block missing")
text = text.replace(old, new, 1)

old = '''    if receiver == "this":
        return caller.class_or_namespace
    pattern = re.compile(_DECL_TYPE_RE_TEMPLATE.format(receiver=re.escape(receiver)), re.MULTILINE)
'''
new = '''    if receiver == "this":
        return caller.class_or_namespace
    if receiver.endswith("()"):
        accessor = receiver[:-2].split("::")[-1]
        for contract in facts.official_contracts.get(accessor, []):
            return_type = _normalize_declared_type(str(contract.get("return_type") or ""))
            if return_type:
                return return_type
    pattern = re.compile(_DECL_TYPE_RE_TEMPLATE.format(receiver=re.escape(receiver)), re.MULTILINE)
'''
if old not in text:
    raise SystemExit("receiver accessor insertion marker missing")
text = text.replace(old, new, 1)

old = '''            type_name = _normalize_declared_type(match.group("type"))
            if type_name:
                matches.append(type_name)
'''
new = '''            type_name = _normalize_declared_type(match.group("type"))
            if type_name and _normalize_type_name(type_name).casefold() not in {
                "return", "if", "for", "while", "switch", "case", "auto"
            }:
                matches.append(type_name)
'''
if old not in text:
    raise SystemExit("receiver type filter block missing")
text = text.replace(old, new, 1)

old = '''    text = text[:-2] if text.endswith("->") else text[:-1] if text.endswith(".") else text
    return text.split("::")[-1].strip()
'''
new = '''    text = text[:-2] if text.endswith("->") else text[:-1] if text.endswith(".") else text
    text = re.sub(r"\\[[^\\]]*\\]$", "", text)
    return text.split("::")[-1].strip()
'''
if old not in text:
    raise SystemExit("receiver object block missing")
text = text.replace(old, new, 1)
graph.write_text(text, encoding="utf-8")

# Extend lexical receiver parsing to indexed objects and chained accessors.
body = ENGINE / "uo" / "scripts" / "function_body.py"
text = body.read_text(encoding="utf-8")
helper = '''def _balanced_open_left(
    text: str, pos: int, *, open_ch: str, close_ch: str, floor: int
) -> int | None:
    if pos <= floor or text[pos - 1] != close_ch:
        return None
    depth = 0
    idx = pos - 1
    while idx >= floor:
        ch = text[idx]
        if ch == close_ch:
            depth += 1
        elif ch == open_ch:
            depth -= 1
            if depth == 0:
                return idx
        idx -= 1
    return None


def _read_receiver_atom_left(text: str, pos: int, *, floor: int) -> tuple[str, int]:
    # Read identifier, indexed identifier, or zero-arg accessor immediately left.
    pos = _skip_ws_left(text, pos, floor=floor)
    if pos > floor and text[pos - 1] == "]":
        open_pos = _balanced_open_left(text, pos, open_ch="[", close_ch="]", floor=floor)
        if open_pos is not None:
            ident, ident_start = _read_ident_left(text, open_pos, floor=floor)
            if ident:
                return f"{ident}[]", ident_start
    if pos > floor and text[pos - 1] == ")":
        open_pos = _balanced_open_left(text, pos, open_ch="(", close_ch=")", floor=floor)
        if open_pos is not None:
            ident, ident_start = _read_ident_left(text, open_pos, floor=floor)
            if ident:
                return f"{ident}()", ident_start
    return _read_ident_left(text, pos, floor=floor)


'''
marker = "\n\ndef _call_context("
if "def _read_receiver_atom_left(" not in text:
    if marker not in text:
        raise SystemExit("function_body helper insertion marker missing")
    text = text.replace(marker, "\n\n" + helper + "def _call_context(", 1)
old_line = '    ident, ident_start = _read_ident_left(text, rpos, floor=floor)\n'
if old_line not in text:
    raise SystemExit("receiver atom call marker missing")
text = text.replace(
    old_line,
    '    ident, ident_start = _read_receiver_atom_left(text, rpos, floor=floor)\n',
    1,
)
body.write_text(text, encoding="utf-8")

# Regression tests.
test_external = ENGINE / "tests" / "test_call_external_classification.py"
text = test_external.read_text(encoding="utf-8")
text = text.replace(
    '    assert edge["verification_source"] == "official_documented_interface"\n',
    '    assert edge["verification_source"].startswith("official_contract:")\n',
    1,
)
old = '''def test_using_external_namespace_supports_unqualified_interface() -> None:
    caller = _fn("void Run() { DataCopy(a, b); }")
    facts = collect_call_resolution_facts(
        [caller],
        source_texts={"op_kernel/test.cpp": "using namespace AscendC;\\n" + caller.body_text},
    )
    edge, _node, unresolved = resolve_call_site(
        _site("DataCopy", argc=2), caller, by_name={}, by_qn={}, by_id={}, facts=facts
    )
    assert edge and edge["target_status"] == "external"
    assert edge["verification_source"] == "using_external_namespace_without_internal_definition"
    assert unresolved is None
'''
new = '''def test_packaged_contract_supports_unqualified_interface() -> None:
    caller = _fn("void Run() { DataCopy(a, b, 16); }")
    facts = collect_call_resolution_facts(
        [caller],
        source_texts={"op_kernel/test.cpp": "using namespace AscendC;\\n" + caller.body_text},
    )
    edge, _node, unresolved = resolve_call_site(
        _site("DataCopy", argc=3), caller, by_name={}, by_qn={}, by_id={}, facts=facts
    )
    assert edge and edge["target_status"] == "external"
    assert edge["verification_source"] == "official_contract:unqualified_free_function"
    assert edge["_target_node"]["official_contract"]["source_authority"] == "official_hiascend"
    assert unresolved is None


def test_using_namespace_does_not_prove_unknown_free_function() -> None:
    caller = _fn("void Run() { UnknownHelper(); }")
    facts = collect_call_resolution_facts(
        [caller],
        source_texts={"op_kernel/test.cpp": "using namespace AscendC;\\n" + caller.body_text},
    )
    edge, _node, unresolved = resolve_call_site(
        _site("UnknownHelper", argc=0), caller, by_name={}, by_qn={}, by_id={}, facts=facts
    )
    assert edge and edge["target_status"] == "missing"
    assert unresolved and unresolved["kind"] == "internal_definition_not_indexed"


def test_method_contract_requires_matching_receiver_type() -> None:
    caller = _fn("void Run() { Worker worker; worker.GetValue(0); }")
    facts = collect_call_resolution_facts(
        [caller], source_texts={"op_kernel/test.cpp": caller.body_text}
    )
    edge, _node, unresolved = resolve_call_site(
        _site("GetValue", receiver="worker.", argc=1),
        caller, by_name={}, by_qn={}, by_id={}, facts=facts
    )
    assert edge and edge["target_status"] == "missing"
    assert unresolved and unresolved["kind"] == "member_target_not_indexed"
'''
if old not in text:
    raise SystemExit("old using namespace test missing")
text = text.replace(old, new, 1)
test_external.write_text(text, encoding="utf-8")

test_scanner = ENGINE / "tests" / "test_call_scanner.py"
text = test_scanner.read_text(encoding="utf-8")
addition = '''

def test_indexed_member_call_preserves_base_receiver() -> None:
    sites = extract_call_sites(_fn("void Run() { queues[idx].template AllocTensor<float>(); }"))
    assert len(sites) == 1
    assert sites[0].callee_name == "AllocTensor"
    assert sites[0].receiver_type_or_object == "queues[]."


def test_chained_accessor_call_preserves_receiver() -> None:
    sites = extract_call_sites(_fn("void Run() { GetTPipePtr()->FetchEventID(HardEvent::S_V); }"))
    names = {site.callee_name: site for site in sites}
    assert names["FetchEventID"].receiver_type_or_object == "GetTPipePtr()->"
'''
if "test_indexed_member_call_preserves_base_receiver" not in text:
    text += addition
test_scanner.write_text(text, encoding="utf-8")

catalog_test = ENGINE / "tests" / "test_cann_api_catalog.py"
catalog_test.write_text('''from __future__ import annotations

from uo.scripts.cann_doc_evidence import load_packaged_contracts, packaged_doc_evidence_bundle


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
''', encoding="utf-8")

print("patched CANN catalog integration")
