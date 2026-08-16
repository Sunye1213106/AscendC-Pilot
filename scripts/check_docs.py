"""Check documentation boundaries and generated reference drift."""

from __future__ import annotations

import os
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
    "docs/modules/acp-harness.md",
    "docs/modules/engines.md",
    "docs/modules/host-adapters.md",
    "docs/modules/pilot-runtime.md",
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
UO_SLASH_COMMANDS = ("/uo-init", "/uo-update", "/uo-query", "/uo-investigate")
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
# Docs (excluding history) must not claim a silent arch35 default.
ARCH35_DEFAULT_RE = re.compile(r"默认\s*architecture\s*为\s*`?arch35`?", re.I)
# Canonical product naming (hand-written docs).
OPERATOR_UO_LEGACY_RE = re.compile(r"operator\.<arch>\.uo")
UO_CANONICAL_NAME = "<op_name>.<arch>.uo"
# Quick Start must not imply UO is bound to a named engine identity.
UO_ENGINE_BIND_RE = re.compile(
    r"绑定到\s*`?deterministic-uo-engine`?|deterministic-uo-engine",
    re.I,
)
# Architecture is always required for UO/TG start — not "only when multiple".
MULTI_ARCH_ONLY_RE = re.compile(
    r"多架构时(?:需|才)?选择|存在多个架构时[，,]?\s*AscendC-Pilot\s*会要求选择",
)
# Backtick paths that should resolve in-repo (or under UO package for frontend/passes).
INLINE_REPO_PATH_RE = re.compile(
    r"`((?:engines|pilot|scripts|agents|docs|adapters|opencode-plugin)/[^`\s]+)`"
)
INLINE_UO_REL_PATH_RE = re.compile(
    r"`((?:frontend|passes|ir|update|query)/[^`\s]+\.py)`"
)
UO_PACKAGE_ROOT = ROOT / "engines" / "understand-operator" / "src" / "uo_init"


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


# Vendor / VCS / plugin trees are not product docs.
SKIP_DIR_NAMES = frozenset({".git", ".opencode", ".cursor", "node_modules"})


def _skip_tree(path: Path) -> bool:
    return any(part in SKIP_DIR_NAMES for part in path.parts)


def _iter_readme_files() -> list[Path]:
    """README.md under the repo, pruning .git / .opencode / node_modules."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        if "README.md" in filenames:
            found.append(Path(dirpath) / "README.md")
    return found


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
    for path in _iter_readme_files():
        if _skip_tree(path):
            continue
        r = rel(path)
        if (
            r.startswith(".git/")
            or r.startswith(".opencode/")
            or r.startswith(".cursor/")
            or r.startswith("_pytest_tmp")
            or "/.pytest_cache/" in f"/{r}"
            or "/node_modules/" in f"/{r}"
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
    path = ROOT / "docs" / "architecture" / "agent-runtime.md"
    if not path.is_file():
        errors.append("missing docs/architecture/agent-runtime.md")
        return
    text = path.read_text(encoding="utf-8")
    for name in ENGINE_NAMES:
        if f"`{name}`" not in text:
            errors.append(f"agent-runtime.md missing engine {name}")


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


def _iter_live_docs() -> list[Path]:
    """Hand-written docs excluding history (historical notes may mention arch35)."""
    paths = [ROOT / "README.md"]
    for path in ROOT.joinpath("docs").rglob("*.md"):
        if "docs/history/" in rel(path) or "\\docs\\history\\" in str(path):
            continue
        if "/history/" in f"/{rel(path)}":
            continue
        paths.append(path)
    return paths


def check_semantic_drift(errors: list[str]) -> None:
    """Light checks for known doc/implementation drifts (no NLP)."""
    for path in _iter_live_docs():
        text = path.read_text(encoding="utf-8")
        if ARCH35_DEFAULT_RE.search(text):
            errors.append(f"{rel(path)} claims silent arch35 architecture default")
        if OPERATOR_UO_LEGACY_RE.search(text):
            errors.append(f"{rel(path)} uses legacy `operator.<arch>.uo` naming")
        if MULTI_ARCH_ONLY_RE.search(text):
            errors.append(
                f"{rel(path)} implies architecture is only required when multiple "
                "arch* dirs exist; UO/TG always require explicit architecture"
            )

    uo = ROOT / "docs" / "modules" / "uo.md"
    if not uo.is_file():
        errors.append("missing docs/modules/uo.md")
    else:
        text = uo.read_text(encoding="utf-8")
        for cmd in UO_SLASH_COMMANDS:
            if cmd not in text:
                errors.append(f"uo.md missing slash command {cmd}")
        if UO_CANONICAL_NAME not in text:
            errors.append(f"uo.md missing canonical product name `{UO_CANONICAL_NAME}`")

    quickstart = ROOT / "docs" / "getting-started" / "quickstart.md"
    if quickstart.is_file():
        qs = quickstart.read_text(encoding="utf-8")
        if UO_ENGINE_BIND_RE.search(qs):
            errors.append(
                "quickstart.md must not bind UO phases to `deterministic-uo-engine` "
                "(UO uses agent_id=None + deterministic execution)"
            )
        if "必须明确 architecture" not in qs and "必须同时有" not in qs:
            # Prefer the explicit-must wording; allow POLICY-style phrasing too.
            if "ARCHITECTURE_REQUIRED" not in qs and "从发现的架构中选择" not in qs:
                errors.append(
                    "quickstart.md must state that architecture is always required "
                    "(discovered options + explicit select; no silent default)"
                )


def _is_concrete_repo_path(cited: str) -> bool:
    """Skip globs / placeholders that are not literal filesystem paths."""
    if any(ch in cited for ch in "*?[]{}"):
        return False
    if "<" in cited or ">" in cited:
        return False
    return True


def check_inline_implementation_paths(errors: list[str]) -> None:
    """Fail when docs cite missing repo / UO-package implementation paths."""
    for path in _iter_live_docs():
        text = path.read_text(encoding="utf-8")
        for match in INLINE_REPO_PATH_RE.finditer(text):
            cited = match.group(1).rstrip("/")
            if not _is_concrete_repo_path(cited):
                continue
            candidate = ROOT / cited
            if not candidate.exists():
                errors.append(f"{rel(path)} missing implementation path: `{cited}`")
        # UO module may cite package-relative frontend/passes/*.py
        if rel(path) == "docs/modules/uo.md":
            for match in INLINE_UO_REL_PATH_RE.finditer(text):
                cited = match.group(1)
                if not _is_concrete_repo_path(cited):
                    continue
                candidate = UO_PACKAGE_ROOT / cited
                if not candidate.exists():
                    errors.append(
                        f"{rel(path)} missing UO package path: `{cited}` "
                        f"(expected under {UO_PACKAGE_ROOT.relative_to(ROOT).as_posix()})"
                    )


def main() -> int:
    errors: list[str] = []
    check_readme_locations(errors)
    check_deprecated_paths(errors)
    check_links(errors)
    check_agent_matrix(errors)
    check_engines_doc(errors)
    check_semantic_drift(errors)
    check_inline_implementation_paths(errors)
    check_generated_references_fresh(errors)
    if errors:
        for item in errors:
            print(f"docs-check: {item}")
        return 1
    print("docs-check: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
