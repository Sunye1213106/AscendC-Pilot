from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from uo.scripts.function_body import iter_function_definitions_from_text
from uo.scripts.function_call_graph import build_call_edges_for_functions, collect_call_resolution_facts
from uo.scripts.source_include_closure import expand_local_include_closure


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(args.repo).resolve()
    seeds = sorted(
        p for p in root.rglob('*')
        if p.is_file()
        and 'flash_attention_score_grad/op_kernel/arch35' in p.as_posix()
        and p.suffix.lower() in {'.h', '.hpp', '.cpp', '.cc'}
    )
    closure = expand_local_include_closure(root, seeds, architecture='arch35')
    texts = {p.relative_to(root).as_posix(): p.read_text(encoding='utf-8', errors='ignore') for p in closure.files}
    functions = []
    for rel, text in texts.items():
        functions.extend(iter_function_definitions_from_text(root, rel, text, architecture='arch35'))
    seed_rels = {p.relative_to(root).as_posix() for p in seeds}
    seed_functions = [fn for fn in functions if fn.file_path in seed_rels]
    facts = collect_call_resolution_facts(functions, source_texts=texts)
    unresolved = []
    nodes, edges = build_call_edges_for_functions(functions, unresolved=unresolved, facts=facts)
    seed_ids = {fn.stable_id for fn in seed_functions}
    seed_edges = [edge for edge in edges if edge.get('source') in seed_ids]
    status = Counter(str(edge.get('target_status') or '') for edge in seed_edges)
    unresolved_seed = [item for item in unresolved if item.get('caller_function_id') in seed_ids]
    kinds = Counter(str(item.get('kind') or '') for item in unresolved_seed)
    watched_names = {'Get', 'GetTensor', 'Init', 'UnInit', 'LoadDataToL0B', 'GetReused'}
    watched = defaultdict(Counter)
    node_by_id = {str(node.get('id')): node for node in nodes}
    for edge in seed_edges:
        name = str(edge.get('callee_name') or '')
        if name not in watched_names:
            continue
        watched[name][str(edge.get('target_status') or '')] += 1
        site = node_by_id.get(str(edge.get('call_site_id') or ''), {})
        if site.get('receiver_type'):
            watched[name]['typed_receiver'] += 1
    top = Counter(str(edge.get('callee_name') or '') for edge in seed_edges if edge.get('target_status') == 'candidate_set')
    payload = {
        'seed_file_count': len(seeds),
        'closure_file_count': len(closure.files),
        'function_count': len(functions),
        'edge_count': len(seed_edges),
        'status': dict(status),
        'unresolved_kinds': dict(kinds),
        'watched': {name: dict(values) for name, values in watched.items()},
        'top_candidate_symbols': top.most_common(30),
    }
    Path(args.output).write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
