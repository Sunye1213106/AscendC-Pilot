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
        return self.judged and not self.reject.startswith(("HOST_CRASHED", "NOT_RUN"))


@runtime_checkable
class Oracle(Protocol):
    def judge(self, cases: Sequence[Any], *, tag: str = "") -> list[Verdict]:
        ...


class HostOracle:
    """Wraps ``ReplayRunner``; flags batch truncation as ORACLE_SUSPECT."""

    def __init__(self, runner=None):
        self.runner = runner or W.replay_runner()

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

        raw = self.runner.run(batch, tag=tag, check=False)
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
        return out

    def batch_integrity(self, sent: int, done: int) -> str | None:
        if done < sent:
            return "ORACLE_SUSPECT"
        return None


class StubOracle:
    """Deterministic oracle for unit tests (no NPU)."""

    def __init__(self, keys: Sequence[int] | None = None):
        self.keys = list(keys or [])

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
        return out
