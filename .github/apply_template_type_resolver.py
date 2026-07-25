from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "engines/understand-operator/uo/scripts"
TESTS = ROOT / "engines/understand-operator/tests"

normalizer = r'''"""Conservative C++ type-alias and template normalization."""
from __future__ import annotations

import re
from typing import Mapping

_ALIAS_RE = re.compile(
    r"\busing\s+([A-Za-z_]\w*)\s*=\s*([^;]+);|"
    r"\btypedef\s+([^;]+?)\s+([A-Za-z_]\w*)\s*;",
    re.DOTALL,
)


def collect_type_aliases(source_texts: Mapping[object, str] | None) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = {}
    for text in (source_texts or {}).values():
        source = _strip_comments(str(text or ""))
        for match in _ALIAS_RE.finditer(source):
            if match.group(1):
                name, expression = match.group(1), match.group(2)
            else:
                name, expression = match.group(4), match.group(3)
            normalized = normalize_declared_type(expression)
            if normalized:
                aliases.setdefault(name, set()).add(normalized)
    return aliases


def expand_type_candidates(
    type_name: str,
    aliases: Mapping[str, set[str]] | None = None,
    *,
    max_depth: int = 2,
) -> set[str]:
    seed = normalize_declared_type(type_name)
    if not seed:
        return set()
    current = {seed}
    seen = set(current)
    for _ in range(max(0, max_depth)):
        changed = False
        next_values: set[str] = set()
        for value in current:
            expanded = _expand_once(value, aliases or {})
            next_values.update(expanded)
            if expanded != {value}:
                changed = True
        next_values = {normalize_declared_type(item) for item in next_values if normalize_declared_type(item)}
        seen.update(next_values)
        current = next_values or current
        if not changed:
            break
    leaves = {value for value in current if value}
    return leaves or seen


def canonical_base(type_name: str) -> str:
    text = normalize_declared_type(type_name)
    if not text:
        return ""
    depth = 0
    out: list[str] = []
    for ch in text:
        if ch == "<":
            depth += 1
            continue
        if ch == ">":
            depth = max(0, depth - 1)
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out).split("::")[-1]


def normalize_declared_type(type_name: str) -> str:
    text = str(type_name or "").strip()
    text = re.sub(r"\b(?:const|volatile|static|mutable|typename|struct|class|register|extern)\b", " ", text)
    text = re.sub(r"\s+", "", text)
    return text.strip("*& ")


def _expand_once(value: str, aliases: Mapping[str, set[str]]) -> set[str]:
    base = canonical_base(value)
    if base in aliases:
        return set(aliases[base])
    conditional = _conditional_branches(value)
    if conditional:
        return conditional
    return {value}


def _conditional_branches(value: str) -> set[str]:
    marker = "std::conditional<"
    start = value.find(marker)
    if start < 0:
        marker = "conditional<"
        start = value.find(marker)
    if start < 0:
        return set()
    open_pos = start + len(marker) - 1
    close_pos = _matching_angle(value, open_pos)
    if close_pos is None:
        return set()
    suffix = value[close_pos + 1 :]
    if suffix not in {"::type", "::type_t", ""}:
        return set()
    args = _split_top_level(value[open_pos + 1 : close_pos], ",")
    if len(args) != 3:
        return set()
    return {normalize_declared_type(args[1]), normalize_declared_type(args[2])} - {""}


def _matching_angle(text: str, open_pos: int) -> int | None:
    depth = 0
    for index in range(open_pos, len(text)):
        if text[index] == "<":
            depth += 1
        elif text[index] == ">":
            depth -= 1
            if depth == 0:
                return index
    return None


def _split_top_level(text: str, delimiter: str) -> list[str]:
    out: list[str] = []
    start = 0
    depths = {"(": 0, "[": 0, "{": 0, "<": 0}
    pairs = {")": "(", "]": "[", "}": "{", ">": "<"}
    for index, ch in enumerate(text):
        if ch in depths:
            depths[ch] += 1
        elif ch in pairs:
            key = pairs[ch]
            depths[key] = max(0, depths[key] - 1)
        elif ch == delimiter and not any(depths.values()):
            out.append(text[start:index])
            start = index + 1
    out.append(text[start:])
    return out


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", " ", text)
'''
(SCRIPTS / "type_normalizer.py").write_text(normalizer, encoding="utf-8")

