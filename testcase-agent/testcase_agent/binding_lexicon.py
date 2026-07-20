"""Operator-agnostic binding lexicon: KEY tokens, CSV aliases, KEY derivations.

Deterministic TG never embeds per-operator name tables. Bootstrap only:
  - generic loop/platform patterns (in atom_bind)
  - optional weak KEY_id → token heuristics from tiling/key_space.yaml
  - UO kernel/variables.yaml set_by

Per-operator maps (IS_TND→VAR_KEY_*, issink→is_sink, KEY exprs from CSV) MUST come from
`realization/binding_lexicon.yaml` written by `/tg-csv-contract` (LLM + evidence).
"""

from __future__ import annotations

from typing import Any

LEXICON_VERSION = 1


def empty_lexicon(*, source: str = "empty") -> dict[str, Any]:
    return {
        "version": LEXICON_VERSION,
        "source": source,
        "key_tokens": {},
        "csv_field_aliases": {},
        "arith_constants": {},
        "key_derivations": [],
        "warnings": [],
    }


def normalize_lexicon(doc: dict[str, Any] | None) -> dict[str, Any]:
    base = empty_lexicon(source=str((doc or {}).get("source") or "empty"))
    if not isinstance(doc, dict):
        return base
    base["version"] = int(doc.get("version") or LEXICON_VERSION)
    base["source"] = str(doc.get("source") or base["source"])
    tokens = doc.get("key_tokens") or {}
    if isinstance(tokens, dict):
        for name, spec in tokens.items():
            parsed = _parse_token_spec(name, spec)
            if parsed:
                base["key_tokens"][str(name).upper()] = parsed
    aliases = doc.get("csv_field_aliases") or {}
    if isinstance(aliases, dict):
        for name, spec in aliases.items():
            parsed = _parse_alias_spec(name, spec)
            if parsed:
                base["csv_field_aliases"][str(name).lower().replace("->", ".").replace(" ", "")] = parsed
    consts = doc.get("arith_constants") or {}
    if isinstance(consts, dict):
        for name, value in consts.items():
            try:
                base["arith_constants"][str(name)] = int(value)
            except (TypeError, ValueError):
                continue
    derivations = doc.get("key_derivations") or []
    if isinstance(derivations, list):
        base["key_derivations"] = [item for item in derivations if isinstance(item, dict) and item.get("id")]
    base["warnings"] = [str(w) for w in (doc.get("warnings") or [])]
    return base


def merge_lexicons(*docs: dict[str, Any] | None) -> dict[str, Any]:
    """Later docs override earlier ones for tokens/aliases; derivations append by id."""
    out = empty_lexicon(source="merged")
    sources: list[str] = []
    seen_deriv: set[str] = set()
    locked_deriv: set[str] = set()
    for doc in docs:
        if not doc:
            continue
        norm = normalize_lexicon(doc)
        sources.append(str(norm.get("source") or ""))
        out["key_tokens"].update(norm["key_tokens"])
        out["csv_field_aliases"].update(norm["csv_field_aliases"])
        out["arith_constants"].update(norm["arith_constants"])
        for item in norm["key_derivations"]:
            vid = str(item.get("id") or "")
            if not vid:
                continue
            if is_locked_derivation(item):
                locked_deriv.add(vid)
            if vid in seen_deriv:
                prev = next((d for d in out["key_derivations"] if str(d.get("id")) == vid), None)
                if prev and is_locked_derivation(prev) and not is_locked_derivation(item):
                    continue
                out["key_derivations"] = [d for d in out["key_derivations"] if str(d.get("id")) != vid]
            seen_deriv.add(vid)
            out["key_derivations"].append(item)
        out["warnings"].extend(norm.get("warnings") or [])
    out["source"] = "+".join(s for s in sources if s) or "merged"
    out["locked_derivation_ids"] = sorted(locked_deriv)
    return out


def is_locked_derivation(item: dict[str, Any]) -> bool:
    if item.get("locked") is True:
        return True
    for ref in item.get("source_refs") or []:
        if not isinstance(ref, dict):
            continue
        path = str(ref.get("path") or "")
        reason = str(ref.get("reason") or "")
        if path.endswith("binding_lexicon.yaml") or path == "binding_lexicon.yaml":
            return True
        if reason.startswith("migrated_from"):
            return True
    return False


