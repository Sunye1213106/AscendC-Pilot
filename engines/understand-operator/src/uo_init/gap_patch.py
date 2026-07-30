# -*- coding: utf-8 -*-
"""Closed-vocabulary gap patches: validate, apply, measure the derive loop.

LLM output is only admitted when every field is mechanically checkable:

1. ``blocker_id`` exists in ``ir/unresolved.yaml``
2. ``classification`` is one of the four closed labels
3. for ``input_derived``, ``var_id`` is already in VariableModel, ``op`` is in
   the support set, and ``value`` sits in the declared domain
4. every evidence ``file:line`` exists and the snippet matches the source

Accepted patches land in ``ir/gap_bindings.yaml``. The next derive pass reads
that ledger so scheduling / input_derived decisions actually shrink the
escalating undecided set — that shrink is the loop gate, not a free-form
"looks good" judgement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

CLASSIFICATIONS = (
    "scheduling",
    "input_derived",
    "validation_assumption",
    "genuinely_unknown",
)

BINDING_OPS = frozenset({"eq", "ne", "lt", "le", "gt", "ge", "in"})

SCHEMA_HINT = {
    "blocker_id": "BLK_… from ir/unresolved.yaml",
    "classification": " | ".join(CLASSIFICATIONS),
    "binding": {
        "var_id": "must already exist in VariableModel (only when input_derived)",
        "op": " | ".join(sorted(BINDING_OPS)),
        "value": "literal or declared enum member inside the var's domain",
    },
    "evidence": [{"file": "repo-relative path", "line": 1, "snippet": "must match source"}],
}


@dataclass
class PatchIssue:
    code: str
    message: str
    path: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = {"code": self.code, "message": self.message}
        if self.path:
            out["path"] = self.path
        return out


@dataclass
class PatchVerdict:
    ok: bool
    patch: dict[str, Any] = field(default_factory=dict)
    issues: list[PatchIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "blocker_id": self.patch.get("blocker_id"),
            "classification": self.patch.get("classification"),
            "issues": [i.to_dict() for i in self.issues],
        }


def _as_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    return {}


def load_unresolved(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, dict[str, Any]] = {}
    for row in data.get("blockers") or []:
        if isinstance(row, dict) and row.get("id"):
            out[str(row["id"])] = row
    return out


def load_bindings(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = data.get("bindings") or []
    return [r for r in rows if isinstance(r, dict)]


def dump_bindings(path: Path, bindings: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "status": "extracted" if bindings else "empty",
        "schema": SCHEMA_HINT,
        "bindings": bindings,
    }
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _value_in_domain(value: Any, spec) -> bool:
    domain = getattr(spec, "domain", None)
    if domain is None:
        return True
    values = list(getattr(domain, "values", None) or [])
    if values:
        allowed = {str(v) for v in values}
        if str(value) in allowed:
            return True
        try:
            return int(value) in {int(v) for v in values if str(v).lstrip("-").isdigit()}
        except (TypeError, ValueError):
            return False
    lo = getattr(domain, "lo", None)
    hi = getattr(domain, "hi", None)
    try:
        iv = int(value)
    except (TypeError, ValueError):
        return getattr(spec, "value_type", "") in ("enum", "bool", "string")
    if lo is not None and iv < int(lo):
        return False
    if hi is not None and iv > int(hi):
        return False
    return True


def _snippet_matches(file_path: Path, line: int, snippet: str) -> bool:
    if not file_path.is_file() or line <= 0:
        return False
    try:
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    if line > len(lines):
        return False
    # Allow the snippet to be a substring of a small window around the line.
    window = "\n".join(lines[max(0, line - 2) : min(len(lines), line + 1)])
    needle = (snippet or "").strip()
    if not needle:
        return False
    # Snippets are often truncated; require a stable prefix.
    probe = needle[:80]
    return probe in window or needle[:40] in lines[line - 1]


def validate_patch(
    patch: dict[str, Any],
    *,
    blockers: dict[str, dict[str, Any]],
    var_model: Any,
    ops_root: Path | None = None,
) -> PatchVerdict:
    """Four mechanical checks. Any failure rejects the patch alone."""
    issues: list[PatchIssue] = []
    patch = _as_dict(patch)
    bid = str(patch.get("blocker_id") or "")
    if not bid or bid not in blockers:
        issues.append(
            PatchIssue("unknown_blocker", f"blocker_id {bid!r} not in unresolved.yaml")
        )
    classification = str(patch.get("classification") or "")
    if classification not in CLASSIFICATIONS:
        issues.append(
            PatchIssue(
                "bad_classification",
                f"classification {classification!r} not in {CLASSIFICATIONS}",
            )
        )
    binding = _as_dict(patch.get("binding"))
    if classification == "input_derived":
        var_id = str(binding.get("var_id") or "")
        op = str(binding.get("op") or "")
        if not var_id:
            issues.append(PatchIssue("missing_binding", "input_derived requires binding.var_id"))
        elif var_model is None or var_model.get(var_id) is None:
            issues.append(
                PatchIssue(
                    "invented_var",
                    f"var_id {var_id!r} is not in VariableModel",
                    path="binding.var_id",
                )
            )
        if op not in BINDING_OPS:
            issues.append(
                PatchIssue(
                    "bad_op",
                    f"op {op!r} not in {sorted(BINDING_OPS)}",
                    path="binding.op",
                )
            )
        if "value" not in binding:
            issues.append(PatchIssue("missing_value", "input_derived requires binding.value"))
        elif var_model is not None and var_id and var_model.get(var_id) is not None:
            if not _value_in_domain(binding.get("value"), var_model.get(var_id)):
                issues.append(
                    PatchIssue(
                        "value_out_of_domain",
                        f"value {binding.get('value')!r} outside domain of {var_id}",
                        path="binding.value",
                    )
                )
    elif binding:
        # Non-input classifications must not smuggle free expressions via binding.
        issues.append(
            PatchIssue(
                "unexpected_binding",
                f"binding only allowed when classification==input_derived (got {classification})",
            )
        )

    evidence = patch.get("evidence") or []
    if not isinstance(evidence, list) or not evidence:
        issues.append(PatchIssue("missing_evidence", "evidence list required"))
    else:
        for i, row in enumerate(evidence):
            if not isinstance(row, dict):
                issues.append(PatchIssue("bad_evidence", "evidence entry must be a map", path=f"evidence[{i}]"))
                continue
            rel = str(row.get("file") or "").replace("\\", "/")
            line = int(row.get("line") or 0)
            snippet = str(row.get("snippet") or "")
            if not rel or line <= 0:
                issues.append(
                    PatchIssue("bad_evidence", "file and line required", path=f"evidence[{i}]")
                )
                continue
            candidates = []
            if ops_root is not None:
                candidates.append(Path(ops_root) / rel)
                candidates.append(Path(rel))
            else:
                candidates.append(Path(rel))
            # Also try absolute paths as stored by IR.
            if Path(rel).is_file():
                candidates.insert(0, Path(rel))
            hit = next((p for p in candidates if p.is_file()), None)
            if hit is None or not _snippet_matches(hit, line, snippet):
                issues.append(
                    PatchIssue(
                        "evidence_mismatch",
                        f"snippet does not match {rel}:{line}",
                        path=f"evidence[{i}]",
                    )
                )

    return PatchVerdict(ok=not issues, patch=patch, issues=issues)


def validate_patches(
    patches: Iterable[dict[str, Any]],
    *,
    blockers: dict[str, dict[str, Any]],
    var_model: Any,
    ops_root: Path | None = None,
) -> list[PatchVerdict]:
    return [
        validate_patch(p, blockers=blockers, var_model=var_model, ops_root=ops_root)
        for p in patches
        if isinstance(p, dict)
    ]


def merge_accepted(
    existing: list[dict[str, Any]],
    verdicts: list[PatchVerdict],
    *,
    blockers: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (new_bindings, accepted_rows, rejected_rows)."""
    blockers = blockers or {}
    by_id = {
        str(b.get("blocker_id")): dict(b)
        for b in existing
        if b.get("blocker_id")
    }
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for v in verdicts:
        row = dict(v.patch)
        bid = str(row.get("blocker_id") or "")
        if v.ok:
            blk = blockers.get(bid) or {}
            affected = list(blk.get("affected_nodes") or row.get("affected_nodes") or [])
            guard_ids = [
                n for n in affected if str(n).startswith("UG_")
            ] + list(row.get("guard_ids") or [])
            # de-dupe
            seen: list[str] = []
            for g in guard_ids:
                if g not in seen:
                    seen.append(str(g))
            entry = {
                "blocker_id": bid,
                "classification": row.get("classification"),
                "binding": _as_dict(row.get("binding")) or None,
                "evidence": list(row.get("evidence") or []),
                "affected_nodes": affected,
                "guard_ids": seen,
                "text": blk.get("text") or row.get("text") or "",
            }
            by_id[bid] = entry
            accepted.append({**row, "status": "accepted"})
        else:
            rejected.append(
                {
                    **row,
                    "status": "rejected",
                    "issues": [i.to_dict() for i in v.issues],
                }
            )
    return list(by_id.values()), accepted, rejected


