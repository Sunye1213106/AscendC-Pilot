# -*- coding: utf-8 -*-
"""Cluster normalization failures into blockers — the unit of LLM work.

Open control nodes are the symptom, not the problem. One unresolved symbol
routinely holds dozens of branches open, so batching semantic work per node
asks the same question over and over. Clustering by the failing atom collapses
that back to the real question count.

This is shared infrastructure on purpose: the export layer, the gate that
checks patch evidence and the subagent prompt all have to agree on what a
blocker is and how it is identified.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from uo_init.ids import hash12
from uo_init.kb_model import Blocker, Evidence

# Reasons ordered by how much a human/LLM can actually do about them. When one
# node fails for several reasons, the most actionable one names the blocker.
REASON_PRIORITY = [
    "UNMAPPED_SYMBOL",
    "UNMAPPED_CALL",
    "FUNCTION_PARAMETER",
    "TILING_DATA_NO_WRITER",
    "CYCLIC_FIELD_DEPENDENCY",
    "UNSUPPORTED_OPERATOR",
    "OPAQUE_EXPRESSION",
    "DERIVATION_UNDECIDED",
    "DERIVATION_DEPTH_EXCEEDED",
    "PARSE_FAILED",
    "NO_CONDITION_TEXT",
    "NO_HOST_IR",
]

# What each reason is actually asking for, so the prompt does not have to
# re-derive it and every blocker of a kind is asked the same way.
REASON_HINT = {
    "UNMAPPED_SYMBOL": "识别该符号代表什么：算子输入/属性/平台量/常量，并给出 path:line 证据",
    "UNMAPPED_CALL": "确认该调用的返回值来源，是否等价于某个已知访问器",
    "FUNCTION_PARAMETER": "找出该形参在所有调用点传入的实参，判断是否统一来源",
    "TILING_DATA_NO_WRITER": "定位该 TilingData 字段的写点；若写在未纳入范围的文件里请指出",
    "CYCLIC_FIELD_DEPENDENCY": "打破字段互相赋值的环，指出真正的初始来源",
    "UNSUPPORTED_OPERATOR": "该表达式含位运算等不可线性化算子，判断能否等价改写",
    "OPAQUE_EXPRESSION": "表达式结构无法归一化，说明其语义或标记为不可控",
    "DERIVATION_UNDECIDED": (
        "从封闭词汇表判定该 guard：scheduling / input_derived / "
        "validation_assumption / genuinely_unknown；若 input_derived 则绑定已声明 var_id"
    ),
    "DERIVATION_DEPTH_EXCEEDED": "推导链过深，指出中间可以直接认定的那一跳",
    "PARSE_FAILED": "条件文本无法解析，确认是否被宏截断",
    "NO_CONDITION_TEXT": "条件来自宏展开且无可读文本，指出宏定义位置",
    "NO_HOST_IR": "缺少 Host IR，检查该文件是否在分析范围内",
}

_WS = re.compile(r"\s+")
# `fBaseParams.queryType<-queryType` — the resolver appends the deepest blocker
# after `<-`; that tail is the thing actually in question.
_CHAIN = re.compile(r"<-")
# Truncated macro text that is not a real unresolved symbol for LLM work.
_NOISE_ATOMS = frozenset(
    {"for", "while", "if", "switch", "return", "do", "sizeof", "?", ":", "::", "/"}
)


def blocker_key(text: str, reason: str) -> str:
    return f"BLK_{hash12(reason, normalize_atom_text(text))}"


def normalize_atom_text(text: str) -> str:
    """Collapse whitespace and keep the deepest *informative* link of a chain.

    Prefer a longer identifier over a 1–2 character tail (`dqRopeNum<-p` →
    `dqRopeNum`) so blockers cluster on the real symbol, not a scratch local.
    """
    t = _WS.sub(" ", str(text or "").strip())
    if not _CHAIN.search(t):
        return t
    parts = [p.strip() for p in t.split("<-") if p.strip()]
    if not parts:
        return t
    tail = parts[-1]
    if len(tail) <= 2 and len(parts) >= 2:
        prev = parts[-2]
        if len(prev) > 2:
            return prev
    return tail


def pick_reason(reasons: Iterable[str]) -> str:
    """The most actionable reason among several."""
    present = [r.split(":")[0] for r in reasons if r]
    for candidate in REASON_PRIORITY:
        if candidate in present:
            return candidate
    return present[0] if present else "UNKNOWN"


@dataclass
class GapItem:
    """One node's failure, before clustering."""

    node_id: str
    text: str
    reason: str
    file: str = ""
    line: int = 0
    snippet: str = ""
    function: str = ""


