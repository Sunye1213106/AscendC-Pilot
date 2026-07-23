from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import read_yaml, write_yaml


DEFAULT_TOPICS: dict[str, dict[str, Any]] = {
    "determinism": {
        "topic_id": "determinism",
        "seed_entities": [
            "KEY_DETERTYPE",
            "VAR_KEY_DETERTYPE",
            "VAR_KVAR_IS_DETER_OLD",
            "VAR_KVAR_IS_DETER_NEW",
        ],
        "include_kinds": ["tiling_key_field_value", "kernel_branch", "runtime_variable_state", "compile_template"],
        "expand_policy": {
            "key_fields": ["DeterType", "DETERTYPE", "KEY_DETERTYPE"],
            "related_closure": "impact_1hop",
            "name_tokens": ["deter", "determin", "is_deter", "isdeter"],
        },
        "llm_completion": {
            "enabled": True,
            "fields": ["set_by", "host_reachable", "hit_recipe"],
        },
        "success_criteria": {
            "cover_all_seed_domain_values": True,
            "min_witnesses_per_value": 1,
        },
    }
}


def load_topic_manifest(out_root: Path, topic: str, *, project_root: Path | None = None) -> dict[str, Any]:
    topic = str(topic or "").strip()
    if not topic:
        raise ValueError("topic is empty; omit --topic for whole-operator scope")
    candidates = [
        out_root / "topics" / f"{topic}.yaml",
    ]
    if project_root is not None:
        candidates.append(project_root / ".ascendc-agent" / "tg" / "topics" / f"{topic}.yaml")
        candidates.append(Path(__file__).resolve().parent / "topics" / f"{topic}.yaml")
    for path in candidates:
        if path.exists():
            doc = read_yaml(path)
            if isinstance(doc, dict) and doc:
                doc.setdefault("topic_id", topic)
                return doc
    if topic in DEFAULT_TOPICS:
        manifest = dict(DEFAULT_TOPICS[topic])
        write_yaml(out_root / "topics" / f"{topic}.yaml", manifest)
        return manifest
    # Generic topic: treat topic string as seed token
    manifest = {
        "topic_id": topic,
        "seed_entities": [],
        "include_kinds": ["tiling_key_field_value", "kernel_branch", "runtime_variable_state", "family", "kernel_path"],
        "expand_policy": {
            "key_fields": [topic, topic.upper()],
            "related_closure": "impact_1hop",
            "name_tokens": [topic.lower()],
        },
        "llm_completion": {"enabled": True, "fields": ["set_by", "host_reachable", "hit_recipe"]},
        "success_criteria": {"cover_all_seed_domain_values": True, "min_witnesses_per_value": 1},
    }
    write_yaml(out_root / "topics" / f"{topic}.yaml", manifest)
    return manifest


def obligation_matches_topic(obligation: dict[str, Any], manifest: dict[str, Any], files: dict[str, Any] | None = None) -> bool:
    seeds = {str(item).upper() for item in manifest.get("seed_entities") or []}
    tokens = {str(item).lower() for item in (_as_dict(manifest.get("expand_policy")).get("name_tokens") or [])}
    key_fields = {str(item).upper() for item in (_as_dict(manifest.get("expand_policy")).get("key_fields") or [])}
    include_kinds = {str(item) for item in manifest.get("include_kinds") or []}
    kind = str(obligation.get("kind") or "")
    if include_kinds and kind not in include_kinds and kind not in {"tiling_key_field_value", "tiling_key_relation"}:
        # still allow if refs match seeds
        pass

    refs = [str(ref).upper() for ref in obligation.get("target_refs") or []]
    blob_parts = refs + [str(obligation.get("id") or ""), str(obligation.get("target_value") or ""), kind]
    constraints = obligation.get("constraints") if isinstance(obligation.get("constraints"), dict) else {}
    field = str(constraints.get("field") or constraints.get("field_name") or "").upper()
    if field:
        blob_parts.append(field)
        if field in key_fields or f"KEY_{field}" in seeds or field in {s.removeprefix("KEY_") for s in seeds}:
            return True
    blob = " ".join(blob_parts).upper()
    blob_l = blob.lower()
    if any(seed and seed in blob for seed in seeds):
        return True
    if any(token and token in blob_l for token in tokens):
        return True
    # template_legal / key card hints from files
    if files:
        for seed in seeds:
            card = files.get(f"tiling/key_cards/{seed}.yaml") or files.get(f"tiling/key_cards/{seed.removeprefix('KEY_')}.yaml")
            if isinstance(card, dict) and field and field in {str(card.get("key") or "").upper(), seed.removeprefix("KEY_")}:
                return True
    return False


def filter_obligations_for_topic(obligations: list[dict[str, Any]], manifest: dict[str, Any], files: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    kept = [item for item in obligations if obligation_matches_topic(item, manifest, files)]
    return kept


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
