# -*- coding: utf-8 -*-
"""Oracle protocol for closure search: Host judges cases, never models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence, runtime_checkable

from testcase_agent.closure import workspace as W


@dataclass
class Verdict:
    case_id: str
    ok: bool = False
    key: int = 0
    dims: dict = field(default_factory=dict)
    reject: str = ""
    judged: bool = True

    @property
    def verdict(self) -> bool:
        return self.judged and not self.reject.startswith(
            ("HOST_CRASHED", "NOT_RUN", "PARSE_FAILED")
        )


def accounting(
    verdicts: Sequence[Verdict],
    *,
    generated: int | None = None,
    normalised_unique: int | None = None,
    serialized: int | None = None,
) -> dict[str, int]:
    """Return the complete Oracle accounting ledger for one replay batch.

    Only ``accepted`` and ``rejected`` are judged outcomes.  A driver crash,
    a missing result and a parse failure remain operational evidence; none is
    a negative model result or evidence for E.
    """
    requested = len(verdicts)
    counts = {
        "requested": requested,
        "generated": requested if generated is None else int(generated),
        "normalised_unique": requested if normalised_unique is None else int(normalised_unique),
        "serialized": requested if serialized is None else int(serialized),
        "driver_started": 0,
        "accepted": 0,
        "rejected": 0,
        "crashed": 0,
        "not_run": 0,
        "parse_failed": 0,
    }
    for verdict in verdicts:
        reason = str(verdict.reject or "").upper()
        if reason.startswith("PARSE_FAILED") or reason.startswith("PARSE_FAIL"):
            counts["parse_failed"] += 1
        elif reason.startswith("HOST_CRASHED") or reason.startswith("CRASH"):
            counts["crashed"] += 1
        elif reason.startswith("NOT_RUN") or not verdict.judged:
            counts["not_run"] += 1
        elif verdict.ok:
            counts["accepted"] += 1
        else:
            counts["rejected"] += 1
    counts["driver_started"] = (
        counts["accepted"] + counts["rejected"] + counts["crashed"]
    )
    counts["actually_run"] = counts["driver_started"]
    counts["judged"] = counts["accepted"] + counts["rejected"]
    counts["conserved"] = int(
        counts["requested"]
        == counts["accepted"]
        + counts["rejected"]
        + counts["crashed"]
        + counts["not_run"]
        + counts["parse_failed"]
    )
    return counts


@runtime_checkable
class Oracle(Protocol):
    def judge(self, cases: Sequence[Any], *, tag: str = "") -> list[Verdict]:
        ...


class HostOracle:
    """Wraps ``ReplayRunner``; flags batch truncation as ORACLE_SUSPECT."""

    def __init__(self, runner=None):
        self.runner = runner or W.replay_runner()
        self.last_accounting: dict[str, int] = accounting(())

    def judge(self, cases: Sequence[Any], *, tag: str = "closure") -> list[Verdict]:
        sent = list(cases)
        batch: dict[str, Any] = {}
        order: list[str] = []
        for i, case in enumerate(sent):
            cid = getattr(case, "tag", None) or f"{tag}_{i}"
            # Avoid collisions when cases share tags.
            while cid in batch:
                cid = f"{cid}_{i}"
            batch[cid] = case
            order.append(cid)

        try:
            raw = self.runner.run(batch, tag=tag, check=False)
        except Exception as exc:  # noqa: BLE001
            out = [
                Verdict(
                    case_id=cid,
                    reject=f"HOST_CRASHED:{type(exc).__name__}",
                    judged=False,
                )
                for cid in order
            ]
            self.last_accounting = accounting(out, generated=len(sent), serialized=len(sent))
            return out
        # Runner returns dict[str, Result]; preserve send order.
        results_by_id = raw if isinstance(raw, dict) else {}
        if not isinstance(raw, dict) and isinstance(raw, (list, tuple)):
            results_by_id = {
                order[i] if i < len(order) else f"{tag}_{i}": r
                for i, r in enumerate(raw)
            }

        out: list[Verdict] = []
        done = 0
        for cid in order:
            r = results_by_id.get(cid)
            if r is None:
                out.append(Verdict(
                    case_id=cid,
                    reject="NOT_RUN:batch_truncated",
                    judged=False,
                ))
                continue
            done += 1
            out.append(Verdict(
                case_id=str(getattr(r, "case_id", "") or cid),
                ok=bool(getattr(r, "ok", False)),
                key=int(getattr(r, "key", 0) or 0),
                dims=dict(getattr(r, "dims", {}) or {}),
                reject=str(getattr(r, "reject", "") or ""),
                judged=bool(getattr(r, "verdict", True)),
            ))
        flag = self.batch_integrity(len(sent), done)
        if flag:
            # Soft signal for callers; route() also watches state/oracle_suspect.
            try:
                ws = W.default_workspace().ensure()
                (ws.state / "oracle_suspect").write_text(flag, encoding="utf-8")
            except Exception:
                pass
        self.last_accounting = accounting(out, generated=len(sent), serialized=len(sent))
        return out

    def batch_integrity(self, sent: int, done: int) -> str | None:
        if done < sent:
            return "ORACLE_SUSPECT"
        return None


class StubOracle:
    """Deterministic oracle for unit tests (no NPU)."""

    def __init__(self, keys: Sequence[int] | None = None):
        self.keys = list(keys or [])
        self.last_accounting: dict[str, int] = accounting(())

    def judge(self, cases: Sequence[Any], *, tag: str = "") -> list[Verdict]:
        out = []
        for i, _c in enumerate(cases):
            key = self.keys[i] if i < len(self.keys) else 0
            out.append(Verdict(
                case_id=f"{tag}_{i}",
                ok=key > 0,
                key=int(key),
                judged=True,
            ))
        self.last_accounting = accounting(out, generated=len(cases), serialized=len(cases))
        return out


def count_done_marks(text: str) -> int:
    """Count ``###DONE`` lines in driver log text."""
    return sum(1 for line in str(text or "").splitlines() if line.lstrip().startswith("###DONE"))


