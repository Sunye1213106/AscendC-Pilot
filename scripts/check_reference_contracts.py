#!/usr/bin/env python3
"""Reference hygiene: one owner, one selector, no hops, Chinese titles."""

from __future__ import annotations

import hashlib
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "skills"
sys.path.insert(0, str(REPO / "pilot"))

from ascendc_pilot.actions.method_bundle import (  # noqa: E402
    materialize_method_bundle,
    parse_declared_refs,
)
from ascendc_pilot.workflows import WORKFLOWS  # noqa: E402

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
H1_RE = re.compile(r"(?m)^#\s+(.+)$")
REF_BACKTICK_RE = re.compile(r"`((?:skills/[a-z0-9-]+/)?references/[^`]+\.md)`")
EN_LOAD_RE = re.compile(
    r"(?im)^(?:#+\s*)?(?:\*\*)?(When to load|When to use|Gotchas)(?:\*\*)?\s*$"
)
FENCE_RE = re.compile(r"```.*?```", re.S)

# Axis playbooks inside bind-init must not mix the other axis's field vocabulary.
# Router SKILL.md names both axes on purpose.
SIBLING_BAN_FILES = {
    "bind-init/references/harness.md": (
        r"api_arg",
        r"script_meta",
        r"domains\.operator",
        r"column-binding",
    ),
    "bind-init/references/columns.md": (
        r"modes\.precision",
        r"modes\.perf",
        r"--golden-only",
        r"generate_inputs",
        r"worklog\.md",
        r"closure-safety",
        r"performance-testing",
    ),
}