def binding_condition(binding: dict[str, Any]) -> dict[str, Any] | None:
    """`{var_id, op, value}` as an SMT-lite condition, or None if incomplete.

    This is the whole content of an `input_derived` verdict: a statement that
    the guard the model could not read is really this test on a known variable.
    """
    binding = _as_dict(binding)
    var_id = str(binding.get("var_id") or "")
    op = str(binding.get("op") or "")
    if not var_id or op not in BINDING_OPS or "value" not in binding:
        return None
    value = binding.get("value")
    if op == "in":
        values = value if isinstance(value, list) else [value]
        return {"op": "in", "var": var_id, "values": list(values)}
    return {"op": op, "var": var_id, "value": value}


def apply_bindings_to_derivation(doc: Any, bindings: list[dict[str, Any]]) -> dict[str, int]:
    """Mutate a HostDerivation in place using accepted ledger rows.

    An `input_derived` verdict has to be substituted into `value_expr`, not
    merely struck from the guard list. Removing the record on its own left the
    free variable sitting in the expression with nothing left to explain it:
    the solver still treated the guard as "either way", while the escalation
    counters reported it closed. That is how a field reached `derived` while
    its condition was still weaker than the source.

    Returns counters used by the loop gate: escalating_before/after, etc.
    """
    from uo_init.derive_key_fields import (
        classify_exactness,
        collect_vars_dag,
        status_of_exactness,
        substitute_vars,
    )

    before = sum(len(f.escalating) for f in getattr(doc, "fields", []) or [])
    by_guard: dict[str, dict[str, Any]] = {}
    by_text: dict[str, dict[str, Any]] = {}
    field_cls: dict[str, dict[str, Any]] = {}
    for b in bindings:
        for gid in b.get("guard_ids") or []:
            by_guard[str(gid)] = b
        text = str(b.get("text") or "").strip()
        if text:
            by_text[text] = b
        for nid in b.get("affected_nodes") or []:
            if str(nid).startswith("KEYFIELD_"):
                field_cls[str(nid)[len("KEYFIELD_") :]] = b

    resolved = 0
    softened = 0
    unusable = 0
    for fld in getattr(doc, "fields", []) or []:
        field_binding = field_cls.get(fld.name)
        kept = []
        substitutions: dict[str, Any] = {}
        for guard in list(fld.undecided_guards or []):
            binding = (
                by_guard.get(guard.id)
                or by_text.get(str(guard.text or "").strip())
                or field_binding
            )
            if binding is None:
                kept.append(guard)
                continue
            cls = str(binding.get("classification") or "")
            if cls in ("scheduling", "validation_assumption"):
                # Still an over-approximation, just one we accept on purpose.
                # It stays recorded so the field never reads as exact.
                guard.presort = "scheduling"
                guard.escalate = False
                kept.append(guard)
                softened += 1
            elif cls == "input_derived":
                condition = binding_condition(binding.get("binding"))
                if condition is None:
                    # "It comes from the input" with no statement of *what* it
                    # tests teaches us nothing substitutable. Keep the guard.
                    kept.append(guard)
                    unusable += 1
                    continue
                substitutions[guard.var_id] = condition
                resolved += 1
            else:
                kept.append(guard)
        fld.undecided_guards = kept
        if substitutions and fld.value_expr is not None:
            fld.value_expr = substitute_vars(fld.value_expr, substitutions)
            fld.variables = sorted(collect_vars_dag(fld.value_expr))
            fld.exactness, fld.free_vars = classify_exactness(
                value_expr=fld.value_expr,
                variables=fld.variables,
                unresolved=fld.unresolved,
            )
            fld.status = status_of_exactness(fld.exactness)
    after = sum(len(f.escalating) for f in getattr(doc, "fields", []) or [])
    return {
        "escalating_before": before,
        "escalating_after": after,
        "resolved": resolved,
        "softened": softened,
        "unusable": unusable,
    }