def validate_wide_csv(path: Any) -> dict[str, Any]:
    """Check every data row has the same column count as the header."""
    from pathlib import Path

    p = Path(path)
    if not p.is_file():
        return {"ok": False, "error": "missing", "bad_rows": []}
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        return {"ok": False, "error": "empty", "bad_rows": []}
    header_n = len(lines[0].split(","))
    bad: list[dict[str, Any]] = []
    for i, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        n = len(line.split(","))
        if n != header_n:
            bad.append({"line": i, "cols": n, "expected": header_n})
    return {
        "ok": len(bad) == 0,
        "header_cols": header_n,
        "rows": max(0, len(lines) - 1),
        "bad_rows": bad[:20],
    }


def check_driver_config(manifest_or_protocol: dict[str, Any] | None) -> dict[str, Any]:
    """If compileInfo / required driver config keys exist, they must be non-empty."""
    doc = dict(manifest_or_protocol or {})
    required_keys = []
    for key in ("compileInfo", "compile_info", "driver_config", "required_driver_config"):
        if key in doc:
            required_keys.append(key)
    nested = doc.get("driver") if isinstance(doc.get("driver"), dict) else {}
    for key in ("compileInfo", "compile_info"):
        if key in nested:
            required_keys.append(f"driver.{key}")
    empty: list[str] = []
    for key in required_keys:
        if key.startswith("driver."):
            val = nested.get(key.split(".", 1)[1])
        else:
            val = doc.get(key)
        if val is None or val == "" or val == {} or val == []:
            empty.append(key)
    return {
        "ok": len(empty) == 0,
        "checked": required_keys,
        "empty": empty,
    }


def warn_singleton_dims(corpus_rows: Sequence[dict[str, Any]], dims: Sequence[str]) -> list[str]:
    """Warn when a dim has only one observed value across the corpus."""
    from collections import defaultdict

    seen: dict[str, set[str]] = defaultdict(set)
    for row in corpus_rows:
        for d in dims:
            if d in row and row[d] is not None and str(row[d]) != "":
                seen[d].add(str(row[d]))
    return [d for d in dims if len(seen.get(d, ())) == 1]


def write_oracle_suspect(ws: W.Workspace | None, reason: str) -> str:
    ws = (ws or W.default_workspace()).ensure()
    path = ws.state / "oracle_suspect"
    prev = path.read_text(encoding="utf-8") if path.is_file() else ""
    text = (prev + "\n" + reason).strip() if prev.strip() else reason
    path.write_text(text + "\n", encoding="utf-8")
    return str(path)


def selfcheck(
    *,
    sent: int | None = None,
    done_count: int | None = None,
    wide_csv: Any = None,
    driver_doc: dict[str, Any] | None = None,
    corpus_rows: Sequence[dict[str, Any]] | None = None,
    dims: Sequence[str] | None = None,
    ws: W.Workspace | None = None,
) -> dict[str, Any]:
    """Run oracle integrity checks; write ``oracle_suspect`` on hard failures."""
    issues: list[str] = []
    warnings: list[str] = []

    if sent is not None and done_count is not None and int(sent) != int(done_count):
        issues.append(
            f"ORACLE_SUSPECT:sent_vs_DONE mismatch sent={sent} done={done_count}"
        )

    if wide_csv is not None:
        csv_check = validate_wide_csv(wide_csv)
        if not csv_check.get("ok"):
            issues.append(
                f"ORACLE_SUSPECT:wide_csv_columns bad_rows={len(csv_check.get('bad_rows') or [])}"
            )

    if driver_doc is not None:
        cfg = check_driver_config(driver_doc)
        if not cfg.get("ok"):
            issues.append(
                f"ORACLE_SUSPECT:driver_config_empty:{','.join(cfg.get('empty') or [])}"
            )

    if corpus_rows is not None and dims:
        singles = warn_singleton_dims(corpus_rows, dims)
        for d in singles:
            warnings.append(f"dim_singleton_value:{d}")

    flag_path = ""
    if issues:
        flag_path = write_oracle_suspect(ws, "\n".join(issues))

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "oracle_suspect": flag_path,
    }
