from pathlib import Path

root = Path(__file__).resolve().parents[1]
type_path = root / 'engines/understand-operator/uo/scripts/type_normalizer.py'
receiver_path = root / 'engines/understand-operator/uo/scripts/receiver_type_facts.py'
test_path = root / 'engines/understand-operator/tests/test_nested_type_resolution.py'

text = type_path.read_text()
text = text.replace('from typing import Mapping', 'from typing import Mapping')
append = r'''

_MEMBER_ALIAS_RE = re.compile(r"\b(?:using\s+([A-Za-z_]\w*)\s*=\s*([^;]+)|typedef\s+([^;]+?)\s+([A-Za-z_]\w*))\s*;", re.DOTALL)
_TEMPLATE_CLASS_RE = re.compile(
    r"template\s*<(?P<params>[^>]+)>\s*(?:class|struct)\s+(?P<name>[A-Za-z_]\w*)\b[^\{;]*\{",
    re.DOTALL,
)
_CLASS_RE = re.compile(r"\b(?:class|struct)\s+(?P<name>[A-Za-z_]\w*)(?:\s*<[^\{;]+>)?\b[^\{;]*\{")


def collect_member_type_aliases(source_texts: Mapping[object, str] | None) -> dict[tuple[str, str], set[str]]:
    out: dict[tuple[str, str], set[str]] = {}
    for raw in (source_texts or {}).values():
        source = _strip_comments(str(raw or ''))
        for match in _CLASS_RE.finditer(source):
            end = _matching_brace(source, match.end() - 1)
            if end is None:
                continue
            owner = match.group('name')
            body = source[match.end():end]
            for alias in _MEMBER_ALIAS_RE.finditer(body):
                if alias.group(1):
                    name, expr = alias.group(1), alias.group(2)
                else:
                    name, expr = alias.group(4), alias.group(3)
                value = normalize_declared_type(expr)
                if value:
                    out.setdefault((owner, name), set()).add(value)
    return out


def collect_template_parameters(source_texts: Mapping[object, str] | None) -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for raw in (source_texts or {}).values():
        source = _strip_comments(str(raw or ''))
        for match in _TEMPLATE_CLASS_RE.finditer(source):
            params: list[str] = []
            for clause in _split_top_level(match.group('params'), ','):
                names = re.findall(r"[A-Za-z_]\w*", clause)
                if names:
                    params.append(names[-1])
            if params:
                out.setdefault(match.group('name'), tuple(params))
    return out


def expand_nested_member_candidates(
    type_name: str,
    member_aliases: Mapping[tuple[str, str], set[str]] | None,
) -> set[str]:
    value = normalize_declared_type(type_name)
    match = re.match(r"^(?P<owner>[A-Za-z_]\w*)(?:<.*>)?::(?P<member>[A-Za-z_]\w*)$", value)
    if not match:
        return {value} if value else set()
    found = set((member_aliases or {}).get((match.group('owner'), match.group('member')), set()))
    return found or {value}


def substitute_template_arguments(
    type_name: str,
    receiver_type: str,
    owner: str,
    template_parameters: Mapping[str, tuple[str, ...]] | None,
) -> str:
    result = normalize_declared_type(type_name)
    recv = normalize_declared_type(receiver_type)
    marker = owner + '<'
    if not recv.startswith(marker) or not recv.endswith('>'):
        return result
    params = tuple((template_parameters or {}).get(owner, ()))
    if not params:
        return result
    args = _split_top_level(recv[len(marker):-1], ',')
    if len(args) != len(params):
        return result
    for param, arg in zip(params, args):
        result = re.sub(rf"\b{re.escape(param)}\b", normalize_declared_type(arg), result)
    return result


def _matching_brace(text: str, open_pos: int) -> int | None:
    depth = 0
    quote = ''
    escape = False
    for index in range(open_pos, len(text)):
        ch = text[index]
        if quote:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == quote:
                quote = ''
            continue
        if ch in {'"', "'"}:
            quote = ch
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return index
    return None
'''
if 'def collect_member_type_aliases' not in text:
    text += append
