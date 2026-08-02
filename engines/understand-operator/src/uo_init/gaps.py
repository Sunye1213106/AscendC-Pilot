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

from uo_init.host_derivation import NON_ESCALATING
from uo_init.ids import hash12
from uo_init.kb_model import Blocker, Evidence

# Reasons ordered by how much a human/LLM can actually do about them. When one
# node fails for several reasons, the most actionable one names the blocker.
REASON_PRIORITY = [
    "UNWRITTEN_INITIAL_VALUE",
    "LOOP_SUMMARY_NEEDED",
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
    "UNWRITTEN_INITIAL_VALUE": (
        "读到该字段时这条路径上没有写点，静态分析只能假设一个初值。"
        "给出它真正的初值，或说明这条路径走不到（两者都要给 path:line 证据）"
    ),
    "LOOP_SUMMARY_NEEDED": (
        "该值由循环产生（掩码扫描、前缀和一类），逐次迭代无法符号化。"
        "读完整个循环体，把它总结成一个只用已声明输入变量的条件"
    ),
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
    #: The over-approximation variable an answer would remove, when the item
    #: is about one. Carried through to `affected_nodes` so the substitution
    #: has something to aim at: an initial-value variable has no guard record
    #: to hang a binding off, and without this there is nothing to replace.
    var_id: str = ""


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
        if item.var_id and item.var_id not in blocker.affected_nodes:
            blocker.affected_nodes.append(item.var_id)
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

    Scheduling, reachability and loop-element guards stay out of this list on
    purpose — see `host_derivation.NON_ESCALATING` for why each one is a
    question nobody should be asked. Everything else (unmapped / platform /
    unknown) is one question per guard id, tagged onto the key field it blocks.
    """
    items: list[GapItem] = []
    fields = getattr(host_derivation, "fields", None) or []
    for fld in fields:
        for guard in getattr(fld, "escalating", None) or []:
            norm = normalize_atom_text(getattr(guard, "text", "") or "")
            if not norm or norm in _NOISE_ATOMS:
                continue
            # Filter on the pre-sort, not on the reason text. The reason says
            # *how* normalization failed and is orthogonal: a loop element that
            # failed as UNMAPPED_SYMBOL carried an escalatable reason and slipped
            # through the old `SCHED_SOFT` check.
            if str(getattr(guard, "presort", "") or "") in NON_ESCALATING:
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
            # Ask in the source's words, not the IR's. A normalized guard is
            # the whole expression the field was folded into -- `let $1 =
            # (__reached_DoOpTiling && ...`, thousands of characters of
            # internal notation naming things no C++ reader has heard of. Cut
            # to fit a question it becomes an unfinished sentence. It also
            # clusters wrong: 33 guards over three files collapse onto three
            # questions, because what they share is the expression they ended
            # up inside rather than the code anyone has to read. The line the
            # guard came from is the question.
            text = (str(ev.get("snippet") or "").strip() or norm)[:200]
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


#: Which over-approximations are a question somebody can answer, and what to
#: ask about each. A scheduling position is not on this list and should not be:
#: which core ran a block is not a property of the input, so an answer would be
#: invention. Reachability placeholders are off it for the same reason — the
#: right fix there is a complete call graph, not a model's opinion.
FREE_VAR_ASKS = {
    "VAR_INIT_": "UNWRITTEN_INITIAL_VALUE",
    "VAR_LOOPELEM_": "LOOP_SUMMARY_NEEDED",
}


def _ask_for(var_id: str) -> str:
    for prefix, reason in FREE_VAR_ASKS.items():
        if var_id.startswith(prefix):
            return reason
    return ""


def _initial_value_item(fld, var_id: str, record: dict[str, Any]) -> GapItem:
    # The question is about the field, not about one read of it: two reads of
    # the same uninitialised member are one thing to find out.
    text = str(record.get("field") or var_id)
    guard = str(record.get("guard") or "")
    return GapItem(
        node_id=f"KEYFIELD_{fld.name}",
        text=text,
        reason="UNWRITTEN_INITIAL_VALUE",
        file=str(record.get("file") or ""),
        line=int(record.get("line") or 0),
        snippet=(f"{text} 在 {guard} 之外没有写点" if guard else text)[:200],
        function=str(record.get("function") or ""),
        var_id=var_id,
    )


def _loop_summary_item(fld, var_id: str, guard) -> GapItem:
    ev = getattr(guard, "evidence", None) or {}
    text = normalize_atom_text(getattr(guard, "text", "") or "") or var_id
    return GapItem(
        node_id=f"KEYFIELD_{fld.name}",
        text=text,
        reason="LOOP_SUMMARY_NEEDED",
        file=str(ev.get("file") or ""),
        line=int(ev.get("line") or 0),
        snippet=str(ev.get("snippet") or text)[:200],
        function=str(ev.get("function") or ""),
        var_id=var_id,
    )


def collect_free_var_gap_items(host_derivation) -> list[GapItem]:
    """Ask about the over-approximations still standing in the expressions.

    `collect_derivation_gap_items` asks about guards the pre-sort escalated,
    which is a different set and a smaller one: the variable standing in for a
    member's value before any write is recorded on `implicit_defaults` and was
    never a guard at all, and a loop-element cut is filtered out as
    non-escalating. Both are exactly what keeps a dimension from closing, so
    both are asked here.

    Backed by the field's own `free_vars`, so an item exists only where an
    over-approximation really survives in `value_expr` — asking about one that
    was already substituted away would spend a model's attention on nothing.
    """
    items: list[GapItem] = []
    for fld in getattr(host_derivation, "fields", None) or []:
        defaults = {
            str(d.get("variable")): d
            for d in getattr(fld, "implicit_defaults", None) or []
            if d.get("variable")
        }
        guards = {
            str(getattr(g, "var_id", "") or ""): g
            for g in getattr(fld, "undecided_guards", None) or []
        }
        for var_id in getattr(fld, "free_vars", None) or []:
            ask = _ask_for(str(var_id))
            if not ask:
                continue
            if ask == "UNWRITTEN_INITIAL_VALUE" and var_id in defaults:
                items.append(_initial_value_item(fld, var_id, defaults[var_id]))
            elif var_id in guards:
                items.append(_loop_summary_item(fld, var_id, guards[var_id]))
            # A free variable with no record behind it is reported by
            # `unrecorded_free_vars` and gated on there. Inventing a question
            # for it here would paper over a derivation bug with a model's
            # guess, which is the one thing this channel must not do.
    return items


#: Free variables stand for what the analysis could not read. Offering one
#: back as an answer would define one over-approximation in terms of another.
_PLACEHOLDERS = (
    "VAR_INIT_",
    "VAR_UNDECIDED_",
    "VAR_LOOPELEM_",
    "VAR_SCHED_",
    "VAR_REACHED_",
    "__reached_",
)


def readable_vars(host_derivation, node_ids: Iterable[str]) -> list[str]:
    """Variables the dimensions a blocker holds up already read.

    Without this the batch says which *ops* a binding may use but not which
    variables exist, so a model has to guess a name — and a guessed name is
    rejected as invented however well it read the code. It is also the set the
    first mechanical gate checks a condition against, so naming it here is not
    a hint but the actual rule.

    Scoped to the dimensions this blocker blocks rather than to the whole
    model: a condition on a variable no affected dimension reads is not an
    answer to this question, whatever else it is.

    Read off `variables`, which the derivation already collected. Walking
    `value_expr` gives the same answer and cannot be used: it is the expanded
    tree, and for the widest dimension here that is hundreds of thousands of
    nodes to cross once per blocker that touches it.
    """
    wanted = {
        str(n)[len("KEYFIELD_") :]
        for n in node_ids
        if str(n).startswith("KEYFIELD_")
    }
    found: set[str] = set()
    for fld in getattr(host_derivation, "fields", None) or []:
        if wanted and fld.name not in wanted:
            continue
        found.update(str(v) for v in getattr(fld, "variables", None) or [])
    return sorted(v for v in found if not v.startswith(_PLACEHOLDERS))


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
    items += collect_free_var_gap_items(host_derivation)
    blockers = cluster(items)
    for blocker in blockers:
        blocker.readable_vars = readable_vars(host_derivation, blocker.affected_nodes)
    fields = getattr(host_derivation, "fields", None) or []
    open_fields = {
        f"KEYFIELD_{f.name}"
        for f in fields
        if any(getattr(g, "escalate", False) for g in getattr(f, "undecided_guards", []) or [])
        or any(_ask_for(str(v)) for v in getattr(f, "free_vars", None) or [])
    }
    return GapReport(blockers=blockers, open_node_count=len(open_fields))
