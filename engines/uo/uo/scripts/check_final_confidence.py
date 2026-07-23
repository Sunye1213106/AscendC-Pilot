"""Final confidence gate for /uo-init.

Closed KEY (true/false) must have confidence=high.
Unsolved / non-high must be LLM-resolved; if still open, require
summary/confidence_report.md with Chinese reasons covering every leftover.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import read_yaml, write_yaml

REPORT_REL = "summary/confidence_report.md"
SECTION_RE = re.compile(r"^###\s+(KEY_\S+|KVAR_\S+)\s*$", re.MULTILINE)


def check_final_confidence(
    uo_root: Path,
    *,
    write_skeleton: bool = False,
    write_report: bool = True,
) -> dict[str, Any]:
    uo_root = Path(uo_root)
    id_doc = read_yaml(uo_root / "ir" / "input_derivable.yaml")
    keys = (id_doc.get("keys") or {}) if isinstance(id_doc, dict) else {}
    patch_reasons = _load_patch_reasons(uo_root)

    closed_ok: list[str] = []
    closed_bad: list[dict[str, Any]] = []  # closed but confidence != high
    need_llm: list[dict[str, Any]] = []  # unsolved / low

    for kid, entry in keys.items():
        if not isinstance(entry, dict):
            continue
        idv = entry.get("input_derivable")
        conf = str(entry.get("confidence") or "").lower().strip()
        reason = str(
            entry.get("reason")
            or patch_reasons.get(str(kid), {}).get("reason")
            or ""
        )
        row = {
            "id": str(kid),
            "input_derivable": idv,
            "confidence": conf or "(missing)",
            "gap_kind": entry.get("gap_kind") or patch_reasons.get(str(kid), {}).get("gap_kind"),
            "host_parent": entry.get("host_parent"),
            "reason": reason,
            "gap_ref": entry.get("gap_ref"),
            "attempted": entry.get("attempted")
            or patch_reasons.get(str(kid), {}).get("attempted")
            or "",
            "suggestion": entry.get("suggestion")
            or patch_reasons.get(str(kid), {}).get("suggestion")
            or "",
        }
        if idv is True or idv is False or entry.get("not_input_derivable") is True:
            if conf == "high":
                closed_ok.append(str(kid))
            else:
                closed_bad.append(row)
                need_llm.append(row)
        else:
            # unsolved or unknown
            need_llm.append(row)

    report_path = uo_root / REPORT_REL
    # Deterministic assembly from structured KB/patch reasons — never TODO skeleton.
    if write_report and (write_skeleton or need_llm or not report_path.is_file()):
        _write_deterministic_report(uo_root, need_llm, closed_ok=closed_ok)
    report_text = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
    covered = set(SECTION_RE.findall(report_text)) if report_text else set()
    missing_report = [r["id"] for r in need_llm if r["id"] not in covered]

    # closed_bad must never ship — force LLM / fix, not just report
    hard_fail = bool(closed_bad)

    # Each leftover section needs a filled 原因 line from structured data (no TODO)
    incomplete_reasons = _sections_missing_reason(report_text, [r["id"] for r in need_llm])

    status = "pass"
    if hard_fail or incomplete_reasons or missing_report:
        status = "fail"
    elif need_llm:
        status = "reported"  # leftovers documented with Chinese reasons
    else:
        status = "pass"

    # Harness hard rules (ses_076d): duplicated boilerplate / closed_high=0 → fail by default
    report_quality_fail = False
    closed_high_fail = False
    if status == "reported" and need_llm:
        fingerprints = []
        for row in need_llm:
            # Prefer report section reason when present
            fingerprints.append(_reason_fingerprint_from_report(report_text, row["id"]))
        from collections import Counter

        counts = Counter(fp for fp in fingerprints if fp)
        if any(n >= 5 for n in counts.values()):
            report_quality_fail = True
            status = "fail"
        if len(closed_ok) == 0 and keys:
            # Default fail unless human_accept_reported.yaml present
            human = uo_root / "checks" / "human_accept_reported.yaml"
            human_ok = False
            if human.is_file():
                hdoc = read_yaml(human)
                human_ok = isinstance(hdoc, dict) and bool(hdoc.get("accepted"))
            if not human_ok:
                closed_high_fail = True
                status = "fail"

    # Triage required when gaps/need_llm but no key_triage
    triage_fail = False
    if need_llm:
        triage_path = uo_root / "ir" / "key_triage.yaml"
        triage = read_yaml(triage_path) if triage_path.is_file() else {}
        triage_keys = []
        if isinstance(triage, dict):
            raw = triage.get("keys") or triage.get("items") or []
            if isinstance(raw, list):
                triage_keys = raw
            elif isinstance(raw, dict):
                triage_keys = list(raw)
        if not triage_keys:
            triage_fail = True
            status = "fail"

    payload = {
        "version": 1,
        "status": status,
        "closed_high_count": len(closed_ok),
        "need_llm_count": len(need_llm),
        "closed_without_high": closed_bad,
        "need_llm": need_llm,
        "report_path": REPORT_REL if need_llm or report_path.is_file() else "",
        "missing_report_ids": missing_report,
        "incomplete_reason_ids": incomplete_reasons,
        "harness": {
            "report_quality_fail": report_quality_fail,
            "closed_high_fail": closed_high_fail,
            "triage_fail": triage_fail,
            "deterministic_report": True,
        },
        "message": _status_message(
            status,
            hard_fail,
            need_llm,
            missing_report,
            incomplete_reasons,
            report_quality_fail=report_quality_fail,
            closed_high_fail=closed_high_fail,
            triage_fail=triage_fail,
        ),
    }
    write_yaml(uo_root / "checks" / "confidence_gate.yaml", payload)
    return payload


def _load_patch_reasons(uo_root: Path) -> dict[str, dict[str, Any]]:
    """Structured reasons from producer patch — sole source for report body text."""
    out: dict[str, dict[str, Any]] = {}
    for rel in ("ir/input_derivable_patch.yaml", "ir/resolution_patch.yaml"):
        doc = read_yaml(uo_root / rel)
        if not isinstance(doc, dict):
            continue
        items = doc.get("items") or doc.get("keys") or doc.get("accepted") or []
        if isinstance(doc.get("keys"), dict):
            for kid, entry in doc["keys"].items():
                if isinstance(entry, dict):
                    out[str(kid)] = {
                        "reason": str(entry.get("reason") or entry.get("reason_zh") or ""),
                        "attempted": str(entry.get("attempted") or entry.get("tried") or ""),
                        "suggestion": str(entry.get("suggestion") or entry.get("next") or ""),
                        "gap_kind": entry.get("gap_kind"),
                    }
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                kid = str(it.get("id") or it.get("key") or "")
                if not kid:
                    continue
                out[kid] = {
                    "reason": str(it.get("reason") or it.get("reason_zh") or out.get(kid, {}).get("reason") or ""),
                    "attempted": str(
                        it.get("attempted") or it.get("tried") or out.get(kid, {}).get("attempted") or ""
                    ),
                    "suggestion": str(
                        it.get("suggestion") or it.get("next") or out.get(kid, {}).get("suggestion") or ""
                    ),
                    "gap_kind": it.get("gap_kind") or out.get(kid, {}).get("gap_kind"),
                }
    return out

def _status_message(
    status: str,
    hard_fail: bool,
    need_llm: list[dict[str, Any]],
    missing_report: list[str],
    incomplete_reasons: list[str],
    *,
    report_quality_fail: bool = False,
    closed_high_fail: bool = False,
    triage_fail: bool = False,
) -> str:
    if triage_fail:
        return "need_llm>0 但缺少 ir/key_triage.yaml：禁止跳过 uo-key-resolve triage"
    if report_quality_fail:
        return "confidence_report 多 KEY 共用同一套借口（如 bit-pack）：禁止 reported 空过"
    if closed_high_fail:
        return "closed_high_count=0 且 KEY 非空：默认 fail（需 checks/human_accept_reported.yaml 才可 reported 放行）"
    if hard_fail:
        return "存在已闭合但 confidence≠high 的 KEY：禁止交付，须 LLM 重解析或降回 unsolved"
    if missing_report or incomplete_reasons:
        return (
            f"未达 high 的项须先 LLM 解析；解析不出须在 {REPORT_REL} 写满中文原因。"
            f" missing={missing_report} incomplete={incomplete_reasons}"
        )
    if status == "reported":
        return (
            f"仍有 {len(need_llm)} 项未 high，已在 {REPORT_REL} 说明原因；"
            "允许收工但须告知用户。integrity 对已报告 open gaps 降为 warning（非 error），"
            "TG 摄入时应可见 confidence_gate=reported"
        )
    return "全部闭合项 confidence=high，无未闭合项"


def _reason_fingerprint_from_report(report_text: str, kid: str) -> str:
    m = re.search(rf"^###\s+{re.escape(kid)}\s*$", report_text, re.MULTILINE)
    if not m:
        return ""
    start = m.end()
    nxt = re.search(r"^###\s+\S+", report_text[start:], re.MULTILINE)
    body = report_text[start : start + nxt.start()] if nxt else report_text[start:]
    rm = re.search(r"^\s*-\s*原因\s*[：:]\s*(.+)$", body, re.MULTILINE)
    if not rm:
        return ""
    reason = rm.group(1).strip()
    t = re.sub(r"\s+", " ", reason.lower())
    t = re.sub(r"key_[a-z0-9_]+", "KEY", t, flags=re.I)
    return t[:240]


def _sections_missing_reason(report_text: str, ids: list[str]) -> list[str]:
    if not ids:
        return []
    bad: list[str] = []
    for kid in ids:
        # slice from ### kid to next ### or EOF
        m = re.search(rf"^###\s+{re.escape(kid)}\s*$", report_text, re.MULTILINE)
        if not m:
            bad.append(kid)
            continue
        start = m.end()
        nxt = re.search(r"^###\s+\S+", report_text[start:], re.MULTILINE)
        body = report_text[start : start + nxt.start()] if nxt else report_text[start:]
        # require 原因: with non-placeholder content
        rm = re.search(r"^\s*-\s*原因\s*[：:]\s*(.+)$", body, re.MULTILINE)
        if not rm:
            bad.append(kid)
            continue
        reason = rm.group(1).strip()
        if not reason or reason.startswith("TODO") or reason.startswith("（待"):
            bad.append(kid)
    return bad


def _write_deterministic_report(
    uo_root: Path,
    need_llm: list[dict[str, Any]],
    *,
    closed_ok: list[str] | None = None,
) -> None:
    """Assemble confidence_report.md solely from structured patch/KB reasons.

    Producer must not edit this file; Referee only reviews. Missing structured
    reason yields an explicit 原因 stating evidence is absent (not TODO).
    """
    path = uo_root / REPORT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# 置信度报告（确定性引擎汇总）",
        "",
        f"- 生成时间：{now}",
        f"- 算子根：`{uo_root.as_posix()}`",
        "- 来源：`ir/input_derivable.yaml` + `ir/input_derivable_patch.yaml` 结构化 reason",
        "- 规则：报告正文由确定性引擎生成；Producer 只写 patch；Referee（uo-confidence-review）只审",
        f"- closed_high_count：{len(closed_ok or [])}",
        "",
        "## 未达 high 的项",
        "",
    ]
    if not need_llm:
        lines.append("（无）全部 KEY 已 high 闭合。")
        lines.append("")
    for row in need_llm:
        kid = row["id"]
        reason = str(row.get("reason") or "").strip()
        attempted = str(row.get("attempted") or "").strip()
        suggestion = str(row.get("suggestion") or "").strip()
        if not reason:
            reason = "结构化 patch/KB 未提供 reason；须由 uo-key-resolve 在 patch 中补中文原因后再汇总"
        if not attempted:
            attempted = "见 patch 记录；未单独声明 attempted 字段"
        if not suggestion:
            suggestion = "补边 / 标 not_input_derivable / 人工确认（由 patch suggestion 驱动）"
        lines.extend(
            [
                f"### {kid}",
                f"- 状态：`{row.get('input_derivable')}`",
                f"- confidence：`{row.get('confidence')}`",
                f"- gap_kind：`{row.get('gap_kind')}`",
                f"- host_parent：`{row.get('host_parent')}`",
                f"- 已尝试：{attempted}",
                f"- 原因：{reason}",
                f"- 建议：{suggestion}",
                "",
            ]
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


# Public helper: must not write TODO placeholders.
def _write_skeleton_report(uo_root: Path, need_llm: list[dict[str, Any]], *, existing: str = "") -> None:
    del existing
    _write_deterministic_report(uo_root, need_llm)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="uo-init final confidence gate (deterministic report)")
    parser.add_argument("repo", type=Path)
    parser.add_argument("--op-name", required=True)
    parser.add_argument(
        "--no-write-skeleton",
        action="store_true",
        help="deprecated alias: skip writing report (prefer --no-write-report)",
    )
    parser.add_argument("--no-write-report", action="store_true", help="do not rewrite confidence_report.md")
    args = parser.parse_args(argv)
    op = safe_op_name(args.op_name, args.repo)
    uo_root = existing_operator_root(args.repo, op)
    write_report = not (args.no_write_report or args.no_write_skeleton)
    payload = check_final_confidence(uo_root, write_report=write_report, write_skeleton=False)
    print(f"confidence_gate status={payload['status']} {payload['message']}")
    print(f"→ {uo_root / 'checks' / 'confidence_gate.yaml'}")
    if payload.get("report_path"):
        print(f"→ {uo_root / payload['report_path']}")
    return 0 if payload["status"] in {"pass", "reported"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
