from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engines" / "understand-operator"

# ---------------------------------------------------------------------------
# Multi-line preprocessor macro indexing.
# ---------------------------------------------------------------------------
macro = ENGINE / "uo" / "scripts" / "macro_regions.py"
text = macro.read_text(encoding="utf-8")
text = text.replace(
    "    variadic: bool = False\n",
    "    variadic: bool = False\n    end_line: int = 0\n",
    1,
)
helper = r'''

def _logical_preprocessor_lines(text: str) -> tuple[list[str], list[int]]:
    """Join backslash-continued directives while preserving physical line indexes."""
    physical = text.splitlines()
    logical = list(physical)
    end_lines = [idx + 1 for idx in range(len(physical))]
    idx = 0
    while idx < len(physical):
        raw = physical[idx]
        if not re.match(r"^\s*#", raw):
            idx += 1
            continue
        end = idx
        joined = raw
        while re.search(r"\\\s*$", joined) and end + 1 < len(physical):
            joined = re.sub(r"\\\s*$", " ", joined) + physical[end + 1].lstrip()
            end += 1
        if end > idx:
            logical[idx] = joined
            end_lines[idx] = end + 1
            for continuation in range(idx + 1, end + 1):
                logical[continuation] = ""
                end_lines[continuation] = end + 1
            idx = end + 1
        else:
            idx += 1
    return logical, end_lines


def _macro_expansion_symbols(body: str, parameters: tuple[str, ...]) -> list[str]:
    """Return deterministic call-like symbols referenced by a macro body."""
    parameter_names = {value.rstrip(".") for value in parameters}
    noise = {
        "if", "for", "while", "switch", "sizeof", "decltype", "static_cast",
        "reinterpret_cast", "const_cast", "dynamic_cast", "return",
    }
    found: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"\b([A-Za-z_]\w*)\s*(?:<[^;{}()]{0,240}>)?\s*\(", body):
        name = match.group(1)
        if name in parameter_names or name in noise or name in seen:
            continue
        seen.add(name)
        found.append(name)
    return found
'''
marker = "\n\ndef analyze_macros(\n"
if "def _logical_preprocessor_lines(" not in text:
    if marker not in text:
        raise SystemExit("macro helper marker missing")
    text = text.replace(marker, helper + marker, 1)
text = text.replace(
    "    lines = text.splitlines()\n    n = len(lines)\n",
    "    lines, logical_end_lines = _logical_preprocessor_lines(text)\n    n = len(lines)\n",
    1,
)
old = '''                function_macros[name] = {
                    "name": name,
                    "parameters": list(params),
                    "variadic": variadic,
                    "body": body,
                    "line": line_no,
                }
'''
new = '''                end_line = logical_end_lines[idx]
                function_macros[name] = {
                    "name": name,
                    "parameters": list(params),
                    "variadic": variadic,
                    "body": body,
                    "line": line_no,
                    "end_line": end_line,
                    "expands_to_symbols": _macro_expansion_symbols(body, params),
                }
'''
if old not in text:
    raise SystemExit("function macro payload marker missing")
text = text.replace(old, new, 1)
old = '''                        parameters=params, function_like=True, variadic=variadic,
                    )
'''
new = '''                        parameters=params, function_like=True, variadic=variadic,
                        end_line=end_line,
                    )
'''
if old not in text:
    raise SystemExit("macro directive marker missing")
text = text.replace(old, new, 1)
macro.write_text(text, encoding="utf-8")

# ---------------------------------------------------------------------------
# Preserve detailed source macro definitions on graph nodes.
# ---------------------------------------------------------------------------
graph = ENGINE / "uo" / "scripts" / "function_call_graph.py"
text = graph.read_text(encoding="utf-8")
text = text.replace(
    "    source_macros: set[str] = field(default_factory=set)\n",
    "    source_macros: set[str] = field(default_factory=set)\n"
    "    source_macro_definitions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)\n",
    1,
)
old = '''        info = analyze_macros(source)
        facts.source_macros.update(info.function_macros)
        namespaces = {m.group(1) for m in _USING_NAMESPACE_RE.finditer(source)}
'''
new = '''        info = analyze_macros(source)
        facts.source_macros.update(info.function_macros)
        for macro_name, definition in info.function_macros.items():
            payload = dict(definition)
            payload["file_path"] = rel
            facts.source_macro_definitions.setdefault(macro_name, []).append(payload)
        namespaces = {m.group(1) for m in _USING_NAMESPACE_RE.finditer(source)}
'''
if old not in text:
    raise SystemExit("source macro collection marker missing")