def _skill_dirs() -> list[Path]:
    out: list[Path] = []
    for path in sorted(SKILLS.iterdir()):
        if path.is_dir() and (path / "SKILL.md").is_file():
            out.append(path)
    return out


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check() -> list[str]:
    errors: list[str] = []
    bodies: dict[str, list[str]] = defaultdict(list)
    reachable: set[str] = set()

    for skill_dir in _skill_dirs():
        sid = skill_dir.name
        skill_md = skill_dir / "SKILL.md"
        skill_text = skill_md.read_text(encoding="utf-8")
        requested, unauth = parse_declared_refs(skill_text, current_skill_id=sid)
        for path in unauth:
            errors.append(f"CROSS_SKILL_REF {sid} -> {path}")
        declared = {rel.replace("\\", "/") for _owner, rel in requested}
        for owner, rel in requested:
            qualified = f"skills/{owner}/references/{rel}"
            reachable.add(qualified)
            target = SKILLS / owner / "references" / rel
            if not target.is_file():
                errors.append(f"MISSING_POINTER {sid}: {qualified}")

        refs_dir = skill_dir / "references"
        if refs_dir.is_dir():
            for path in sorted(refs_dir.rglob("*.md")):
                rel = path.relative_to(refs_dir).as_posix()
                text = path.read_text(encoding="utf-8")
                bodies[_sha(text)].append(f"{sid}/references/{rel}")
                qualified = f"skills/{sid}/references/{rel}"
                if rel not in declared:
                    errors.append(f"DEAD_REFERENCE {qualified}")
                hops = REF_BACKTICK_RE.findall(text)
                for hop in hops:
                    errors.append(f"REFERENCE_HOP {qualified} -> {hop}")
                title = ""
                hit = H1_RE.search(text)
                if hit:
                    title = hit.group(1).strip()
                if title and not CJK_RE.search(title):
                    errors.append(f"TITLE_NOT_ZH {qualified}: {title}")
                if EN_LOAD_RE.search(text):
                    errors.append(f"EN_LOAD_HEADING {qualified}")
                stripped = FENCE_RE.sub("", text)
                cjk = len(CJK_RE.findall(stripped))
                latin = len(re.findall(r"[A-Za-z]", stripped))
                if cjk < 12 and latin > 80:
                    errors.append(f"BODY_NOT_ZH {qualified}: cjk={cjk} latin={latin}")

        for rel, pats in SIBLING_BAN_FILES.items():
            owner, _, name = rel.partition("/")
            if not name.startswith("references/"):
                continue
            if sid != owner:
                continue
            path = skill_dir / name
            if not path.is_file():
                errors.append(f"SIBLING_BAN_MISSING {rel}")
                continue
            blob = path.read_text(encoding="utf-8")
            for pat in pats:
                if re.search(pat, blob):
                    errors.append(f"SIBLING_LEAK {rel}: /{pat}/")

        h1 = H1_RE.search(skill_text)
        if h1 and not CJK_RE.search(h1.group(1)):
            errors.append(f"TITLE_NOT_ZH skills/{sid}/SKILL.md: {h1.group(1).strip()}")

    for digest, locs in bodies.items():
        if len(locs) > 1:
            errors.append(f"DUPLICATE_REFERENCE_BODY {digest[:12]}: {', '.join(locs)}")

    llm_modes = {"subagent", "primary_interactive", "primary_review"}
    for wid, meta in WORKFLOWS.items():
        if not isinstance(meta, dict) or meta.get("reserved"):
            continue
        for action in meta.get("actions") or []:
            mode = str(action.get("execution_mode") or "")
            if mode not in llm_modes:
                continue
            sid = str(action.get("skill_id") or "").rsplit("/", 1)[-1]
            if not sid:
                continue
            skill_dir = SKILLS / sid
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.is_file():
                errors.append(f"LLM_ACTION_MISSING_SKILL {wid}/{action.get('id')}: {sid}")
                continue
            axes = list(action.get("fanout_axes") or [])
            copy_declared = not (
                bool(axes) and all(str(a.get("method_ref") or "").strip() for a in axes)
            )
            with tempfile.TemporaryDirectory() as tmp:
                mat = materialize_method_bundle(
                    Path(tmp),
                    skill_ids=[sid],
                    existing_method=skill_md.read_text(encoding="utf-8"),
                    project_root=REPO,
                    current_skill_id=sid,
                    copy_declared_refs=copy_declared,
                    explicit_refs=list(action.get("refs") or []),
                )
            if not mat.get("ok"):
                errors.append(
                    f"MATERIALIZE_FAIL {wid}/{action.get('id')}: {mat.get('reason_code')} "
                    f"missing={mat.get('missing')} unauthorized={mat.get('unauthorized')} "
                    f"ambiguous={mat.get('ambiguous')}"
                )
                continue
            requested = list(mat.get("requested") or [])
            copied = list(mat.get("copied") or [])
            if len(copied) != len(requested):
                errors.append(
                    f"COPIED_NE_REQUESTED {wid}/{action.get('id')}: {copied} vs {requested}"
                )
            if sid == "bind-init":
                columns = skill_dir / "references" / "columns.md"
                blob = columns.read_text(encoding="utf-8") if columns.is_file() else ""
                if "performance-testing" in blob:
                    errors.append("GOLDEN_POLLUTE bind-init columns playbook contains performance-testing")

    knowledge_root = REPO / "knowledge"
    for rel in (
        "knowledge/ascendc/precision.md",
        "knowledge/ascendc/performance.md",
        "knowledge/ascendc/cross-layer-contracts.md",
        "knowledge/ascendc/synchronization.md",
        "skills/test-plan/references/evidence.md",
        "skills/solve/references/precision-construction.md",
        "skills/solve/references/performance-construction.md",
        "skills/source-proof/references/review.md",
        "skills/source-proof/references/referee-replay.md",
    ):
        if not (REPO / rel).is_file():
            errors.append(f"AUTHORITY_FILE_MISSING {rel}")
    for wid, meta in WORKFLOWS.items():
        if not isinstance(meta, dict) or meta.get("reserved"):
            continue
        for action in meta.get("actions") or []:
            aid = str(action.get("id") or "")
            sid = str(action.get("skill_id") or "").rsplit("/", 1)[-1]
            declared = list(action.get("knowledge_refs") or [])
            method_refs = [(sid, r) for r in (action.get("refs") or [])]
            for axis in action.get("fanout_axes") or []:
                declared.extend(axis.get("knowledge_refs") or [])
                axis_skill = str(axis.get("skill") or axis.get("capability_id") or sid)
                method_refs.extend((axis_skill, r) for r in (axis.get("refs") or []))
            for raw in declared:
                rel = str(raw or "").replace("\\", "/").lstrip("/")
                if rel.startswith("knowledge/"):
                    rel = rel[len("knowledge/") :]
                if not rel or ".." in rel.split("/"):
                    errors.append(f"KNOWLEDGE_REF_INVALID {wid}/{aid}: {raw}")
                    continue
                if not (knowledge_root / rel).is_file():
                    errors.append(f"KNOWLEDGE_REF_MISSING {wid}/{aid}: {rel}")
            for owner, raw in method_refs:
                rel = str(raw or "").replace("\\", "/").lstrip("/")
                if rel.startswith("references/"):
                    rel = rel[len("references/") :]
                if not owner or not rel or ".." in rel.split("/"):
                    errors.append(f"REF_INVALID {wid}/{aid}: {owner}/{raw}")
                    continue
                if not (SKILLS / owner / "references" / rel).is_file():
                    errors.append(f"REF_MISSING {wid}/{aid}: skills/{owner}/references/{rel}")

    return errors


def main() -> int:
    errors = check()
    for err in errors:
        print(err)
    if errors:
        print(f"FAIL {len(errors)} reference-contract error(s)")
        return 1
    print("OK reference contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
