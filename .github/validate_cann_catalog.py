from collections import Counter
from pathlib import Path
import json

from uo.scripts.cann_doc_evidence import BUILTIN_CONTRACTS
from uo.scripts.function_body import iter_function_definitions
from uo.scripts.function_call_graph import build_call_edges_for_functions

roots = [p for p in Path('real-fag').rglob('flash_attention_score_grad') if p.is_dir()]
if not roots:
    raise SystemExit('flash_attention_score_grad directory not found')
root = min(roots, key=lambda p: len(p.parts))
files = []
for path in root.rglob('*'):
    if not path.is_file() or path.suffix.lower() not in {'.h', '.hpp', '.cpp', '.cc', '.cxx'}:
        continue
    parts = path.relative_to(root).parts
    if 'op_kernel' not in parts:
        continue
    arch_parts = {part for part in parts if part.startswith('arch') and part[4:].isdigit()}
    if arch_parts and 'arch35' not in arch_parts:
        continue
    files.append(path)
files.sort()

source_texts = {}
functions = []
for path in files:
    rel = path.relative_to(root).as_posix()
    text = path.read_text(encoding='utf-8', errors='ignore')
    source_texts[rel] = text
    functions.extend(iter_function_definitions(root, rel, architecture='arch35'))

unresolved = []
nodes, edges = build_call_edges_for_functions(
    functions,
    unresolved=unresolved,
    source_texts=source_texts,
    doc_evidence={'items': list(BUILTIN_CONTRACTS.values())},
)
status = Counter(str(edge.get('target_status') or '') for edge in edges)
reasons = Counter(str(edge.get('verification_source') or '') for edge in edges)
kinds = Counter(str(item.get('kind') or '') for item in unresolved)
missing_names = Counter(
    str(item.get('callee_name') or '')
    for item in unresolved
    if str(item.get('kind') or '') != 'call_target_ambiguous'
)
official_symbols = Counter(
    str(edge.get('callee_name') or '')
    for edge in edges
    if str(edge.get('verification_source') or '').startswith('official_contract:')
)
report = {
    'baseline_missing': 887,
    'operator_root': root.as_posix(),
    'architecture': 'arch35',
    'files': len(files),
    'functions': len(functions),
    'nodes': len(nodes),
    'edges': len(edges),
    'target_status': dict(status),
    'unresolved_kinds': dict(kinds),
    'verification_reasons': dict(reasons),
    'top_missing_callees': missing_names.most_common(60),
    'official_contract_symbols': official_symbols.most_common(),
    'official_contract_edges': sum(official_symbols.values()),
    'builtin_contract_count': len(BUILTIN_CONTRACTS),
    'missing_reduction': 887 - int(status.get('missing', 0)),
}
Path('cann-api-catalog-validation.json').write_text(
    json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8'
)
print(json.dumps(report, indent=2, ensure_ascii=False))

assert status.get('missing', 0) < 587, status
assert report['official_contract_edges'] >= 300, report['official_contract_edges']
assert reasons.get('using_external_namespace_without_internal_definition', 0) == 0
assert reasons.get('api_style_symbol_without_internal_definition', 0) == 0
assert kinds.get('call_target_missing', 0) == 0
assert missing_names.get('Ceil', 0) > 0
assert missing_names.get('Min', 0) > 0
assert missing_names.get('Max', 0) > 0
assert missing_names.get('LoadDataToL0A', 0) > 0
