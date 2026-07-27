"""extract_plan slim IR 工具（与 Relation 语义裁决无关）。"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

SLIM_PLAN_VERSION = 2

AUDIT_ITEM_KEYS = frozenset(
    {
        "evidence_snippet",
        "decision_reason",
        "score",
        "source_window",
        "evidence",
        "duplicate_of",
        "duplicate_explanation",
    }
)

AUDIT_PLAN_KEYS = frozenset(
    {
        "rejected_candidates",
        "deferred_candidates",
        "accepted_candidates",
        "decision_report_ref",
        "input_roots",
        "condition_nodes",
        "branch_nodes",
        "template_nodes",
        "key_dimensions",
        "derived_values",
        "groundings",
        "tiling_field_sinks",
    }
)

# 语义权威面仅存 semantic_relations.yaml，禁止重复展开到主计划。
RELATION_ONLY_KEYS = frozenset(
    {
        "input_roots",
        "condition_nodes",
        "branch_nodes",
        "template_nodes",
        "key_dimensions",
        "derived_values",
        "groundings",
        "tiling_field_sinks",
    }
)


def _binding_ref(binding: dict[str, Any], idx: int) -> str:
    existing = str(binding.get("binding_ref") or "").strip()
    if existing.startswith("RB_"):
        return existing
    return f"RB_{idx:03d}"


def slim_extract_plan(
    plan: dict[str, Any],
    *,
    aliases_rel: str = "extract_plan_aliases.yaml",
    bindings_rel: str = "receiver_bindings.yaml",
    relations_rel: str = "semantic_relations.yaml",
    aliases_sha: str = "",
    bindings_sha: str = "",
    relations_sha: str = "",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """返回 (slim_plan, aliases_sidecar, bindings_sidecar)。"""
    aliases_doc: dict[str, Any] = {"version": 1, "aliases": {}}
    for a in plan.get("aliases") or []:
        if not isinstance(a, dict):
            continue
        local = str(a.get("local") or "").strip()
        leaf = str(a.get("tdf_leaf") or "").strip()
        if local and leaf:
            aliases_doc["aliases"][local] = leaf

    bindings_doc: dict[str, Any] = {"version": 1, "bindings": {}}
    for idx, b in enumerate(plan.get("receiver_bindings") or [], start=1):
        if not isinstance(b, dict):
            continue
        bref = _binding_ref(b, idx)
        owner = b.get("canonical_owner_key") if isinstance(b.get("canonical_owner_key"), dict) else {}
        bindings_doc["bindings"][bref] = {
            "receiver": b.get("receiver") or b.get("name"),
            "root_type": owner.get("root_type")
            or (list(b.get("root_tiling_types") or [None])[0]),
            "nested_field": b.get("nested_field") or owner.get("nested_path"),
            "member_type": b.get("member_type") or owner.get("member_type"),
            "source_candidate": b.get("candidate_id"),
        }

    recv_name_to_ref = {
        str(v.get("receiver") or ""): k
        for k, v in bindings_doc["bindings"].items()
        if v.get("receiver")
    }

    slim_writers = []
    for w in plan.get("writers") or []:
        if not isinstance(w, dict):
            continue
        slim_writers.append(
            {
                "id": w.get("candidate_id") or w.get("id"),
                "name": w.get("name"),
                "role": w.get("role"),
                "file_path": w.get("file_path"),
                "start_line": w.get("start_line"),
                "qualified_name": w.get("qualified_name"),
            }
        )

    slim_receivers = []
    for r in plan.get("receivers") or []:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name") or "").strip()
        slim_receivers.append(
            {
                "id": r.get("candidate_id") or r.get("id"),
                "name": name,
                "is_tiling_sink": r.get("is_tiling_sink"),
                "file_path": r.get("file_path"),
                "binding_ref": recv_name_to_ref.get(name),
            }
        )

    writers = slim_writers
    receivers = slim_receivers
    slim: dict[str, Any] = {
        "version": SLIM_PLAN_VERSION,
        "architecture": plan.get("architecture"),
        "actor_id": plan.get("actor_id"),
        "run_id": plan.get("run_id"),
        "workflow_id": plan.get("workflow_id"),
        "candidates_sha256": plan.get("candidates_sha256"),
        "confirmed_by": plan.get("confirmed_by") or "relation_graph",
        "semantic_relations_ref": {
            "path": relations_rel,
            "sha256": relations_sha,
        },
        "writers": writers,
        "receivers": receivers,
        "non_sink_roots": [
            x for x in (plan.get("non_sink_roots") or []) if isinstance(x, str)
        ],
        "derived_roots": [
            x for x in (plan.get("derived_roots") or []) if isinstance(x, str)
        ],
        "extra_host_entries": list(plan.get("extra_host_entries") or []),
        "aliases_ref": {
            "path": aliases_rel,
            "sha256": aliases_sha,
            "count": len(aliases_doc["aliases"]),
        },
        "receiver_bindings_ref": {
            "path": bindings_rel,
            "sha256": bindings_sha,
            "count": len(bindings_doc["bindings"]),
        },
        "counts": {
            "writers": len(writers),
            "receivers": len(receivers),
            "aliases": len(aliases_doc["aliases"]),
            "bindings": len(bindings_doc["bindings"]),
        },
    }
    slim = {k: v for k, v in slim.items() if v is not None}
    return slim, aliases_doc, bindings_doc


def hydrate_extract_plan(plan: dict[str, Any], uo_ir: Path) -> dict[str, Any]:
    """合并 sidecar aliases/bindings，供下游消费。"""
    out = dict(plan)
    aref = plan.get("aliases_ref") if isinstance(plan.get("aliases_ref"), dict) else None
    if aref and aref.get("path"):
        ap = uo_ir / str(aref["path"])
        if ap.is_file():
            from uo.scripts._ir_io import read_yaml

            doc = read_yaml(ap) or {}
            aliases = doc.get("aliases") if isinstance(doc, dict) else None
            if isinstance(aliases, dict) and aliases:
                out["aliases"] = [
                    {"local": k, "tdf_leaf": v} for k, v in aliases.items()
                ]
    bref = (
        plan.get("receiver_bindings_ref")
        if isinstance(plan.get("receiver_bindings_ref"), dict)
        else None
    )
    if bref and bref.get("path"):
        bp = uo_ir / str(bref["path"])
        if bp.is_file():
            from uo.scripts._ir_io import read_yaml

            doc = read_yaml(bp) or {}
            bindings = doc.get("bindings") if isinstance(doc, dict) else None
            if isinstance(bindings, dict) and bindings:
                rows = []
                for k, v in bindings.items():
                    if not isinstance(v, dict):
                        continue
                    rows.append(
                        {
                            "binding_ref": k,
                            "receiver": v.get("receiver"),
                            "root_type": v.get("root_type"),
                            "nested_field": v.get("nested_field"),
                            "member_type": v.get("member_type"),
                            "candidate_id": v.get("source_candidate"),
                            "canonical_owner_key": {
                                "root_type": v.get("root_type") or "",
                                "nested_path": v.get("nested_field") or "",
                                "member_type": v.get("member_type") or "",
                            },
                        }
                    )
                out["receiver_bindings"] = rows
    writers = []
    for w in out.get("writers") or []:
        if not isinstance(w, dict):
            writers.append(w)
            continue
        row = dict(w)
        if row.get("id") and not row.get("candidate_id"):
            row["candidate_id"] = row["id"]
        writers.append(row)
    out["writers"] = writers
    return out


def file_sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def assert_canonical_plan_slim(plan: dict[str, Any]) -> list[str]:
    """Gate：canonical IR 不得携带审计或 Relation 展开字段。"""
    errors: list[str] = []
    for key in AUDIT_PLAN_KEYS:
        if key in plan and plan.get(key):
            errors.append(f"CANONICAL_SLIM: 禁止字段 {key!r} 出现在 extract_plan.yaml")
    for section in ("writers", "receivers", "aliases"):
        for item in plan.get(section) or []:
            if not isinstance(item, dict):
                continue
            for bad in AUDIT_ITEM_KEYS:
                if item.get(bad):
                    errors.append(
                        f"CANONICAL_SLIM: {section} 条目携带审计字段 {bad!r}"
                    )
    return errors


def atomic_write_yaml(path: Path, doc: dict[str, Any]) -> None:
    """先写临时文件再 rename，失败不留半成品。"""
    from uo.scripts._ir_io import write_yaml

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    write_yaml(tmp, doc)
    tmp.replace(path)


__all__ = [
    "SLIM_PLAN_VERSION",
    "RELATION_ONLY_KEYS",
    "slim_extract_plan",
    "hydrate_extract_plan",
    "file_sha256_bytes",
    "assert_canonical_plan_slim",
    "atomic_write_yaml",
]