def collect_gap_items(analyses) -> list[GapItem]:
    """Pull the failing atoms out of each unresolved node analysis.

    A node contributes one item per distinct failing atom, not one per node:
    a guard blocked by two different symbols is two questions.
    """
    items: list[GapItem] = []
    for a in analyses:
        if a.closed:
            continue
        node = a.node
        seen: set[tuple[str, str]] = set()
        for atom in _failing_atoms(a):
            reason = (atom.reason or "UNKNOWN").split(":")[0]
            text = normalize_atom_text(atom.text)
            if not text or text in _NOISE_ATOMS or (text, reason) in seen:
                continue
            # Pure punctuation / parse-noise reasons are not LLM tasks.
            if reason.startswith("unexpected_token") or reason == "NO_CONDITION_TEXT":
                if text in _NOISE_ATOMS or len(text) <= 2:
                    continue
                if text.lstrip().startswith(("for", "while", "do", "switch")):
                    continue
            seen.add((text, reason))
            items.append(
                GapItem(
                    node_id=a.branch_id,
                    text=text,
                    reason=reason,
                    file=node.file,
                    line=node.line,
                    snippet=(node.condition or node.snippet or "")[:200],
                    function=node.function,
                )
            )
        if not seen:
            # Normalization failed without a resolver-level atom, e.g. an
            # unsupported operator. The predicate reason is the blocker.
            # Skip when the only "failure" was keyword / punctuation noise.
            cond = normalize_atom_text(node.condition or "")
            if cond in _NOISE_ATOMS:
                continue
            reason = a.own.reason or pick_reason(a.reasons)
            if (reason or "").startswith("unexpected_token") or reason == "NO_CONDITION_TEXT":
                if not cond or cond in _NOISE_ATOMS or len(cond) <= 2:
                    continue
                if cond.lstrip().startswith(("for", "while", "do", "switch")):
                    continue
            items.append(
                GapItem(
                    node_id=a.branch_id,
                    text=cond or normalize_atom_text(a.own.detail or ""),
                    reason=reason,
                    file=node.file,
                    line=node.line,
                    snippet=(node.condition or node.snippet or "")[:200],
                    function=node.function,
                )
            )
    return items


def _failing_atoms(analysis):
    """Atoms that blocked resolution, including partial roots.

    A `TILING_DATA` field with no locatable writer carries a root, so it is not
    caught by `reason is None`; it is still an open question.
    """
    return [a for a in getattr(analysis, "atoms", []) if a.reason or a.partial]


def cluster(items: Iterable[GapItem]) -> list[Blocker]:
    """Group failures by (normalized text, reason).

    The resulting count is what the subagent is asked to work through, and it
    is typically several times smaller than the open-node count.
    """
    by_key: dict[str, Blocker] = {}
    for item in items:
        key = blocker_key(item.text, item.reason)
        blocker = by_key.get(key)
        if blocker is None:
            blocker = Blocker(
                id=key,
                text=item.text,
                reason_code=item.reason,
                hint=REASON_HINT.get(item.reason, ""),
            )
            by_key[key] = blocker
        if item.node_id not in blocker.affected_nodes:
            blocker.affected_nodes.append(item.node_id)
        if item.file and len(blocker.evidence) < 5:
            ev = Evidence.at(item.file, item.line, snippet=item.snippet)
            if ev.id not in {e.id for e in blocker.evidence}:
                blocker.evidence.append(ev)
    # Most-blocking first: fixing the top of this list moves the metric most.
    return sorted(by_key.values(), key=lambda b: (-len(b.affected_nodes), b.id))


