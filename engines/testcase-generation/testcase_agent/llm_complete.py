from __future__ import annotations

from pathlib import Path
from typing import Any

from .extract import merge_llm_patches
from .io import read_yaml


def load_llm_patches(out_root: Path) -> list[dict[str, Any]]:
    """Load optional LLM patch file written by a skill / human.

    Expected path: extract/llm_patches.yaml with {patches: [...]}.
    Each patch is a GenerationCondition-like LogicExpr only — never CSV rows.
    """
    path = out_root / "extract" / "llm_patches.yaml"
    if not path.exists():
        return []
    doc = read_yaml(path)
    patches = doc.get("patches") if isinstance(doc, dict) else None
    if isinstance(patches, list):
        return [item for item in patches if isinstance(item, dict)]
    return []


def apply_llm_completion(extract_doc: dict[str, Any], patches: list[dict[str, Any]], *, declared_variables: set[str] | None = None) -> dict[str, Any]:
    if not patches:
        out = dict(extract_doc)
        out.setdefault("accepted_llm_patches", [])
        out.setdefault("rejected_llm_patches", [])
        return out
    return merge_llm_patches(extract_doc, patches, declared_variables=declared_variables)


def build_llm_prompt_bundle(extract_doc: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """Deterministic bundle for bounded LLM completion — scripts never invent exprs."""
    gaps = [item for item in extract_doc.get("gaps") or [] if item.get("code") == "EXTRACT_GAP"]
    files = snapshot.get("files") if isinstance(snapshot.get("files"), dict) else {}
    slices: list[dict[str, Any]] = []
    for gap in gaps:
        for ref in gap.get("source_refs") or []:
            payload = files.get(ref)
            if payload is not None:
                slices.append({"path": ref, "content": payload, "gap_id": gap.get("id")})
        entity = str(gap.get("entity_ref") or "")
        if entity:
            key = f"tiling/key_cards/{entity}.yaml"
            if key in files:
                slices.append({"path": key, "content": files[key], "gap_id": gap.get("id")})
    return {
        "version": 1,
        "snapshot_hash": snapshot.get("snapshot_hash"),
        "instruction": "Emit only LogicExpr GenerationCondition patches. Do not write solver IR, CSV, or shapes.",
        "gaps": gaps,
        "kb_slices": slices,
        "output_schema": {
            "patches": [
                {
                    "id": "GC_LLM_EXAMPLE",
                    "closes_gap": "GC_KEY_DETERTYPE_HIT_RECIPE",
                    "role": "legal",
                    "expr": {"op": "implies", "antecedent": {"op": "eq", "var": "VAR_KEY_DETERTYPE", "value": 1}, "consequent": {"op": "eq", "var": "VAR_KEY_ISTND", "value": 1}},
                    "source_refs": ["tiling/key_cards/KEY_DETERTYPE.yaml"],
                }
            ]
        },
    }
