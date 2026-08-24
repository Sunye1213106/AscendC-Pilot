# -*- coding: utf-8 -*-
"""Fold replay slices into an init-shaped product and score it.

Mirrors what `bind_promote` does in a real run: merge `bindN.yaml` into `bind.yaml`,
restore engine-owned fields on both parts, then overlay the contract fields that only
appear on the canonical product (`defaults`, `test_script_root`). The result is graded
by `grade_init.py`.

Usage:
    python evals/tg_init/score_replay.py --replay .pytest-tmp/replay/bind_init \
        --repo <test script root> --rubric <rubric.yaml> [--elapsed 210]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "engines" / "testcase-generation"))

from testcase_agent import bind_parts as BP  # noqa: E402
from testcase_agent import test_repo as TR  # noqa: E402


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return doc if isinstance(doc, dict) else {}


def promote(replay: Path, repo: Path) -> tuple[Path, dict[str, Any]]:
    parts = replay / "parts"
    result = BP.restore_and_dump_parts(parts)
    bind = _load(parts / "bind.yaml")
    harness = _load(parts / "harness.yaml")

    product: dict[str, Any] = {}
    for doc in (bind, harness):
        for key, value in doc.items():
            if key in {"schema", "artifact_identity", "llm_edit", "run_id", "workflow_id",
                       "action_id", "actor_id"}:
                continue
            if value in (None, "", [], {}) and key in product:
                continue
            product[key] = value

    contract = TR.contract_from_inventory(TR.scan(repo))
    product.setdefault("schema", "tg-init/v1")
    product["defaults"] = dict(contract.get("defaults") or {})
    product["test_script_root"] = str(repo)

    out = replay / "promoted.init.yaml"
    out.write_text(yaml.safe_dump(product, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return out, result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--replay", required=True, type=Path)
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--rubric", required=True, type=Path)
    ap.add_argument("--elapsed", type=float, default=None)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    product, restore = promote(args.replay.resolve(), args.repo.resolve())
    if not restore.get("ok"):
        print(f"restore_and_dump_parts failed: {restore}")
    print(f"promoted -> {product}\n")

    cmd = [
        sys.executable,
        str(REPO_ROOT / "evals" / "tg_init" / "grade_init.py"),
        "--rubric", str(args.rubric),
        "--product", str(product),
        "--repo", str(args.repo),
    ]
    if args.elapsed is not None:
        cmd += ["--elapsed", str(args.elapsed)]
    if args.json:
        cmd += ["--json", str(args.json)]
    return subprocess.call(cmd, cwd=str(REPO_ROOT))


if __name__ == "__main__":
    sys.exit(main())