@dataclass
class GapReport:
    blockers: list[Blocker] = field(default_factory=list)
    open_node_count: int = 0

    @property
    def blocker_count(self) -> int:
        return len(self.blockers)

    @property
    def compression(self) -> float:
        """Open nodes per blocker — how much clustering saved."""
        if not self.blockers:
            return 0.0
        return round(self.open_node_count / len(self.blockers), 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "status": "extracted" if self.blockers else "closed",
            "open_node_count": self.open_node_count,
            "blocker_count": self.blocker_count,
            "nodes_per_blocker": self.compression,
            "note": (
                "分片单位是 blocker 而不是节点：一个符号常常同时挡住几十个分支，"
                "按节点分片会把同一个问题问很多遍"
            ),
            "blockers": [b.to_dict() for b in self.blockers],
        }


def collect_derivation_gap_items(host_derivation) -> list[GapItem]:
    """Escalate undecided key-field guards that pre-sort could not soften.

    Scheduling guards stay out of this list on purpose: they are soft by
    design and must not become LLM work. Everything else (unmapped / platform /
    unknown) is one question per guard id, tagged onto the key field it blocks.
    """
    items: list[GapItem] = []
    fields = getattr(host_derivation, "fields", None) or []
    for fld in fields:
        for guard in getattr(fld, "escalating", None) or []:
            text = normalize_atom_text(getattr(guard, "text", "") or "")
            if not text or text in _NOISE_ATOMS:
                continue
            reason = (getattr(guard, "reason", "") or "DERIVATION_UNDECIDED").split(":")[0]
            if reason in ("SCHED_SOFT", "scheduling"):
                continue
            # Keep the actionable derivation reason even when the normalizer
            # already labelled the failure UNMAPPED_*: the hint tells the LLM
            # to answer inside the closed vocabulary.
            if reason not in REASON_HINT:
                reason = "DERIVATION_UNDECIDED"
            else:
                # Prefer the derivation-specific ask when the failure came from
                # key-field expansion rather than a host-branch predicate.
                reason = "DERIVATION_UNDECIDED"
            ev = getattr(guard, "evidence", None) or {}
            items.append(
                GapItem(
                    node_id=f"KEYFIELD_{fld.name}",
                    text=text,
                    reason=reason,
                    file=str(ev.get("file") or ""),
                    line=int(ev.get("line") or 0),
                    snippet=str(ev.get("snippet") or text)[:200],
                    function=str(getattr(fld, "name", "") or ""),
                )
            )
            # Attach the stable guard id as a second affected-node tag via a
            # synthetic item key that cluster will merge (same text+reason).
            gid = str(getattr(guard, "id", "") or "")
            if gid:
                items.append(
                    GapItem(
                        node_id=gid,
                        text=text,
                        reason=reason,
                        file=str(ev.get("file") or ""),
                        line=int(ev.get("line") or 0),
                        snippet=str(ev.get("snippet") or text)[:200],
                        function=str(getattr(fld, "name", "") or ""),
                    )
                )
    return items


def merge_gap_reports(*reports: GapReport) -> GapReport:
    """Union blockers from several reports; keep highest affected-node count."""
    by_id: dict[str, Blocker] = {}
    open_nodes = 0
    for report in reports:
        if report is None:
            continue
        open_nodes += int(report.open_node_count or 0)
        for blocker in report.blockers:
            existing = by_id.get(blocker.id)
            if existing is None:
                by_id[blocker.id] = blocker
                continue
            for nid in blocker.affected_nodes:
                if nid not in existing.affected_nodes:
                    existing.affected_nodes.append(nid)
            for ev in blocker.evidence:
                if ev.id not in {e.id for e in existing.evidence}:
                    existing.evidence.append(ev)
    blockers = sorted(by_id.values(), key=lambda b: (-len(b.affected_nodes), b.id))
    return GapReport(blockers=blockers, open_node_count=open_nodes)


def build_gap_report(analyses) -> GapReport:
    items = collect_gap_items(analyses)
    open_nodes = {a.branch_id for a in analyses if not a.closed}
    return GapReport(blockers=cluster(items), open_node_count=len(open_nodes))


def build_derivation_gap_report(host_derivation) -> GapReport:
    items = collect_derivation_gap_items(host_derivation)
    fields = getattr(host_derivation, "fields", None) or []
    open_fields = {
        f"KEYFIELD_{f.name}"
        for f in fields
        if any(getattr(g, "escalate", False) for g in getattr(f, "undecided_guards", []) or [])
    }
    return GapReport(blockers=cluster(items), open_node_count=len(open_fields))
