# -*- coding: utf-8 -*-
"""Load proof and derived rules, and ask them about an instance.

Two grades live in two files: proof_rules.yaml is written by a person (or an
LLM quoting source), derived_rules.yaml by the solver. Both answer the same
question -- which dimension values cannot occur -- and the runtime
counterexample gate refuses to believe either when a real witness contradicts
it. source_hash on the derived file is what keeps a stale solve from silently
excluding keys the current derivation would allow.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml


@dataclass(frozen=True)
class Rule:
    kind: str                 # value_unreachable | combo
    grade: str                # human | llm | solver_derived
    label: str                # what excluded_by returns
    reason: str = ""
    dim: str = ""
    value: str = ""
    when: Mapping[str, str] = field(default_factory=dict)


@dataclass
class RuleBook:
    rules: tuple[Rule, ...] = ()
    source_hash: str = ""
    expected_hash: str = ""

    def excluded_by(self, inst: Mapping[str, Any]) -> list[str]:
        out = []
        for rule in self.rules:
            if rule.kind == "value_unreachable":
                if str(inst.get(rule.dim)) == rule.value:
                    out.append(rule.label)
            elif rule.kind == "combo":
                if all(str(inst.get(d)) == v for d, v in rule.when.items()):
                    out.append(rule.label)
        return out

    def hash_ok(self) -> bool:
        if not self.expected_hash:
            return True
        return self.source_hash == self.expected_hash


def source_hash(*payloads: bytes | str) -> str:
    h = hashlib.sha256()
    for p in payloads:
        h.update(p if isinstance(p, bytes) else str(p).encode("utf-8"))
    return h.hexdigest()[:16]


def load_proof(path: str | Path) -> RuleBook:
    path = Path(path)
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    grade = str(doc.get("grade") or "human")
    rules: list[Rule] = []
    for raw in doc.get("value_unreachable") or []:
        dim, value = str(raw["dim"]), str(raw["value"])
        rules.append(Rule(
            kind="value_unreachable", grade=grade,
            label=f"{dim}={value}", reason=str(raw.get("reason") or ""),
            dim=dim, value=value))
    evidence = doc.get("combo_evidence") or {}
    for raw in doc.get("combos") or []:
        when = {str(k): str(v) for k, v in (raw.get("when") or {}).items()}
        tag = str(raw.get("tag") or "")
        label = " + ".join(f"{d}={v}" for d, v in when.items())
        rules.append(Rule(
            kind="combo", grade=grade, label=label,
            reason=str(evidence.get(tag) or raw.get("reason") or ""),
            when=when))
    return RuleBook(rules=tuple(rules))


def load_derived(path: str | Path, *, expected_hash: str = "") -> RuleBook:
    path = Path(path)
    if not path.is_file():
        return RuleBook(expected_hash=expected_hash)
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    grade = "solver_derived"
    rules: list[Rule] = []
    for raw in doc.get("rules") or doc.get("value_unreachable") or []:
        # The solver states every rule the same way: the (dim, value) pairs
        # that cannot hold at once. One pair is a value that never occurs,
        # several are a combination. `dim`/`value` at the top level, and
        # `left`/`right`, are the hand-written shapes, read here too so that
        # either file can be loaded by this function.
        pairs = [
            (str(e["dim"]), str(e["value"]))
            for e in (raw.get("excludes") or [])
            if e.get("dim") is not None
        ]
        if not pairs and raw.get("dim") is not None and raw.get("value") is not None:
            pairs = [(str(raw["dim"]), str(raw["value"]))]
        if not pairs and raw.get("left") and raw.get("right"):
            pairs = [
                (str(raw["left"]["dim"]), str(raw["left"]["value"])),
                (str(raw["right"]["dim"]), str(raw["right"]["value"])),
            ]
        if not pairs and raw.get("when"):
            pairs = [(str(k), str(v)) for k, v in raw["when"].items()]
        if not pairs:
            continue
        reason = str(raw.get("reason") or raw.get("statement") or "")
        this_grade = str(raw.get("evidence_grade") or grade)
        if len(pairs) == 1:
            dim, value = pairs[0]
            rules.append(Rule(
                kind="value_unreachable", grade=this_grade,
                label=f"{dim}={value}", reason=reason, dim=dim, value=value))
        else:
            label = str(
                raw.get("label")
                or raw.get("statement")
                or " + ".join(f"{d}={v}" for d, v in pairs)
            )
            rules.append(Rule(
                kind="combo", grade=this_grade, label=label,
                reason=reason, when=dict(pairs)))
    return RuleBook(
        rules=tuple(rules),
        source_hash=str(doc.get("source_hash") or ""),
        expected_hash=expected_hash,
    )


def merge(*books: RuleBook) -> RuleBook:
    """Combine rule books, carrying the freshness stamp forward.

    Only the derived book has one, because it is the only one that can go
    stale: it was proved against a derivation that may since have changed. A
    merge that dropped it left `hash_ok` answering yes to every question.
    """
    rules: list[Rule] = []
    src = exp = ""
    for book in books:
        rules.extend(book.rules)
        src = src or book.source_hash
        exp = exp or book.expected_hash
    return RuleBook(rules=tuple(rules), source_hash=src, expected_hash=exp)


_BOOK: RuleBook | None = None


def default_book(*, refresh: bool = False) -> RuleBook:
    """Proof rules of the active operator, plus derived rules if present.

    Held after the first read. Callers ask this per instance -- once per
    declared key, tens of thousands of times -- and parsing both YAML files
    again for each of them costs orders of magnitude more than answering the
    question. `refresh` is for a process that rewrote the files and wants to
    see its own output.
    """
    global _BOOK
    if _BOOK is None or refresh:
        from .runner import default
        package = default().manifest.package
        cache = default().cache
        proof = load_proof(package / "proof_rules.yaml")
        derived = load_derived(cache / "derived_rules.yaml")
        _BOOK = merge(proof, derived)
    return _BOOK
