"""Deterministically decide whether an LLM fact review is required."""
from __future__ import annotations
import argparse, hashlib, sys
from pathlib import Path
from typing import Any
import yaml
if __package__ in (None, ""):
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path: sys.path.insert(0, str(root))
from understand_operator._operator.artifacts import existing_operator_root, safe_op_name

def evaluate_review_trigger(repo: Path, op_name: str, step: str) -> dict[str, Any]:
    root = existing_operator_root(repo.resolve(), safe_op_name(op_name, repo)); facts = root / "facts"
    fact_paths = list(facts.rglob("*.yaml")) if facts.exists() else []
    unresolved = False
    for path in fact_paths:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        groups = (doc.get("sections") or {}).values() if isinstance(doc.get("sections"), dict) else [doc]
        unresolved |= any(bool(group.get("unresolved")) for group in groups if isinstance(group, dict))
    reports = (root / "checks" / step).glob("*validation*.yaml") if (root / "checks" / step).exists() else []
    failed = any((yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("status") not in {"pass", "skipped"} for p in reports)
    triggered = unresolved or failed
    hashes = {p.relative_to(root).as_posix(): "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(fact_paths)}
    return {"version": 1, "status": "triggered" if triggered else "skipped", "triggered": triggered, "reason": "unresolved_or_validation_failure" if triggered else "no_unresolved_conflict_or_closure_gap", "input_hashes": hashes, "items": [], "relations": [], "unresolved": []}
def main(argv: list[str] | None = None) -> int:
    p=argparse.ArgumentParser(); p.add_argument("repo", nargs="?", default="."); p.add_argument("--op-name", required=True); p.add_argument("--step", choices=("step2","step3"), required=True); a=p.parse_args(argv); root=existing_operator_root(Path(a.repo).resolve(), safe_op_name(a.op_name,Path(a.repo))); data=evaluate_review_trigger(Path(a.repo),a.op_name,a.step); out=root/"checks"/a.step/"review_trigger.yaml"; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(yaml.safe_dump(data,sort_keys=False,allow_unicode=True),encoding="utf-8"); return 0
if __name__ == "__main__": raise SystemExit(main())
