from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
engine = ROOT / "engines" / "understand-operator"
graph_path = engine / "uo" / "scripts" / "function_call_graph.py"
text = graph_path.read_text(encoding="utf-8")

marker = '''    candidates = _candidate_callees(
        site, caller, by_name=by_name, by_qn=by_qn, receiver_type=receiver_type
    )
'''
insert = '''    # A precise receiver may prove an official method before generic short-name
    # lookup sees unrelated project helpers with the same name (for example TBuf::Get).
    method_contract, method_reason = _matching_official_contract(site, receiver_type, facts)
    if method_contract is not None and (site.receiver_type_or_object or "").strip():
        method_kind = _official_contract_kind(method_contract)
        method_style = str(
            method_contract.get("call_style")
            or ("method" if method_kind == "method" else "free_function")
        )
        if method_style == "method" or method_contract.get("receiver_types"):
            typed_source = [
                candidate
                for candidate in _filter_by_arity(
                    list(by_name.get(site.callee_name) or []), site.argument_count
                )
                if _type_matches_scope(receiver_type, candidate.class_or_namespace)
            ]
            if not typed_source:
                return _emit_target(
                    site,
                    caller,
                    site_id,
                    site_node,
                    base_edge,
                    node_type="ExternalFunction",
                    status="external",
                    reason=method_reason,
                    confidence="documented",
                    contract=method_contract,
                )

    candidates = _candidate_callees(
        site, caller, by_name=by_name, by_qn=by_qn, receiver_type=receiver_type
    )
'''
if "A precise receiver may prove an official method" not in text:
    if marker not in text:
        raise SystemExit("candidate routing marker missing")
    text = text.replace(marker, insert, 1)

start = text.find("def _infer_receiver_type(\n")
end = text.find("\n\ndef _receiver_object(", start)
if start < 0 or end < 0:
    raise SystemExit("receiver wrapper markers missing")
replacement = '''def _infer_receiver_type(
    site: CallSite, caller: FunctionDefinition, facts: CallResolutionFacts
) -> str:
    receiver_facts = facts.receiver_type_facts
    if receiver_facts is None:
        receiver_facts = build_receiver_type_facts(
            [caller],
            facts.source_text_by_file,
            official_contracts=facts.official_contracts,
        )
    structured = infer_receiver_type_from_facts(
        site,
        caller,
        receiver_facts,
        official_contracts=facts.official_contracts,
    )
    legacy = _legacy_receiver_type(site, caller, facts)
    if _receiver_type_supported(site, structured, facts):
        return structured
    if _receiver_type_supported(site, legacy, facts):
        return legacy
    # Preserve previous fail-closed behavior for aliases the lightweight parser
    # cannot bind to a concrete class; structured facts are preferred only when
    # they carry source/API support.
    return legacy or structured


def _receiver_type_supported(
    site: CallSite, receiver_type: str, facts: CallResolutionFacts
) -> bool:
    if not receiver_type:
        return False
    if any(_type_matches_scope(receiver_type, scope) for scope in facts.internal_classes):
        return True
    for contract in facts.official_contracts.get(site.callee_name, []):
        counts = {int(value) for value in contract.get("argument_counts") or []}
        if counts and site.argument_count not in counts:
            continue
        allowed = [str(value or "") for value in contract.get("receiver_types") or []]
        if allowed and any(_type_matches_scope(receiver_type, value) for value in allowed):
            return True
    return False


def _legacy_receiver_type(
    site: CallSite, caller: FunctionDefinition, facts: CallResolutionFacts
) -> str:
    receiver = _receiver_object(site.receiver_type_or_object)
    if not receiver:
        return ""
    if receiver == "this":
        return caller.class_or_namespace
    if receiver.endswith("()"):
        accessor = receiver[:-2].split("::")[-1]
        for contract in facts.official_contracts.get(accessor, []):
            return_type = _normalize_declared_type(str(contract.get("return_type") or ""))
            if return_type:
                return return_type
    pattern = re.compile(
        _DECL_TYPE_RE_TEMPLATE.format(receiver=re.escape(receiver)), re.MULTILINE
    )
    sources = [caller.header_text or "", caller.body_text or ""]
    full = facts.source_text_by_file.get(site.file_path, "")
    if full:
        line_prefix = "\n".join(full.splitlines()[: max(0, site.line)])
        sources.append(line_prefix)
    matches: list[str] = []
    for source in sources:
        for match in pattern.finditer(source):
            type_name = _normalize_declared_type(match.group("type"))
            if type_name and _normalize_type_name(type_name).casefold() not in {
                "return", "if", "for", "while", "switch", "case", "auto"
            }:
                matches.append(type_name)
    return matches[-1] if matches else ""
'''
text = text[:start] + replacement + text[end:]
graph_path.write_text(text, encoding="utf-8")

test_path = engine / "tests" / "test_receiver_type_propagation.py"
test = test_path.read_text(encoding="utf-8")
addition = r'''


def test_official_receiver_method_precedes_unrelated_short_name_candidate() -> None:
    caller = _fn(
        name="Run", owner="Driver", header="void Driver::Run(TBuf<> &buffer) {",
        body="void Driver::Run(TBuf<> &buffer) { buffer.Get<int>(); }",
        signature="(TBuf<>&buffer)", stable_id="FN_RUN",
    )
    unrelated = _fn(
        name="Get", owner="Policy", header="Buffer<int> &Policy::Get() {",
        body="Buffer<int> &Policy::Get() { return buffer_; }",
        signature="()", stable_id="FN_POLICY_GET",
    )
    unresolved: list[dict] = []
    facts = collect_call_resolution_facts(
        [caller, unrelated],
        source_texts={"op_kernel/test.h": caller.body_text + "\n" + unrelated.body_text},
    )
    _nodes, edges = build_call_edges_for_functions(
        [caller, unrelated], unresolved=unresolved, facts=facts
    )
    call = _edge(edges, caller.stable_id, "Get")
    assert call["target_status"] == "external"
    assert call["verification_source"] == "official_contract:receiver_type"
    assert not any(item.get("callee_name") == "Get" for item in unresolved)
'''
if "test_official_receiver_method_precedes_unrelated_short_name_candidate" not in test:
    test += addition
test_path.write_text(test, encoding="utf-8")
print("fixed receiver-scoped source/API resolution order")
