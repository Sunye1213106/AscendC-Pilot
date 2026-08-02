# -*- coding: utf-8 -*-
"""Run a resolve_gaps part through every gate and report what got through.

Two layers, and they answer different questions. `validate_patch` asks whether
the answer is well formed and made of things that exist. `patch_gates` asks
whether it says anything about this operator that could be false. A patch has
to survive both before it is worth a referee's time.
"""
from __future__ import annotations

import argparse
import pickle
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "engines" / "common"))

STAGE = ROOT / ".probe_cache" / "resolve_gaps"
BUNDLE = ROOT / ".probe_cache" / "fag_bundle.pkl"


def _load_bundle():
    with open(BUNDLE, "rb") as fh:
        return pickle.load(fh)


def _domains_and_constants(var_model):
    domains = {}
    for name, spec in (getattr(var_model, "variables", None) or {}).items():
        domain = getattr(spec, "domain", None)
        if domain is not None:
            domains[name] = domain
    constants = dict(getattr(var_model, "named_constants", None) or {})
    return domains, constants


def main(argv: list[str] | None = None) -> int:
    from uo_init.gap_patch import patch_condition, validate_patches
    from uo_init.host_derivation import HostDerivation, _to_field
    from uo_init.patch_gates import check_patch_condition

    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default=str(STAGE))
    ap.add_argument("--shard", default="000")
    ap.add_argument("--derive", default=str(ROOT / ".probe_cache" / "fag_derive.json"))
    args = ap.parse_args(argv)

    stage = Path(args.stage)
    batch = yaml.safe_load(
        (stage / "inputs" / "batches" / f"batch_{args.shard}.yaml").read_text(
            encoding="utf-8"
        )
    )
    part_path = stage / "parts" / f"part_{args.shard}.yaml"
    if not part_path.is_file():
        print(f"no part at {part_path}")
        return 1
    part = yaml.safe_load(part_path.read_text(encoding="utf-8")) or {}
    patches = [p for p in (part.get("patches") or []) if isinstance(p, dict)]
    blockers = {str(b["id"]): b for b in batch.get("blockers") or [] if b.get("id")}

    import json

    saved = json.loads(Path(args.derive).read_text(encoding="utf-8"))["host_derivation"]
    doc = HostDerivation()
    doc.fields = [_to_field(row, None) for row in saved.get("fields") or []]
    fields = {f.name: f for f in doc.fields}

    bundle = _load_bundle()
    var_model = bundle.get("var_model")
    domains, constants = _domains_and_constants(var_model)

    print(f"{len(patches)} patches for {len(blockers)} blockers\n")
    kinds = Counter(str(p.get("classification") or "?") for p in patches)
    for kind, n in kinds.most_common():
        print(f"  {n:3d}  {kind}")

    verdicts = validate_patches(
        patches, blockers=blockers, var_model=var_model, ops_root=None
    )
    schema_ok = [v for v in verdicts if v.ok]
    print(f"\nform and vocabulary: {len(schema_ok)}/{len(verdicts)} pass")
    for verdict in verdicts:
        if verdict.ok:
            continue
        bid = str(verdict.patch.get("blocker_id") or "?")
        for issue in verdict.issues:
            print(f"  {bid}: {issue.code} — {issue.message[:110]}")

    ok_ids = {str(v.patch.get("blocker_id") or "") for v in schema_ok}
    checked = 0
    clean = 0
    blocked = Counter()
    for patch in patches:
        bid = str(patch.get("blocker_id") or "")
        if bid not in ok_ids:
            continue
        condition = patch_condition(patch)
        if condition is None:
            continue
        blocker = blockers.get(bid) or {}
        var_ids = [
            n
            for n in blocker.get("affected_nodes") or []
            if str(n).startswith("VAR_")
        ]
        names = [
            str(n)[len("KEYFIELD_") :]
            for n in blocker.get("affected_nodes") or []
            if str(n).startswith("KEYFIELD_")
        ]
        field = next((fields[n] for n in names if n in fields), None)
        checked += 1
        findings = check_patch_condition(
            condition,
            var_id=var_ids[0] if var_ids else "",
            value_expr=getattr(field, "value_expr", None) if var_ids else None,
            readable=blocker.get("readable_vars"),
            declared=getattr(field, "domain", None) if field else None,
            domains=domains,
            constants=constants,
        )
        if not findings:
            clean += 1
            continue
        for finding in findings:
            blocked[finding.code] += 1
            print(f"  {bid}: {finding.code} — {finding.message[:100]}")
            if finding.witness:
                print(f"        witness {dict(list(finding.witness.items())[:4])}")

    print(f"\nmechanical checks: {clean}/{checked} clean")
    for code, n in blocked.most_common():
        print(f"  {n:3d}  {code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
