from pathlib import Path

root = Path(__file__).resolve().parents[1]
type_path = root / 'engines/understand-operator/uo/scripts/type_normalizer.py'
receiver_path = root / 'engines/understand-operator/uo/scripts/receiver_type_facts.py'
call_graph_path = root / 'engines/understand-operator/uo/scripts/function_call_graph.py'
test_path = root / 'engines/understand-operator/tests/test_selector_type_resolution.py'

text = type_path.read_text()
text = text.replace(
"    marker = \"std::conditional<\"\n    start = value.find(marker)\n",
"    marker = \"std::conditional_t<\"\n    start = value.find(marker)\n    alias_form = start >= 0\n    if start < 0:\n        marker = \"conditional_t<\"\n        start = value.find(marker)\n        alias_form = start >= 0\n    if start < 0:\n        marker = \"std::conditional<\"\n        start = value.find(marker)\n        alias_form = False\n",
)
text = text.replace(
"    if start < 0:\n        marker = \"conditional<\"\n        start = value.find(marker)\n    if start < 0:\n        return set()\n",
"    if start < 0:\n        marker = \"conditional<\"\n        start = value.find(marker)\n        alias_form = False\n    if start < 0:\n        return set()\n",
)
text = text.replace(
"    if suffix not in {\"::type\", \"::type_t\", \"\"}:\n        return set()\n",
"    if alias_form:\n        if suffix:\n            return set()\n    elif suffix not in {\"::type\", \"::type_t\", \"\"}:\n        return set()\n",
)
text = text.replace(
'r"\\b(?:class|struct)\\s+(?P<name>[A-Za-z_]\\w*)(?:\\s*<[^\\{;]+>)?\\b[^\\{;]*\\{"',
'r"\\b(?:class|struct)\\s+(?P<name>[A-Za-z_]\\w*)(?:\\s*<[^\\{;]+>)?[^\\{;]*\\{"',
)
type_path.write_text(text)

r = receiver_path.read_text()
anchor = "def _unique_return_type(\n"
helper = '''def _expanded_receiver_candidates(receiver_type: str, facts: ReceiverTypeFacts) -> set[str]:
    current = {receiver_type} if receiver_type else set()
    for _ in range(4):
        next_values: set[str] = set()
        for item in current:
            expanded = expand_type_candidates(item, facts.type_aliases, max_depth=2)
            for value in expanded:
                next_values.update(expand_nested_member_candidates(value, facts.member_type_aliases))
        next_values = {normalize_declared_type(item) for item in next_values if normalize_declared_type(item)}
        if not next_values or next_values == current:
            break
        current = next_values
    return current


'''
if '_expanded_receiver_candidates' not in r:
    r = r.replace(anchor, helper + anchor)
r = r.replace(
"    receiver_candidates = expand_type_candidates(receiver_type, facts.type_aliases, max_depth=2)\n    nested: set[str] = set()\n    for item in receiver_candidates:\n        nested.update(expand_nested_member_candidates(item, facts.member_type_aliases))\n    receiver_candidates = nested or receiver_candidates\n",
"    receiver_candidates = _expanded_receiver_candidates(receiver_type, facts)\n",
)
r = r.replace(
"    candidates = expand_type_candidates(receiver_type, facts.type_aliases, max_depth=2)\n    nested: set[str] = set()\n    for item in candidates:\n        nested.update(expand_nested_member_candidates(item, facts.member_type_aliases))\n    candidates = nested or candidates\n",
"    candidates = _expanded_receiver_candidates(receiver_type, facts)\n",
)
receiver_path.write_text(r)

cg = call_graph_path.read_text()
cg = cg.replace(
"    legacy = _legacy_receiver_type(site, caller, facts)\n    if _receiver_type_supported(site, structured, facts):\n",
"    legacy = _legacy_receiver_type(site, caller, facts)\n    if _receiver_type_matches_official(site, legacy, facts):\n        return legacy\n    if _receiver_type_supported(site, structured, facts):\n",
)
helper2 = '''def _receiver_type_matches_official(
    site: CallSite, receiver_type: str, facts: CallResolutionFacts
) -> bool:
    if not receiver_type:
        return False
    for contract in facts.official_contracts.get(site.callee_name, []):
        counts = {int(value) for value in contract.get("argument_counts") or []}
        if counts and site.argument_count not in counts:
            continue
        allowed = [str(value or "") for value in contract.get("receiver_types") or []]
        if allowed and any(_type_matches_scope(receiver_type, value) for value in allowed):
            return True
    return False


'''
if 'def _receiver_type_matches_official' not in cg:
    cg = cg.replace('def _receiver_type_supported(\n', helper2 + 'def _receiver_type_supported(\n')
call_graph_path.write_text(cg)

test_path.write_text('''from uo.scripts.type_normalizer import (
    collect_member_type_aliases,
    expand_nested_member_candidates,
    expand_type_candidates,
)


def test_conditional_t_expands_without_type_suffix() -> None:
    assert expand_type_candidates(
        'std::conditional_t<FLAG, Buffer<int>, std::nullptr_t>', {}, max_depth=2
    ) == {'Buffer<int>', 'std::nullptr_t'}


def test_real_selector_shape_expands_member_alias() -> None:
    source = """
    template <uint8_t A, uint8_t B>
    struct QL1BuffSelector {
      using TYPE = std::conditional_t<A, PolicyDB<int>, PolicySingle<int>>;
    };
    """
    aliases = collect_member_type_aliases({'x.h': source})
    member = expand_nested_member_candidates('QL1BuffSelector<X,Y>::TYPE', aliases)
    assert member == {'std::conditional_t<A,PolicyDB<int>,PolicySingle<int>>'}
    leaves = set()
    for item in member:
        leaves.update(expand_type_candidates(item, {}, max_depth=2))
    assert leaves == {'PolicyDB<int>', 'PolicySingle<int>'}
''')