text = text.replace(old, new, 1)
old = '''        return _emit_target(
            site, caller, site_id, site_node, base_edge,
            node_type="CompileMacro", status="macro", reason=reason, confidence=confidence,
        )
'''
new = '''        return _emit_target(
            site, caller, site_id, site_node, base_edge,
            node_type="CompileMacro", status="macro", reason=reason, confidence=confidence,
            source_definitions=facts.source_macro_definitions.get(name),
        )
'''
if old not in text:
    raise SystemExit("source macro emit marker missing")
text = text.replace(old, new, 1)
text = text.replace(
    "    contract: dict[str, Any] | None = None,\n) -> tuple[dict[str, Any], dict[str, Any], None]:\n",
    "    contract: dict[str, Any] | None = None,\n"
    "    source_definitions: list[dict[str, Any]] | None = None,\n"
    ") -> tuple[dict[str, Any], dict[str, Any], None]:\n",
    1,
)
old = '''    if contract:
        target_node["official_contract"] = {
'''
new = '''    if source_definitions:
        target_node["source_macro_definitions"] = [
            {
                "file_path": item.get("file_path"),
                "line": item.get("line"),
                "end_line": item.get("end_line"),
                "parameters": item.get("parameters") or [],
                "variadic": bool(item.get("variadic")),
                "expands_to_symbols": item.get("expands_to_symbols") or [],
                "body": item.get("body") or "",
            }
            for item in source_definitions
        ]
    if contract:
        target_node["official_contract"] = {
'''
if old not in text:
    raise SystemExit("target metadata marker missing")
text = text.replace(old, new, 1)
graph.write_text(text, encoding="utf-8")

# ---------------------------------------------------------------------------
# Feed repository-local include closure into kernel extraction.
# ---------------------------------------------------------------------------
kernel = ENGINE / "uo" / "scripts" / "extract_kernel_subgraph.py"
text = kernel.read_text(encoding="utf-8")
import_marker = "from uo.scripts.resolve_entrypoints import entrypoint_units, load_entrypoint_graph\n"
if "source_include_closure import" not in text:
    text = text.replace(
        import_marker,
        import_marker + "from uo.scripts.source_include_closure import expand_local_include_closure\n",
        1,
    )
old = '''    kernel_files = _kernel_files(repo_root, op_name, architecture, primary if primary else None, kernel_nodes)
    domain_files = list(
        dict.fromkeys(_enum_declaration_files(repo_root, op_name, architecture) + kernel_files)
    )
'''
new = '''    kernel_seed_files = _kernel_files(
        repo_root, op_name, architecture, primary if primary else None, kernel_nodes
    )
    include_closure = expand_local_include_closure(
        repo_root, kernel_seed_files, architecture=architecture
    )
    kernel_files = include_closure.files
    domain_files = list(
        dict.fromkeys(_enum_declaration_files(repo_root, op_name, architecture) + kernel_files)
    )
    for item in include_closure.unresolved:
        if item.get("kind") in {
            "include_target_ambiguous", "include_closure_file_budget",
            "include_closure_depth_budget", "include_read_failed",
        }:
            unresolved.append(
                {
                    "id": stable_id("UNRES_INCLUDE_", repr(sorted(item.items()))),
                    "kind": item.get("kind"),
                    "message": "Repository-local include closure could not be completed safely",
                    **item,
                }
            )
'''
if old not in text:
    raise SystemExit("kernel file scope marker missing")
text = text.replace(old, new, 1)
old = '''        "loaded_tiling_fields": sorted(loaded_fields | enum_fields_resolved),
        "function_definitions": [fn.as_dict() for fn in all_functions],
        "unresolved": unresolved,
'''
new = '''        "loaded_tiling_fields": sorted(loaded_fields | enum_fields_resolved),
        "source_scope": include_closure.as_dict(repo_root),
        "function_definitions": [fn.as_dict() for fn in all_functions],
        "unresolved": unresolved,
'''
if old not in text:
    raise SystemExit("kernel payload marker missing")
