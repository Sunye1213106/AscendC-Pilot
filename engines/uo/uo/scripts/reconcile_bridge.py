"""Typed TilingData / positional TilingKey bridge reconcile."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.semantic_identity import mint_edge_id, mint_field_identity

_NON_TILING_KEYS = frozenset(
    {
        "origdtypequery",
        "gcoretype",
        "mmidx",
        "splitaxis",
        "aic",
        "aiv",
    }
)
_NON_TILING_PREFIXES = ("origdtype",)
GET_TPL_CALL_RE = re.compile(r"GET_TPL_TILING_KEY\s*\(([^;]*)\)", re.DOTALL)


def reconcile_bridge(repo_root: Path, op_name: str) -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    host = read_yaml(uo_root / "ir" / "host_subgraph.yaml")
    kernel = read_yaml(uo_root / "ir" / "kernel_subgraph.yaml")
    tilingkey = read_yaml(uo_root / "ir" / "tilingkey_space.yaml")
    build_ev = read_yaml(uo_root / "ir" / "build_evidence.yaml")

    host_fields = _collect_typed_fields(host, side="host")
    kernel_fields = _collect_typed_fields(kernel, side="kernel", also=list(kernel.get("loaded_tiling_fields") or []))

    tilingdata_bridges, td_unresolved, td_diagnostics = _bridge_tilingdata(host_fields, kernel_fields)
    tilingkey_bindings, tk_unresolved = _bridge_tilingkey(repo_root, uo_root, host, kernel, tilingkey)

    bridge_nodes = []
    for n in (host.get("nodes") or []) + (kernel.get("nodes") or []) + (tilingkey.get("nodes") or []):
        if n.get("node_type") in {"TilingKey", "TilingDataField", "KernelTemplateArgument"} or n.get("layer") in {
            "tilingkey",
            "bridge",
        }:
            bridge_nodes.append(n)

    bridge_edges = []
    for edge in (host.get("edges") or []) + (kernel.get("edges") or []) + (tilingkey.get("edges") or []):
        if edge.get("type") in {"writes", "sets", "reserves", "dispatches", "selects", "loads_into", "determines"}:
            bridge_edges.append(edge)
    for b in tilingdata_bridges:
        if b.get("status") == "verified":
            bridge_edges.append(
                {
                    "id": mint_edge_id("tilingdata_bridge", str(b.get("host_writer")), str(b.get("kernel_reader"))),
                    "type": "maps_tilingdata",
                    "source": b.get("host_writer"),
                    "target": b.get("kernel_reader"),
                    "confidence": "verified",
                    "canonical_type": b.get("canonical_type"),
                    "field_path": b.get("field_path"),
                }
            )

    unresolved = list(td_unresolved) + list(tk_unresolved)
    # BuildConfig must not become CSV — annotate for consumers.
    for det in build_ev.get("determinants") or []:
        if det.get("csv_controllable") is False:
            continue

    payload = {
        "version": 2,
        "op_name": op_name,
        "bridge_nodes": bridge_nodes,
        "bridge_edges": bridge_edges,
        "tilingdata_bridges": tilingdata_bridges,
        "tilingkey_bindings": tilingkey_bindings,
        "unused_tiling_fields": [d["field"] for d in td_diagnostics if d.get("code") == "unused_tiling_field"],
        "missing_tiling_fields": [d["field"] for d in td_diagnostics if d.get("code") == "missing_tiling_field_producer"],
        "diagnostics": td_diagnostics,
        "unresolved": unresolved,
        "csv_excluded_determinant_sources": ["BuildConfig", "CompileMacro", "PlatformInfo", "SourceSelection", "KernelRuntimeVariable"],
    }
    write_yaml(uo_root / "ir" / "bridge.yaml", payload)
    if unresolved:
        _merge_unresolved(uo_root, unresolved)
    return payload


def _collect_typed_fields(layer: dict[str, Any], *, side: str, also: list[Any] | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for n in layer.get("nodes") or []:
        if n.get("node_type") != "TilingDataField" and not str(n.get("id") or "").startswith("TDF_"):
            continue
        name = str(n.get("name") or "").strip()
        if not name:
            continue
        leaf = name.split(".")[-1]
        if _is_non_tiling_key(leaf):
            continue
        owning = str(n.get("owning_type") or n.get("canonical_type") or n.get("struct_type") or "")
        field_path = str(n.get("field_path") or name)
        out.append(
            {
                "side": side,
                "name": leaf,
                "field_path": field_path,
                "owning_type": owning,
                "id": n.get("id"),
                "architecture": n.get("architecture"),
                "path_family": n.get("path_family"),
                "template_family": n.get("template_family"),
                "node": n,
            }
        )
    for item in also or []:
        if isinstance(item, dict):
            leaf = str(item.get("name") or item.get("field") or "").split(".")[-1]
            owning = str(item.get("owning_type") or "")
            field_path = str(item.get("field_path") or leaf)
        else:
            leaf = str(item).split(".")[-1]
            owning = ""
            field_path = str(item)
        if not leaf or _is_non_tiling_key(leaf):
            continue
        out.append(
            {
                "side": side,
                "name": leaf,
                "field_path": field_path,
                "owning_type": owning,
                "id": None,
                "architecture": None,
                "path_family": None,
                "template_family": None,
                "node": {},
            }
        )
    return out


def _bridge_tilingdata(
    host_fields: list[dict[str, Any]],
    kernel_fields: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    bridges: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    # Index kernel by (owning_type, field_path) and by field leaf for ambiguity checks.
    kern_by_typed: dict[tuple[str, str], list[dict[str, Any]]] = {}
    kern_by_leaf: dict[str, list[dict[str, Any]]] = {}
    for kf in kernel_fields:
        typed = (_norm_type(kf.get("owning_type")), _norm_key(kf.get("field_path") or kf.get("name")))
        kern_by_typed.setdefault(typed, []).append(kf)
        kern_by_leaf.setdefault(_norm_key(kf.get("name")), []).append(kf)

    matched_host: set[str] = set()
    matched_kern: set[str] = set()

    for hf in host_fields:
        leaf = _norm_key(hf.get("name"))
        owning = _norm_type(hf.get("owning_type"))
        fpath = _norm_key(hf.get("field_path") or hf.get("name"))
        typed_hits = kern_by_typed.get((owning, fpath), []) if owning else []
        leaf_hits = kern_by_leaf.get(leaf, [])

        if owning and typed_hits:
            for kf in typed_hits:
                ident = mint_field_identity(
                    owning_type=owning,
                    field_path=str(hf.get("field_path") or hf.get("name")),
                    file_path=str((hf.get("node") or {}).get("file_path") or ""),
                    architecture=str(hf.get("architecture") or ""),
                    template_family=str(hf.get("template_family") or ""),
                    path_family=str(hf.get("path_family") or ""),
                )
                bridges.append(
                    {
                        "status": "verified",
                        "canonical_type": owning,
                        "field_path": hf.get("field_path") or hf.get("name"),
                        "host_writer": hf.get("id") or ident.stable_id,
                        "kernel_reader": kf.get("id") or ident.stable_id,
                        "architecture": hf.get("architecture") or kf.get("architecture"),
                        "path_family": hf.get("path_family") or kf.get("path_family"),
                        "template_family": hf.get("template_family") or kf.get("template_family"),
                        "registration_evidence": "typed_field_match",
                    }
                )
                matched_host.add(leaf)
                matched_kern.add(_norm_key(kf.get("name")))
            continue

        # Unknown type on one side with unique leaf candidate → candidate only
        if not owning and len(leaf_hits) == 1:
            kf = leaf_hits[0]
            bridges.append(
                {
                    "status": "candidate",
                    "canonical_type": kf.get("owning_type") or "",
                    "field_path": hf.get("field_path") or hf.get("name"),
                    "host_writer": hf.get("id"),
                    "kernel_reader": kf.get("id"),
                    "architecture": hf.get("architecture") or kf.get("architecture"),
                    "path_family": hf.get("path_family"),
                    "template_family": hf.get("template_family"),
                    "registration_evidence": "unique_leaf_candidate",
                }
            )
            matched_host.add(leaf)
            matched_kern.add(_norm_key(kf.get("name")))
            continue

        if len(leaf_hits) > 1:
            types = sorted({_norm_type(x.get("owning_type")) or "?" for x in leaf_hits})
            unresolved.append(
                {
                    "severity": "blocking",
                    "code": "tilingdata_bridge_ambiguous",
                    "related_symbols": [hf.get("name")],
                    "candidate_files": [],
                    "evidence_present": [f"leaf={hf.get('name')}", f"types={types}"],
                    "evidence_missing": ["canonical_type_agreement"],
                    "reason": f"field {hf.get('name')} matches multiple kernel owning types: {types}",
                }
            )
            continue

        if owning and leaf_hits:
            # type conflict
            conflict = [x for x in leaf_hits if _norm_type(x.get("owning_type")) not in {"", owning}]
            if conflict:
                unresolved.append(
                    {
                        "severity": "blocking",
                        "code": "tilingdata_type_conflict",
                        "related_symbols": [hf.get("name")],
                        "candidate_files": [],
                        "evidence_present": [f"host_type={owning}"],
                        "evidence_missing": ["matching_kernel_type"],
                        "reason": f"host type {owning} conflicts with kernel field types",
                    }
                )
                continue

    host_leaves = {_norm_key(h.get("name")) for h in host_fields}
    kern_leaves = {_norm_key(k.get("name")) for k in kernel_fields}
    for leaf in sorted(host_leaves - matched_host):
        diagnostics.append(
            {
                "id": f"DIAG_UNUSED_{leaf}",
                "code": "unused_tiling_field",
                "field": leaf,
                "severity": "warning",
                "message": f"Host writes TilingDataField {leaf} but no verified/candidate kernel bridge",
            }
        )
    for leaf in sorted(kern_leaves - matched_kern):
        diagnostics.append(
            {
                "id": f"DIAG_MISSING_{leaf}",
                "code": "missing_tiling_field_producer",
                "field": leaf,
                "severity": "warning",
                "message": f"Kernel loads TilingDataField {leaf} but Host graph has no typed writer",
            }
        )
    return bridges, unresolved, diagnostics


def _bridge_tilingkey(
    repo_root: Path,
    uo_root: Path,
    host: dict[str, Any],
    kernel: dict[str, Any],
    tilingkey: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bindings: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    dimensions = list(tilingkey.get("dimensions") or [])
    # declaration_space from dimensions
    declaration_space = [
        {
            "index": i,
            "name": d.get("name"),
            "bit_width": d.get("bit_width") or d.get("bits"),
            "allowed": d.get("values") or d.get("allowed") or d.get("domain"),
        }
        for i, d in enumerate(dimensions)
    ]
    compile_selection_space = list(tilingkey.get("selection_space") or tilingkey.get("args_sel") or [])
    if not compile_selection_space and tilingkey.get("args_sel_count"):
        compile_selection_space = [{"note": "ARGS_SEL present", "count": tilingkey.get("args_sel_count")}]

    schemas = tilingkey.get("schemas") or [{"key_schema_id": "default", "dimensions": dimensions}]
    if not dimensions and not schemas:
        return bindings, unresolved

    # Host GET_TPL_TILING_KEY argument lists
    host_calls = _find_get_tpl_calls(repo_root, host)
    kernel_params = list(kernel.get("template_parameters") or tilingkey.get("kernel_template_params") or [])

    if len(schemas) > 1 and not host_calls:
        unresolved.append(
            {
                "severity": "blocking",
                "code": "tilingkey_schema_ambiguous",
                "related_symbols": [s.get("key_schema_id") for s in schemas],
                "candidate_files": [],
                "evidence_present": [f"schema_count={len(schemas)}"],
                "evidence_missing": ["host_key_writer_site"],
                "reason": "multiple TilingKey schemas without Host writer binding",
            }
        )

    for schema in schemas:
        schema_id = str(schema.get("key_schema_id") or "default")
        dims = list(schema.get("dimensions") or dimensions)
        decl = [
            {
                "index": i,
                "name": d.get("name"),
                "bit_width": d.get("bit_width") or d.get("bits"),
                "allowed": d.get("values") or d.get("allowed") or d.get("domain"),
            }
            for i, d in enumerate(dims)
        ]
        # Prefer matching host call by schema/file hints; else first call.
        call = None
        for c in host_calls:
            if schema_id != "default" and schema_id in str(c.get("file_path") or ""):
                call = c
                break
        if call is None and len(host_calls) == 1:
            call = host_calls[0]
        if call is None and len(host_calls) > 1:
            unresolved.append(
                {
                    "severity": "blocking",
                    "code": "tilingkey_schema_ambiguous",
                    "related_symbols": [schema_id],
                    "candidate_files": [c.get("file_path") for c in host_calls],
                    "evidence_present": [f"host_calls={len(host_calls)}"],
                    "evidence_missing": ["schema_to_call_binding"],
                    "reason": "multiple Host GET_TPL_TILING_KEY calls; cannot bind schema globally",
                }
            )
            continue

        host_args = list((call or {}).get("args") or [])
        # Kernel template params that are KEY dims only (exclude non-key params if marked)
        key_params = [p for p in kernel_params if not p.get("non_tilingkey")]
        if not key_params and dims:
            key_params = [{"index": i, "name": d.get("name")} for i, d in enumerate(dims)]

        diagnostics: list[str] = []
        if host_args and len(host_args) != len(decl):
            diagnostics.append("tilingkey_count_mismatch")
            unresolved.append(
                {
                    "severity": "blocking",
                    "code": "tilingkey_count_mismatch",
                    "related_symbols": [schema_id],
                    "candidate_files": [call.get("file_path")] if call else [],
                    "evidence_present": [f"host_args={len(host_args)}", f"decl={len(decl)}"],
                    "evidence_missing": ["matching_counts"],
                    "reason": "Host GET_TPL_TILING_KEY arity differs from ARGS_DECL",
                }
            )
        if key_params and decl and len(key_params) != len(decl):
            # only if kernel params claimed to be pure KEY params
            if all(p.get("is_tilingkey", True) for p in key_params):
                diagnostics.append("tilingkey_count_mismatch")

        positions = []
        for i, d in enumerate(decl):
            host_arg = host_args[i] if i < len(host_args) else None
            kparam = key_params[i] if i < len(key_params) else None
            if host_arg and kparam and d.get("name") and kparam.get("name") and d.get("name") != kparam.get("name"):
                if "tilingkey_order_mismatch" not in diagnostics:
                    diagnostics.append("tilingkey_order_mismatch")
                    unresolved.append(
                        {
                            "severity": "blocking",
                            "code": "tilingkey_order_mismatch",
                            "related_symbols": [d.get("name"), kparam.get("name")],
                            "candidate_files": [],
                            "evidence_present": [f"index={i}"],
                            "evidence_missing": ["name_alignment"],
                            "reason": f"decl name {d.get('name')} != kernel param {kparam.get('name')} at index {i}",
                        }
                    )
            if kparam is None and decl:
                if "tilingkey_kernel_binding_missing" not in diagnostics:
                    diagnostics.append("tilingkey_kernel_binding_missing")
            positions.append(
                {
                    "index": i,
                    "host_arg": host_arg,
                    "decl": d,
                    "bit_width": d.get("bit_width"),
                    "declaration_space": d.get("allowed"),
                    "compile_selection_space": _selection_for(compile_selection_space, d.get("name")),
                    "host_runtime_space": (call or {}).get("runtime_space"),
                    "kernel_template_param": kparam,
                    "kernel_uses": [],
                }
            )

        bindings.append(
            {
                "key_schema_id": schema_id,
                "architecture": tilingkey.get("architecture"),
                "path_family": (call or {}).get("path_family") or "unknown",
                "template_family": schema.get("template_family") or "unknown",
                "host_writer": (call or {}).get("file_path"),
                "kernel_entry": (kernel.get("entry") or {}).get("id") if isinstance(kernel.get("entry"), dict) else None,
                "positions": positions,
                "declaration_space": decl,
                "compile_selection_space": compile_selection_space,
                "host_runtime_space": (call or {}).get("runtime_space"),
                "diagnostics": diagnostics,
            }
        )
    return bindings, unresolved


def _find_get_tpl_calls(repo_root: Path, host: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    files = set()
    for n in host.get("nodes") or []:
        fp = str(n.get("file_path") or (n.get("locator") or {}).get("file_path") or "")
        if fp:
            files.add(fp)
    for helper in host.get("helpers") or []:
        fp = str(helper.get("file_path") or "")
        if fp:
            files.add(fp)
    for fp in files:
        path = repo_root / fp
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in GET_TPL_CALL_RE.finditer(text):
            raw = match.group(1)
            args = [a.strip() for a in _split_args(raw) if a.strip()]
            line = text.count("\n", 0, match.start()) + 1
            calls.append({"file_path": fp, "line": line, "args": args, "runtime_space": None})
    return calls


def _split_args(raw: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    cur = []
    for ch in raw:
        if ch == "(":
            depth += 1
            cur.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            cur.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return parts


def _selection_for(selection_space: list[Any], name: Any) -> Any:
    if not name:
        return selection_space
    for item in selection_space:
        if isinstance(item, dict) and item.get("name") == name:
            return item.get("values") or item
    return None


def _norm_key(name: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").casefold())


def _norm_type(name: Any) -> str:
    text = str(name or "").strip()
    text = text.replace("::", ".").split("<")[0].strip()
    return text


def _is_non_tiling_key(name: str) -> bool:
    key = _norm_key(name)
    if key in _NON_TILING_KEYS:
        return True
    return any(key.startswith(p) for p in _NON_TILING_PREFIXES)


def _merge_unresolved(uo_root: Path, items: list[dict[str, Any]]) -> None:
    path = uo_root / "ir" / "unresolved.yaml"
    data = read_yaml(path)
    existing = list(data.get("items") or [])
    keys = {(x.get("code"), tuple(x.get("related_symbols") or [])) for x in existing}
    for item in items:
        key = (item.get("code"), tuple(item.get("related_symbols") or []))
        if key not in keys:
            existing.append(item)
    write_yaml(path, {"version": 1, "items": existing})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile typed Host↔Kernel bridges")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    args = parser.parse_args(argv)
    payload = reconcile_bridge(Path(args.repo).resolve(), args.op_name)
    print(
        f"tilingdata_bridges={len(payload.get('tilingdata_bridges') or [])} "
        f"tilingkey_bindings={len(payload.get('tilingkey_bindings') or [])} "
        f"unresolved={len(payload.get('unresolved') or [])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
