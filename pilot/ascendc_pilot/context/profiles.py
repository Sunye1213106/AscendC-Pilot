"""Context profile registry — declarative slice recipes per Action.

Profiles are opt-in. When no profile matches ``context_profile_id``, the
legacy lightweight ``build_context_pack`` path is used unchanged.

Unregistered Actions must omit ``context_profile_id`` (explicit None). Do not
fabricate ``{workflow}-{action}`` ids that are not in this registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class QuerySlice:
    """One UoQuery call family to include in the compiled slice."""

    method: str
    # seed_from: where seed entity ids come from (relative to project uo/tg roots).
    # Supported: unresolved_blockers | lemma_leads | open_keys | change_capture_identifiers | none
    seed_from: str = "none"
    limit: int = 16
    # Extra kwargs passed to the query method when applicable.
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextProfile:
    id: str
    description: str = ""
    query_slices: tuple[QuerySlice, ...] = ()
    include_prior_failure: bool = True
    # Hard cap on estimated tokens for the graph_slice section.
    token_budget: int = 4000
    # Host-dynamic refs that SKILL.md did not declare. Must be owner-qualified
    # ``skills/<id>/references/<rel>.md`` and disjoint from SKILL pointers.
    conditional_refs: tuple[str, ...] = ()
    # Always-excluded material (documentation for agents; compiler enforces).
    excluded: tuple[str, ...] = (
        "full_kb",
        "full_source_tree",
        "unrelated_ir",
        "reference_bodies",
    )


# High-value Action profiles. Ids are declared explicitly on LLM Actions in specs.py.
PROFILES: dict[str, ContextProfile] = {
    "uo-init-propose-include-heal": ContextProfile(
        id="uo-init-propose-include-heal",
        description="Propose extra -I dirs for unresolved include-heal; staging only.",
        query_slices=(),
        token_budget=2500,
    ),
    "uo-investigate-investigate": ContextProfile(
        id="uo-investigate-investigate",
        description="Bounded unresolved residual investigation: blockers + nearby graph + gotchas.",
        query_slices=(
            QuerySlice(method="neighbors", seed_from="unresolved_blockers", limit=8),
            QuerySlice(method="constraints_for", seed_from="unresolved_blockers", limit=8),
        ),
        token_budget=4500,
    ),
    "uo-query-kb-lookup": ContextProfile(
        id="uo-query-kb-lookup",
        description="Read-only CodeMap Q&A: query gotchas + nearby unresolved neighborhood.",
        query_slices=(
            QuerySlice(method="neighbors", seed_from="unresolved_blockers", limit=6),
            QuerySlice(method="constraints_for", seed_from="unresolved_blockers", limit=8),
        ),
        token_budget=3500,
    ),
    "tg-init-bind-init": ContextProfile(
        id="tg-init-bind-init",
        description="Bind test-script columns to UO identifiers; write init.yaml draft.",
        query_slices=(
            QuerySlice(method="neighbors", seed_from="open_keys", limit=8),
        ),
        token_budget=3500,
    ),
    "tg-init-bind-review": ContextProfile(
        id="tg-init-bind-review",
        description="Primary reads both bind drafts; next pilot_run is PASS or REWORK.",
        query_slices=(),
        token_budget=2000,
    ),
    "tg-plan-plan-scope": ContextProfile(
        id="tg-plan-plan-scope",
        description="Write the test purpose for this PR from init.yaml and the compact change packet.",
        query_slices=(),
        token_budget=2500,
    ),
    "tg-plan-plan-fuse": ContextProfile(
        id="tg-plan-plan-fuse",
        description="Fuse intent into plan.md obligations rooted at CSV columns.",
        query_slices=(
            QuerySlice(method="neighbors", seed_from="open_keys", limit=8),
            QuerySlice(method="constraints_for", seed_from="open_keys", limit=6),
        ),
        token_budget=4000,
    ),
    "tg-plan-plan-approve": ContextProfile(
        id="tg-plan-plan-approve",
        description="Host-owned approve of plan.md.",
        query_slices=(),
        token_budget=800,
    ),
    "tg-solve-construct-cases": ContextProfile(
        id="tg-solve-construct-cases",
        description="Construct case rows for approved obligations.",
        query_slices=(
            QuerySlice(method="constraints_for", seed_from="open_keys", limit=8),
        ),
        token_budget=3500,
    ),
    "tg-solve-analyze-round": ContextProfile(
        id="tg-solve-analyze-round",
        description="Split expected vs unexpected Replay, grow R, derive lemmas, sync worklog.",
        query_slices=(
            QuerySlice(method="neighbors", seed_from="open_keys", limit=8),
        ),
        token_budget=4000,
    ),
    "ce-review-code-review": ContextProfile(
        id="ce-review-code-review",
        description="Dual-axis review of a captured git/PR diff; dialogue only.",
        query_slices=(
            QuerySlice(method="agent_query", seed_from="change_capture_identifiers", limit=6),
        ),
        token_budget=4500,
    ),
    "ce-review-report": ContextProfile(
        id="ce-review-report",
        description="Host-owned: suggest modify or suggest tests; do not persist review yaml.",
        query_slices=(),
        token_budget=800,
    ),
    "ce-plan-draft": ContextProfile(
        id="ce-plan-draft",
        description="Grill while writing ce/plan/{slug}_plan.md: analysis, todos, test section.",
        query_slices=(
            QuerySlice(method="neighbors", seed_from="unresolved_blockers", limit=8),
            QuerySlice(method="constraints_for", seed_from="unresolved_blockers", limit=8),
        ),
        token_budget=4500,
    ),
    "ce-plan-human-confirm": ContextProfile(
        id="ce-plan-human-confirm",
        description="Host-owned confirm of the named CE plan markdown.",
        query_slices=(),
        token_budget=800,
    ),
    "ce-apply-patch": ContextProfile(
        id="ce-apply-patch",
        description="Apply one unfinished todo from the current {slug}_plan.md.",
        query_slices=(),
        token_budget=4000,
    ),
    "ce-apply-revise": ContextProfile(
        id="ce-apply-revise",
        description="Revise the current {slug}_plan.md from a goal delta; keep completed todos.",
        query_slices=(),
        token_budget=3500,
    ),
    "ce-apply-report": ContextProfile(
        id="ce-apply-report",
        description="Host-owned: suggest review, tests, back to plan, or handoff.",
        query_slices=(),
        token_budget=800,
    ),
    "handoff-session": ContextProfile(
        id="handoff-session",
        description="Pointer-only session handoff markdown; next slash, no copied bodies.",
        query_slices=(),
        token_budget=1200,
    ),
}


def get_profile(profile_id: str | None) -> ContextProfile | None:
    if not profile_id:
        return None
    return PROFILES.get(str(profile_id).strip())