path = SCRIPTS / "receiver_type_facts.py"
text = path.read_text(encoding="utf-8")
text = text.replace(
    "from uo.scripts.function_body import CallSite, FunctionDefinition\n",
    "from uo.scripts.function_body import CallSite, FunctionDefinition\n"
    "from uo.scripts.type_normalizer import (\n"
    "    canonical_base, collect_type_aliases, expand_type_candidates, normalize_declared_type,\n"
    ")\n",
)
text = text.replace(
    "    return_types_by_name: dict[tuple[str, int], set[str]] = field(default_factory=dict)\n",
    "    return_types_by_name: dict[tuple[str, int], set[str]] = field(default_factory=dict)\n"
    "    type_aliases: dict[str, set[str]] = field(default_factory=dict)\n",
)
text = text.replace(
    "    facts = ReceiverTypeFacts()\n    source_by_rel =",
    "    facts = ReceiverTypeFacts()\n    facts.type_aliases = collect_type_aliases(source_texts)\n    source_by_rel =",
)
old = '''    for assignment in assignments:
        receiver_type = _lookup_receiver_expression(
            assignment.receiver,
            assignment.function_id,
            assignment.caller_class,
            assignment.line,
            facts,
        )
        return_type = _unique_return_type(
            receiver_type,
            assignment.method,
            assignment.argument_count,
            facts,
            official_contracts or {},
        )
        if return_type:
            facts.add_binding(
                assignment.function_id,
                TypeBinding(assignment.name, return_type, assignment.line, "one_hop_return"),
            )
'''
new = '''    pending = list(assignments)
    for propagation_depth in range(2):
        next_pending: list[_AutoAssignment] = []
        progress = False
        for assignment in pending:
            receiver_type = _lookup_receiver_expression(
                assignment.receiver,
                assignment.function_id,
                assignment.caller_class,
                assignment.line,
                facts,
            )
            return_type = _unique_return_type(
                receiver_type,
                assignment.method,
                assignment.argument_count,
                facts,
                official_contracts or {},
            )
            if return_type:
                facts.add_binding(
                    assignment.function_id,
                    TypeBinding(
                        assignment.name,
                        return_type,
                        assignment.line,
                        "one_hop_return" if propagation_depth == 0 else "two_hop_return",
                    ),
                )
                progress = True
            else:
                next_pending.append(assignment)
        pending = next_pending
        if not progress or not pending:
            break
'''
if old not in text:
    raise SystemExit("assignment block not found")
text = text.replace(old, new)
old = '''    return _lookup_receiver_expression(
        receiver,
        caller.stable_id,
        caller.class_or_namespace,
        site.line,
        facts,
    )
'''
new = '''    receiver_type = _lookup_receiver_expression(
        receiver,
        caller.stable_id,
        caller.class_or_namespace,
        site.line,
        facts,
    )
    return _narrow_receiver_type(
        receiver_type,
        site.callee_name,
        site.argument_count,
        facts,
        official_contracts or {},
    )
'''
if old not in text:
    raise SystemExit("infer return block not found")
text = text.replace(old, new, 1)
old = '''    candidates: set[str] = set()
    owner = _normalize_type_name(receiver_type)
    if owner:
        candidates.update(facts.return_types_by_method.get((owner, method, argument_count), set()))
'''
new = '''    candidates: set[str] = set()
    receiver_candidates = expand_type_candidates(receiver_type, facts.type_aliases, max_depth=2)
    owner_candidates = {_normalize_type_name(item) for item in receiver_candidates if _normalize_type_name(item)}
    for owner in owner_candidates:
        candidates.update(facts.return_types_by_method.get((owner, method, argument_count), set()))
'''
if old not in text:
    raise SystemExit("unique return owner block not found")
