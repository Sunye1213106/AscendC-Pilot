from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from uo.scripts.cann_doc_evidence import packaged_doc_evidence_bundle
from uo.scripts.function_body import iter_function_definitions
from uo.scripts.function_call_graph import build_call_edges_for_functions
from uo.scripts.source_include_closure import expand_local_include_closure


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    roots = [path for path in repo.rglob("flash_attention_score_grad") if path.is_dir()]
    if not roots:
        raise SystemExit("operator root missing")
    op_root = min(roots, key=lambda path: len(path.parts))
    seed_files: list[Path] = []
    for path in op_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".h", ".hh", ".hpp", ".hxx", ".inc", ".c", ".cc", ".cpp", ".cxx"}:
            continue
        parts = path.relative_to(op_root).parts
        if "op_kernel" not in parts:
            continue
        arch_parts = {part.casefold() for part in parts if part.casefold().startswith("arch") and part[4:].isdigit()}
        if arch_parts and "arch35" not in arch_parts:
            continue
        seed_files.append(path.resolve())
    seed_files.sort()
    closure = expand_local_include_closure(repo, seed_files, architecture="arch35")

    functions = []
    texts: dict[str, str] = {}
    for path in closure.files:
        rel = path.relative_to(repo).as_posix()
        texts[rel] = path.read_text(encoding="utf-8", errors="ignore")
        functions.extend(iter_function_definitions(repo, rel, architecture="arch35"))

    unresolved: list[dict] = []
    nodes, edges = build_call_edges_for_functions(
        functions,
        unresolved=unresolved,
        source_texts=texts,
        doc_evidence=packaged_doc_evidence_bundle(cann_version="9.0"),
    )
    seed_rels = {path.relative_to(repo).as_posix() for path in seed_files}
    seed_ids = {fn.stable_id for fn in functions if fn.file_path in seed_rels}
    edges = [edge for edge in edges if edge.get("source") in seed_ids]
    unresolved = [item for item in unresolved if item.get("caller_function_id") in seed_ids]
    site_by_id = {str(node.get("id")): node for node in nodes if node.get("node_type") == "CallSite"}

    status = Counter(str(edge.get("target_status") or "") for edge in edges)
    kinds = Counter(str(item.get("kind") or "") for item in unresolved)
    symbols: dict[str, Counter] = defaultdict(Counter)
    receiver_types = Counter()
    for edge in edges:
        name = str(edge.get("callee_name") or "")
        state = str(edge.get("target_status") or "")
        symbols[name][state] += 1
        site = site_by_id.get(str(edge.get("call_site_id") or "")) or {}
        receiver = str(site.get("receiver_type") or "")
        if receiver:
            symbols[name]["typed_receiver"] += 1
            receiver_types[receiver] += 1
    top_candidates = sorted(
        ((name, counts.get("candidate_set", 0)) for name, counts in symbols.items()),
        key=lambda item: (-item[1], item[0]),
    )[:30]
    watched = ["Get", "GetTensor", "Init", "UnInit", "LoadDataToL0B", "LockProd", "LockCons"]
    report = {
        "seed_file_count": len(seed_files),
        "closure_file_count": len(closure.files),
        "function_count": len(functions),
        "edge_count": len(edges),
        "status": dict(status),
        "unresolved_kinds": dict(kinds),
        "watched": {name: dict(symbols.get(name, {})) for name in watched},
        "top_candidate_symbols": top_candidates,
        "top_receiver_types": receiver_types.most_common(30),
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
