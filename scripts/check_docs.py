"""Check documentation boundaries and generated reference drift."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPRECATED_PATHS = (
    "docs/design/",
    "docs/fag/",
    "docs/case-studies/",
    "docs/architecture/agent-system.md",
    "docs/architecture/harness-and-permissions.md",
    "docs/architecture/skills-prompts-policies.md",
    "docs/architecture/state-and-artifacts.md",
    "docs/development/extending-agent.md",
    "docs/development/extending-engine.md",
    "docs/development/extending-skill.md",
    "docs/development/extending-workflow.md",
    "docs/development/testing-and-evals.md",
    "docs/fag/data/",
    "agents/README.md",
    "pilot/README.md",
    "skills/_shared/README.md",
)
ENGINE_NAMES = ("common", "understand-operator", "testcase-generation", "code-engineering")
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def is_runtime_readme(path: Path) -> bool:
    r = rel(path)
    if r == "README.md" or r.startswith("docs/"):
        return True
    if re.fullmatch(r"skills/[^/]+/examples/.+/README\.md", r):
        return True
    if re.fullmatch(r"evals/skills/[^/]+/live/README\.md", r):
        return True
    return False


def check_readme_locations(errors: list[str]) -> None:
    for path in ROOT.rglob("README.md"):
        r = rel(path)
        if (
            r.startswith(".git/")
            or r.startswith("_pytest_tmp")
            or "/.pytest_cache/" in f"/{r}"
            or r.startswith("generated/")
        ):
            continue
        if not is_runtime_readme(path):
            errors.append(f"non-doc README: {r}")


def check_deprecated_paths(errors: list[str]) -> None:
    docs = [ROOT / "README.md", *ROOT.joinpath("docs").rglob("*.md")]
    for path in docs:
        text = path.read_text(encoding="utf-8")
        for needle in DEPRECATED_PATHS:
            if needle in text:
                errors.append(f"{rel(path)} references deprecated path {needle}")


def check_links(errors: list[str]) -> None:
    docs = [ROOT / "README.md", *ROOT.joinpath("docs").rglob("*.md")]
    for path in docs:
        text = path.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            target = match.group(1).strip()
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            clean = target.split("#", 1)[0]
            if not clean:
                continue
            candidate = (path.parent / clean).resolve()
            try:
                candidate.relative_to(ROOT)
            except ValueError:
                errors.append(f"{rel(path)} link escapes repo: {target}")
                continue
            if not candidate.exists():
                errors.append(f"{rel(path)} missing link target: {target}")


def check_agent_matrix(errors: list[str]) -> None:
    matrix = ROOT / "docs" / "reference" / "agent-matrix.generated.md"
    if not matrix.is_file():
        errors.append("missing docs/reference/agent-matrix.generated.md")
        return
    text = matrix.read_text(encoding="utf-8")
    for path in sorted((ROOT / "agents").glob("*.yaml")):
        agent_id = path.stem
        if f"`{agent_id}`" not in text:
            errors.append(f"agent matrix missing {agent_id}")


def check_engines_doc(errors: list[str]) -> None:
    path = ROOT / "docs" / "modules" / "acp-harness.md"
    if not path.is_file():
        errors.append("missing docs/modules/acp-harness.md")
        return
    text = path.read_text(encoding="utf-8")
    for name in ENGINE_NAMES:
        if f"`{name}`" not in text:
            errors.append(f"acp-harness.md missing engine {name}")


def check_generated_references_fresh(errors: list[str]) -> None:
    result = subprocess.run(
        [sys.executable, "scripts/generate_reference_docs.py", "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()
        errors.append(f"generated references are stale: {detail}")


def main() -> int:
    errors: list[str] = []
    check_readme_locations(errors)
    check_deprecated_paths(errors)
    check_links(errors)
    check_agent_matrix(errors)
    check_engines_doc(errors)
    check_generated_references_fresh(errors)
    if errors:
        for item in errors:
            print(f"docs-check: {item}")
        return 1
    print("docs-check: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