text = text.replace(old, new, 1)
kernel.write_text(text, encoding="utf-8")

# ---------------------------------------------------------------------------
# Official scalar CeilDivision contract. Do not conflate with tensor Ceil or
# project helper Ceil<T>(a, b).
# ---------------------------------------------------------------------------
catalog = ENGINE / "uo" / "resources" / "cann_api_catalog.yaml"
text = catalog.read_text(encoding="utf-8")
if "symbol_or_macro: CeilDivision" not in text:
    text += '''
- symbol_or_macro: CeilDivision
  symbol_kind: function
  call_style: free_function
  qualified_names: [AscendC::CeilDivision]
  receiver_types: []
  argument_counts: [2]
  allow_unqualified: true
  document_title: CeilDivision - scalar integer ceiling division
  document_url: https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900beta2/API/ascendcopapi/atlasascendc_api_07_00265.html
  semantic_summary: Computes integer ceiling division for two scalar integer arguments.
  source_authority: official_hiascend
  version_scope: multi_version
  cann_versions: ['9.0', '9.1']
  confidence: 1.0
'''
    catalog.write_text(text, encoding="utf-8")

# ---------------------------------------------------------------------------
# Regression tests.
# ---------------------------------------------------------------------------
test_macro = ENGINE / "tests" / "test_macro_regions.py"
t = test_macro.read_text(encoding="utf-8")
addition = r'''

def test_multiline_function_macro_is_one_definition() -> None:
    text = """#define INVOKE_IMPL(T, FLAG) \\
    Kernel<T>(FLAG); \\
    SyncAll();
void Run() { INVOKE_IMPL(float, true); }
"""
    info = analyze_macros(text)
    macro = info.function_macros["INVOKE_IMPL"]
    assert macro["line"] == 1
    assert macro["end_line"] == 3
    assert macro["parameters"] == ["T", "FLAG"]
    assert macro["expands_to_symbols"] == ["Kernel", "SyncAll"]
'''
if "test_multiline_function_macro_is_one_definition" not in t:
    t += addition
    test_macro.write_text(t, encoding="utf-8")

test_calls = ENGINE / "tests" / "test_call_external_classification.py"
t = test_calls.read_text(encoding="utf-8")
addition = r'''

def test_multiline_source_macro_keeps_compact_expansion_metadata() -> None:
    caller = _fn("void Run() { INVOKE_IMPL(float, true); }")
    source = """#define INVOKE_IMPL(T, FLAG) \\
    Kernel<T>(FLAG); \\
    SyncAll();
""" + caller.body_text
    facts = collect_call_resolution_facts(
        [caller], source_texts={"op_kernel/test.cpp": source}
    )
    edge, _node, unresolved = resolve_call_site(
        _site("INVOKE_IMPL", argc=2), caller, by_name={}, by_qn={}, by_id={}, facts=facts
    )
    assert edge and edge["target_status"] == "macro"
    definition = edge["_target_node"]["source_macro_definitions"][0]
    assert definition["end_line"] == 3
    assert definition["expands_to_symbols"] == ["Kernel", "SyncAll"]
    assert unresolved is None
'''
if "test_multiline_source_macro_keeps_compact_expansion_metadata" not in t:
    t += addition
    test_calls.write_text(t, encoding="utf-8")

test_catalog = ENGINE / "tests" / "test_cann_api_catalog.py"
t = test_catalog.read_text(encoding="utf-8")
addition = '''

def test_scalar_ceil_division_is_official_but_tensor_ceil_is_not_aliased() -> None:
    contracts = load_packaged_contracts()
    contract = contracts["CeilDivision"]
    assert contract["argument_counts"] == [2]
    assert contract["qualified_names"] == ["AscendC::CeilDivision"]
    assert "Ceil" not in contract.get("aliases", [])
'''
if "test_scalar_ceil_division_is_official_but_tensor_ceil_is_not_aliased" not in t:
    t += addition
    test_catalog.write_text(t, encoding="utf-8")

print("patched deterministic source symbol closure")
