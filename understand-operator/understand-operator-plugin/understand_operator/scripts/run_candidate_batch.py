from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from understand_operator._operator.artifacts import existing_operator_root, safe_op_name
from understand_operator._operator.candidate import CandidateError, load_json
from understand_operator._operator.repair_controller import MAX_ATTEMPTS, mark_repair_completed, read_repair_state, record_repair_attempt, repair_key_for_batch
from understand_operator.scripts.compile_candidate_facts import compile_candidate_facts
from understand_operator.scripts.validate_candidate_batch import validate_candidate_batch


def run_candidate_batch(repo_root: Path, op_name: str, batch_path: Path) -> tuple[int, dict[str, Any]]:
    repo_root = repo_root.resolve()
    op_name = safe_op_name(op_name, repo_root)
    uo_root = existing_operator_root(repo_root, op_name)
    try:
        batch = load_json(batch_path)
    except CandidateError as exc:
        return 2, {"status": "fail", "phase": "load", "errors": [exc.to_dict()]}
    task = batch.get("task") if isinstance(batch, dict) and isinstance(batch.get("task"), dict) else {}
    target = batch.get("target") if isinstance(batch, dict) and isinstance(batch.get("target"), dict) else {}
    run_id = str(task.get("run_id") or "")
    task_id = str(task.get("task_id") or "unknown_task")
    owner = str(task.get("owner") or "unknown-owner")
    repair_key = repair_key_for_batch(
        run_id,
        owner,
        target,
        batch.get("items") or [],
        batch.get("relations") or [],
        batch.get("unresolved") or [],
    )
    lock_path = batch_path.with_suffix(batch_path.suffix + ".lock")
    lock_fd: int | None = None
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(lock_fd, str(os.getpid()).encode("ascii", errors="ignore"))
        state = read_repair_state(uo_root, run_id, repair_key)
        if state.get("status") == "exhausted" or int(state.get("attempt") or 0) >= MAX_ATTEMPTS:
            return 2, {
                "status": "exhausted",
                "phase": "preflight",
                "errors": [{
                    "code": "CANDIDATE_REPAIR_EXHAUSTED",
                    "message": "candidate repair attempts exhausted",
                    "target": target,
                    "task_id": task_id,
                    "repair_key": repair_key,
                    "attempt": int(state.get("attempt") or MAX_ATTEMPTS),
                    "max_attempts": MAX_ATTEMPTS,
                    "candidate_path": str(batch_path),
                }],
            }
        errors = validate_candidate_batch(repo_root, op_name, batch)
        phase = "validate"
        if not errors:
            errors = compile_candidate_facts(repo_root, op_name, batch)
            phase = "compile"
        if errors:
            error_dicts = [error.to_dict() for error in errors]
            repair = record_repair_attempt(uo_root, run_id, repair_key, task_id, owner, target, str(batch_path), error_dicts)
            status = "exhausted" if repair else "retrying"
            return 2, {"status": status, "phase": phase, "errors": error_dicts, "repair": repair}
        state = mark_repair_completed(uo_root, run_id, repair_key, task_id, owner, target, str(batch_path))
        return 0, {"status": "pass", "phase": "compile", "errors": [], "repair_state": state}
    except FileExistsError:
        return 2, {"status": "fail", "phase": "lock", "errors": [{"code": "CANDIDATE_FILE_LOCKED", "message": "candidate file is already being processed", "candidate_path": str(batch_path)}]}
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
            lock_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate, repair-track, and compile one Candidate JSON batch.")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name")
    parser.add_argument("--batch", required=True, type=Path)
    args = parser.parse_args(argv)
    code, payload = run_candidate_batch(Path(args.repo), args.op_name or "", args.batch)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