def lexicon_from_key_space(key_space: dict[str, Any] | None) -> dict[str, Any]:
    """Weak bootstrap: KEY_FOO → token FOO / IS_* heuristic. No CSV coupling."""
    out = empty_lexicon(source="key_space_heuristic")
    if not isinstance(key_space, dict):
        return out
    entries = list(key_space.get("fields") or []) + list(key_space.get("dimensions") or [])
    for field in entries:
        if not isinstance(field, dict):
            continue
        key_id = str(field.get("id") or "").strip()
        name = str(field.get("name") or "").strip()
        if key_id.upper().startswith("KEY_"):
            bare = key_id[4:]
        elif name:
            # tilingkey_space dimensions use bare names like IsTnd
            bare = name
            key_id = f"KEY_{name.upper()}" if not name.upper().startswith("KEY_") else name
        else:
            continue
        var_id = f"VAR_KEY_{bare.upper()}" if not bare.upper().startswith("KEY_") else f"VAR_{bare}"
        if not var_id.startswith("VAR_KEY_"):
            var_id = f"VAR_KEY_{bare.upper()}"
        true_value = 1
        values = field.get("values")
        if isinstance(values, list) and values and all(isinstance(v, int) and not isinstance(v, bool) for v in values):
            # Prefer 1 as true for 0/1 flags; else first non-zero
            if 1 in values:
                true_value = 1
            elif 0 in values and len(values) == 2:
                true_value = next(v for v in values if v != 0)
        for token in _heuristic_tokens_from_key(bare):
            out["key_tokens"].setdefault(token.upper(), {"var": var_id, "true_value": true_value})
        # Domain-only placeholders are filled by /tg-csv-contract key_derivations (no CSV coupling here).
    out["warnings"].append(
        "key_space_heuristic: KEY→token names are best-effort; /tg-csv-contract must write binding_lexicon.yaml"
    )
    return out


def apply_lexicon_key_derivations(
    existing: list[dict[str, Any]],
    lexicon: dict[str, Any],
) -> list[dict[str, Any]]:
    """Merge lexicon key_derivations over existing stubs (same id → replace)."""
    by_id: dict[str, dict[str, Any]] = {}
    for item in existing:
        if isinstance(item, dict) and item.get("id"):
            by_id[str(item["id"])] = item
    for item in lexicon.get("key_derivations") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        vid = str(item["id"])
        expr = item.get("expr")
        if not isinstance(expr, dict):
            continue
        # Wrap as derived variable record used by realization_map
        if expr.get("op") != "derived":
            wrapped = {"op": "derived", "var": vid, "expr": expr}
        else:
            wrapped = expr
        by_id[vid] = {
            "id": vid,
            "type": item.get("type") or "int",
            "domain": item.get("domain") or [0, 1],
            "expr": wrapped,
            "description": item.get("description") or item.get("rationale") or f"lexicon derivation {vid}",
            "source_refs": item.get("source_refs") or [{"path": "binding_lexicon.yaml"}],
        }
    return list(by_id.values())


def _heuristic_tokens_from_key(bare: str) -> list[str]:
    """KEY_ISTND → ISTND, IS_TND; KEY_ISROPE → ISROPE, IS_ROPE."""
    bare_u = bare.upper()
    tokens = [bare_u]
    if bare_u.startswith("IS") and len(bare_u) > 2 and not bare_u.startswith("IS_"):
        tokens.append("IS_" + bare_u[2:])
    return tokens


def _parse_token_spec(name: str, spec: Any) -> dict[str, Any] | None:
    if isinstance(spec, (list, tuple)) and len(spec) >= 1:
        var = str(spec[0])
        true_value = int(spec[1]) if len(spec) > 1 else 1
        return {"var": var if var.startswith("VAR_") else f"VAR_KEY_{var}", "true_value": true_value}
    if isinstance(spec, dict) and spec.get("var"):
        return {
            "var": str(spec["var"]),
            "true_value": int(spec.get("true_value", 1)),
        }
    if isinstance(spec, str):
        var = spec if spec.startswith("VAR_") else f"VAR_KEY_{spec}"
        return {"var": var, "true_value": 1}
    return None


def _parse_alias_spec(name: str, spec: Any) -> dict[str, Any] | None:
    if isinstance(spec, (list, tuple)) and len(spec) >= 1:
        return {"column": str(spec[0]), "value": spec[1] if len(spec) > 1 else None}
    if isinstance(spec, dict) and spec.get("column"):
        return {"column": str(spec["column"]), "value": spec.get("value")}
    if isinstance(spec, str):
        return {"column": spec, "value": None}
    return None
