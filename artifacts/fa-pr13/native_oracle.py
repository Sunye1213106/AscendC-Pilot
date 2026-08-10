# -*- coding: utf-8 -*-
"""Host oracle that calls run_replay.sh natively (no nested wsl.exe)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Sequence

from testcase_agent.closure import workspace as W
from testcase_agent.closure.oracle import Verdict, accounting


ENTRY = "/work/wsl/setup/run_replay.sh"


class NativeHostOracle:
    def __init__(self, runner=None):
        self.runner = runner or W.replay_runner()
        self.last_accounting: dict[str, int] = accounting(())

    def judge(self, cases: Sequence[Any], *, tag: str = "closure") -> list[Verdict]:
        from replay import inputs as I

        sent = list(cases)
        batch: dict[str, Any] = {}
        order: list[str] = []
        for i, case in enumerate(sent):
            cid = getattr(case, "tag", None) or f"{tag}_{i}"
            while cid in batch:
                cid = f"{cid}_{i}"
            batch[cid] = case
            order.append(cid)

        if not batch:
            self.last_accounting = accounting(())
            return []

        cache = Path(self.runner.cache)
        cache.mkdir(parents=True, exist_ok=True)
        in_csv = cache / f"{tag}_in.csv"
        out_csv = cache / f"{tag}_out.csv"
        log_txt = cache / f"{tag}_log.txt"
        in_csv.write_text(
            "\n".join(I.to_csv_line(c, cid) for cid, c in batch.items()) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        env = os.environ.copy()
        env["ASCEND_SLOG_PRINT_TO_STDOUT"] = "0"
        env["ASCEND_GLOBAL_LOG_LEVEL"] = "3"
        try:
            proc = subprocess.run(
                ["bash", ENTRY, str(in_csv), str(out_csv), str(log_txt), "0"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            out = [
                Verdict(case_id=cid, reject=f"HOST_CRASHED:{type(exc).__name__}", judged=False)
                for cid in order
            ]
            self.last_accounting = accounting(out, generated=len(sent), serialized=len(sent))
            return out

        text = log_txt.read_text(encoding="utf-8", errors="replace") if log_txt.is_file() else ""
        if "BATCH_DONE" not in (proc.stdout or "") and not text:
            out = [
                Verdict(case_id=cid, reject="HOST_CRASHED:no_batch_done", judged=False)
                for cid in order
            ]
            self.last_accounting = accounting(out, generated=len(sent), serialized=len(sent))
            return out

        parsed = self.runner.parse_log(text) if text else {}
        done = set(self.runner.finished_ids(text)) if text else set()
        out: list[Verdict] = []
        for cid in order:
            r = parsed.get(cid)
            if r is None:
                out.append(
                    Verdict(
                        case_id=cid,
                        reject="NOT_RUN:missing_in_log",
                        judged=False,
                    )
                )
                continue
            out.append(
                Verdict(
                    case_id=str(getattr(r, "case_id", "") or cid),
                    ok=bool(getattr(r, "ok", False)),
                    key=int(getattr(r, "key", 0) or 0),
                    dims=dict(getattr(r, "dims", {}) or {}),
                    reject=str(getattr(r, "reject", "") or ""),
                    judged=cid in done or bool(getattr(r, "ok", False) or getattr(r, "key", 0)),
                )
            )
        self.last_accounting = accounting(out, generated=len(sent), serialized=len(sent))
        return out

    def batch_integrity(self, sent: int, done: int) -> str | None:
        if done < sent:
            return "ORACLE_SUSPECT"
        return None