text = text.replace(old, new)
text = text.replace(
    "        if allowed and (not receiver_type or not any(_type_matches(receiver_type, item) for item in allowed)):\n",
    "        if allowed and (not receiver_candidates or not any(\n"
    "            _type_matches(candidate, item) for candidate in receiver_candidates for item in allowed\n"
    "        )):\n",
)
insert_before = "\ndef _collect_class_members(text: str, facts: ReceiverTypeFacts) -> None:\n"
helper = r'''

def _narrow_receiver_type(
    receiver_type: str,
    method: str,
    argument_count: int,
    facts: ReceiverTypeFacts,
    official_contracts: Mapping[str, list[dict[str, Any]]],
) -> str:
    candidates = expand_type_candidates(receiver_type, facts.type_aliases, max_depth=2)
    if not candidates:
        return receiver_type
    supported: set[str] = set()
    for candidate in candidates:
        owner = _normalize_type_name(candidate)
        if facts.return_types_by_method.get((owner, method, argument_count)):
            supported.add(candidate)
            continue
        for contract in official_contracts.get(method, []):
            counts = {int(value) for value in contract.get("argument_counts") or []}
            if counts and argument_count not in counts:
                continue
            allowed = [str(value or "") for value in contract.get("receiver_types") or []]
            if allowed and any(_type_matches(candidate, item) for item in allowed):
                supported.add(candidate)
                break
    bases = {canonical_base(item) for item in supported if canonical_base(item)}
    if len(bases) == 1 and supported:
        return sorted(supported, key=lambda value: (len(value), value))[0]
    all_bases = {canonical_base(item) for item in candidates if canonical_base(item)}
    if len(all_bases) == 1:
        return sorted(candidates, key=lambda value: (len(value), value))[0]
    return receiver_type
'''
if insert_before not in text:
    raise SystemExit("collect class marker not found")
text = text.replace(insert_before, helper + insert_before)
text = text.replace(
    "def _normalize_declared_type(type_name: str) -> str:\n    text = str(type_name or \"\").strip()\n    text = re.sub(r\"\\b(?:const|volatile|static|mutable|typename|struct|class|register|extern)\\b\", \" \", text)\n    text = re.sub(r\"\\s+\", \"\", text)\n    return text.strip(\"*& \")\n",
    "def _normalize_declared_type(type_name: str) -> str:\n    return normalize_declared_type(type_name)\n",
)
path.write_text(text, encoding="utf-8")

test = r'''from uo.scripts.type_normalizer import collect_type_aliases, expand_type_candidates
from uo.scripts.receiver_type_facts import build_receiver_type_facts
from uo.scripts.function_body import FunctionDefinition


def _fn(name: str, owner: str, header: str, body: str, stable_id: str) -> FunctionDefinition:
    return FunctionDefinition(
        name=name, qualified_name=f"{owner}::{name}", class_or_namespace=owner,
        normalized_signature="()", template_arity_or_signature="", specialization_kind="none",
        file_path="op_kernel/test.h", start_line=1, end_line=body.count("\n") + 1,
        header_text=header, body_text=body, source_hash="s", snippet_hash="h",
        identity_key=f"IK_{stable_id}", stable_id=stable_id,
    )


def test_alias_and_conditional_expansion_is_bounded() -> None:
    source = "using Chosen = std::conditional<FLAG, Buffer<int>, std::nullptr_t>::type;"
    aliases = collect_type_aliases({"x.h": source})
    assert expand_type_candidates("Chosen", aliases, max_depth=2) == {"Buffer<int>", "std::nullptr_t"}


def test_two_round_return_propagation_binds_second_auto() -> None:
    source = """
class Leaf { public: void Run() {} };
class Mid { public: Leaf &GetLeaf() { return leaf_; } private: Leaf leaf_; };
class Root { public: Mid &GetMid() { return mid_; } private: Mid mid_; };
class Driver { public: void Go(Root &root) {
  auto &mid = root.GetMid();
  auto &leaf = mid.GetLeaf();
  leaf.Run();
}};
"""
    go = _fn("Go", "Driver", "void Driver::Go(Root &root) {", "void Driver::Go(Root &root) {\n auto &mid=root.GetMid();\n auto &leaf=mid.GetLeaf();\n leaf.Run();\n}", "GO")
    get_mid = _fn("GetMid", "Root", "Mid &Root::GetMid() {", "Mid &Root::GetMid() { return mid_; }", "GM")
    get_leaf = _fn("GetLeaf", "Mid", "Leaf &Mid::GetLeaf() {", "Leaf &Mid::GetLeaf() { return leaf_; }", "GL")
    run = _fn("Run", "Leaf", "void Leaf::Run() {", "void Leaf::Run() {}", "RUN")
    facts = build_receiver_type_facts([go, get_mid, get_leaf, run], {"op_kernel/test.h": source})
    bindings = {item.name: item for item in facts.bindings_by_function[go.stable_id]}
    assert bindings["mid"].type_name == "Mid"
    assert bindings["leaf"].type_name == "Leaf"
    assert bindings["leaf"].source == "two_hop_return"
'''
(TESTS / "test_template_type_normalizer.py").write_text(test, encoding="utf-8")
