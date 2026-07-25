from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engines" / "understand-operator"
graph = ENGINE / "uo" / "scripts" / "function_call_graph.py"
text = graph.read_text(encoding="utf-8")

old = '''    if candidates:
        ids = [c.stable_id for c in candidates]
        edge = {
'''
new = '''    if candidates:
        family = _source_overload_family(
            site, caller, site_id, site_node, base_edge, candidates
        )
        if family is not None:
            return family
        ids = [c.stable_id for c in candidates]
        edge = {
'''
if old not in text and "family = _source_overload_family(" not in text:
    raise SystemExit("candidate-set insertion marker missing")
if old in text:
    text = text.replace(old, new, 1)

helper = '''def _source_overload_family(
    site: CallSite,
    caller: FunctionDefinition,
    site_id: str,
    site_node: dict[str, Any],
    base_edge: dict[str, Any],
    candidates: list[FunctionDefinition],
) -> tuple[dict[str, Any], dict[str, Any], None] | None:
    """Resolve to a source symbol family without selecting a concrete overload.

    This is safe only when every arity-compatible candidate has the same precise
    qualified name and owning scope. Member definitions remain attached to the
    family node, so downstream consumers can request concrete overload binding
    only when it is materially needed.
    """
    if len(candidates) < 2:
        return None
    qualified = {str(candidate.qualified_name or "").replace(" ", "") for candidate in candidates}
    scopes = {_normalize_type_name(candidate.class_or_namespace) for candidate in candidates}
    arities = {_signature_arity(candidate.normalized_signature) for candidate in candidates}
    if len(qualified) != 1 or not next(iter(qualified), ""):
        return None
    if len(scopes) != 1:
        return None
    if arities != {site.argument_count}:
        return None
    ordered = sorted(candidates, key=lambda candidate: candidate.stable_id)
    qualified_name = ordered[0].qualified_name
    family_id = mint_scoped_node_id(
        "FNFAMILY",
        qualified_name,
        str(site.argument_count),
        normalized_expression=f"{qualified_name}/{site.argument_count}",
    )
    family_node = {
        "id": family_id,
        "layer": "kernel",
        "node_type": "FunctionOverloadSet",
        "name": site.callee_name,
        "qualified_name": qualified_name,
        "class_or_namespace": ordered[0].class_or_namespace,
        "argument_count": site.argument_count,
        "resolution_status": "resolved_family",
        "member_function_ids": [candidate.stable_id for candidate in ordered],
        "members": [
            {
                "function_id": candidate.stable_id,
                "normalized_signature": candidate.normalized_signature,
                "template_arity_or_signature": candidate.template_arity_or_signature,
                "specialization_kind": candidate.specialization_kind,
                "file_path": candidate.file_path,
                "start_line": candidate.start_line,
            }
            for candidate in ordered
        ],
    }
    edge = {
        **base_edge,
        "id": mint_edge_id("calls", caller.stable_id, family_id, site_id),
        "target": family_id,
        "target_status": "resolved_family",
        "candidate_ids": family_node["member_function_ids"],
        "confidence": "source_family",
        "verification_source": "same_qualified_name_and_arity_overload_family",
        "_target_node": family_node,
    }
    return edge, site_node, None


'''
marker = "def _classify_unindexed_target(\n"
if "def _source_overload_family(" not in text:
    if marker not in text:
        raise SystemExit("overload helper marker missing")
    text = text.replace(marker, helper + marker, 1)

graph.write_text(text, encoding="utf-8")

# Update the existing overload regression: preserve every member, but do not ask
# semantic agents to choose a concrete overload when source facts only prove the family.
test = ENGINE / "tests" / "test_function_call_graph.py"
t = test.read_text(encoding="utf-8")
old = '''def test_overloaded_callee_ambiguous_is_candidate_set(tmp_path: Path) -> None:
'''
if old in t:
    t = t.replace(old, "def test_overloaded_callee_resolves_to_source_family(tmp_path: Path) -> None:\n", 1)
t = t.replace(
    '''    helper_calls = [e for e in edges if e.get("callee_name") == "Helper"]
    assert helper_calls and helper_calls[0].get("target_status") == "candidate_set"
''',
    '''    helper_calls = [e for e in edges if e.get("callee_name") == "Helper"]
    assert helper_calls and helper_calls[0].get("target_status") == "resolved_family"
    assert len(helper_calls[0].get("candidate_ids") or []) == 2
    assert not any(item.get("kind") == "call_target_ambiguous" for item in unresolved)
''',
    1,
)
addition = '''

def test_same_short_name_in_different_scopes_stays_candidate_set(tmp_path: Path) -> None:
    (tmp_path / "k.h").write_text(
        "class A { public: static void Helper(int x) {} }; "
        "class B { public: static void Helper(int x) {} }; "
        "void Run() { Helper(1); }\\n",
        encoding="utf-8",
    )
    unresolved: list[dict] = []
    _nodes, edges = build_call_edges_for_functions(
        iter_function_definitions(tmp_path, "k.h"), unresolved=unresolved
    )
    helper_calls = [edge for edge in edges if edge.get("callee_name") == "Helper"]
    assert helper_calls and helper_calls[0].get("target_status") == "candidate_set"
    assert any(item.get("kind") == "call_target_ambiguous" for item in unresolved)
'''
if "test_same_short_name_in_different_scopes_stays_candidate_set" not in t:
    t += addition
test.write_text(t, encoding="utf-8")

print("patched deterministic source overload families")