type_path.write_text(text)

r = receiver_path.read_text()
r = r.replace(
"    canonical_base, collect_type_aliases, expand_type_candidates, normalize_declared_type,\n",
"    canonical_base, collect_member_type_aliases, collect_template_parameters, collect_type_aliases,\n    expand_nested_member_candidates, expand_type_candidates, normalize_declared_type,\n    substitute_template_arguments,\n",
)
r = r.replace(
"    type_aliases: dict[str, set[str]] = field(default_factory=dict)\n",
"    type_aliases: dict[str, set[str]] = field(default_factory=dict)\n    member_type_aliases: dict[tuple[str, str], set[str]] = field(default_factory=dict)\n    template_parameters: dict[str, tuple[str, ...]] = field(default_factory=dict)\n",
)
r = r.replace(
"    facts.type_aliases = collect_type_aliases(source_texts)\n",
"    facts.type_aliases = collect_type_aliases(source_texts)\n    facts.member_type_aliases = collect_member_type_aliases(source_texts)\n    facts.template_parameters = collect_template_parameters(source_texts)\n",
)
r = r.replace(
"    receiver_candidates = expand_type_candidates(receiver_type, facts.type_aliases, max_depth=2)\n    owner_candidates = {_normalize_type_name(item) for item in receiver_candidates if _normalize_type_name(item)}\n    for owner in owner_candidates:\n        candidates.update(facts.return_types_by_method.get((owner, method, argument_count), set()))\n",
"    receiver_candidates = expand_type_candidates(receiver_type, facts.type_aliases, max_depth=2)\n    nested: set[str] = set()\n    for item in receiver_candidates:\n        nested.update(expand_nested_member_candidates(item, facts.member_type_aliases))\n    receiver_candidates = nested or receiver_candidates\n    owner_candidates = {_normalize_type_name(item) for item in receiver_candidates if _normalize_type_name(item)}\n    for receiver_candidate in receiver_candidates:\n        owner = _normalize_type_name(receiver_candidate)\n        for raw_return in facts.return_types_by_method.get((owner, method, argument_count), set()):\n            candidates.add(substitute_template_arguments(\n                raw_return, receiver_candidate, owner, facts.template_parameters\n            ))\n",
)
r = r.replace(
"    candidates = expand_type_candidates(receiver_type, facts.type_aliases, max_depth=2)\n",
"    candidates = expand_type_candidates(receiver_type, facts.type_aliases, max_depth=2)\n    nested: set[str] = set()\n    for item in candidates:\n        nested.update(expand_nested_member_candidates(item, facts.member_type_aliases))\n    candidates = nested or candidates\n",
1)
receiver_path.write_text(r)

test_path.write_text(r'''from uo.scripts.type_normalizer import (
    collect_member_type_aliases,
    collect_template_parameters,
    expand_nested_member_candidates,
    substitute_template_arguments,
)


def test_selector_member_type_collects_specialization_candidates() -> None:
    source = '''
    template <bool F> struct Selector;
    template <> struct Selector<true> { using TYPE = Buffer<int>; };
    template <> struct Selector<false> { using TYPE = std::nullptr_t; };
    '''
    aliases = collect_member_type_aliases({'x.h': source})
    assert expand_nested_member_candidates('Selector<FLAG>::TYPE', aliases) == {
        'Buffer<int>', 'std::nullptr_t'
    }


def test_template_argument_substitution_is_owner_scoped() -> None:
    source = 'template <typename T, class U> class Policy { };'
    params = collect_template_parameters({'x.h': source})
    assert params['Policy'] == ('T', 'U')
    assert substitute_template_arguments(
        'Buffer<T,U>', 'Policy<int,float>', 'Policy', params
    ) == 'Buffer<int,float>'
''')
