"""Context profile registry — declarative slice recipes per Action.

Profiles are opt-in. When no profile matches ``context_profile_id``, the
legacy lightweight ``build_context_pack`` path is used unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class QuerySlice:
    """One UoQuery call family to include in the compiled slice."""

    method: str
    # seed_from: where seed entity ids come from (relative to project uo/tg roots).
    # Supported: unresolved_blockers | lemma_leads | open_keys | impact_files | none
    seed_from: str = "none"
    limit: int = 16
    # Extra kwargs passed to the query method when applicable.
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextProfile:
    id: str
    description: str = ""
    # Domain reference files relative to repo root (skills/<skill>/...).
    references: tuple[str, ...] = ()
    query_slices: tuple[QuerySlice, ...] = ()
    include_prior_failure: bool = True
    # Hard cap on estimated tokens for the graph_slice section.
    token_budget: int = 4000
    # Always-excluded material (documentation for agents; compiler enforces).
    excluded: tuple[str, ...] = (
        "full_kb",
        "full_source_tree",
        "full_memory",
        "unrelated_ir",
    )


# High-value Action profiles (P1c). Ids match specs.py default
# context_profile_id = f"{workflow_id}-{action_id with dashes}".
PROFILES: dict[str, ContextProfile] = {
    "uo-init-resolve": ContextProfile(
        id="uo-init-resolve",
        description="Bounded semantic-gap resolve: blockers + nearby graph + gotchas.",
        references=(
            "skills/operator-analysis/references/codemap-authority.md",
            "skills/operator-analysis/references/codemap-completeness.md",
            "skills/operator-analysis/references/codemap-build-gotchas.md",
            "skills/_shared/evidence-quality.md",
            "skills/_shared/cpp-semantics.md",
        ),
        query_slices=(
            QuerySlice(method="search", seed_from="unresolved_blockers", limit=12),
            QuerySlice(method="neighbors", seed_from="unresolved_blockers", limit=8),
            QuerySlice(method="constraints_for", seed_from="unresolved_blockers", limit=8),
        ),
        token_budget=4500,
    ),
    "tg-solve-lemma-mine": ContextProfile(
        id="tg-solve-lemma-mine",
        description="Lemma mining: open keys / leads + branch/template locality + proof gotchas.",
        references=(
            "skills/source-proof/references/proof-obligations.md",
            "skills/source-proof/references/failure-patterns.md",
            "skills/source-proof/references/static-evidence.md",
            "skills/source-proof/references/gotchas.md",
            "skills/testcase-generation/references/closure-safety.md",
        ),
        query_slices=(
            QuerySlice(method="branches_for_key", seed_from="lemma_leads", limit=8),
            QuerySlice(method="templates_for_key", seed_from="lemma_leads", limit=8),
            QuerySlice(method="locate_dim", seed_from="lemma_leads", limit=6),
            QuerySlice(method="neighbors", seed_from="open_keys", limit=6),
        ),
        token_budget=5000,
    ),
    "ce-review-code-review": ContextProfile(
        id="ce-review-code-review",
        description="Code review: impact neighborhood of changed files + cross-layer gotchas.",
        references=(
            "skills/code-review/references/ascendc-checks.md",
            "skills/code-review/references/cross-layer-contracts.md",
            "skills/code-review/references/gotchas.md",
            "skills/_shared/finding-format.md",
        ),
        query_slices=(
            QuerySlice(method="entities_in_files", seed_from="impact_files", limit=20),
            QuerySlice(method="impact_of", seed_from="impact_files", limit=12),
            QuerySlice(method="neighbors", seed_from="impact_files", limit=8),
        ),
        token_budget=4500,
    ),
}


def get_profile(profile_id: str | None) -> ContextProfile | None:
    if not profile_id:
        return None
    return PROFILES.get(str(profile_id).strip())
