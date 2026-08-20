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
    # Domain reference files relative to repo root (skills/<skill>/...).
    # Compiler records paths only; bodies stay in the static method/skill prefix.
    references: tuple[str, ...] = ()
    query_slices: tuple[QuerySlice, ...] = ()
    include_prior_failure: bool = True
    # Hard cap on estimated tokens for the graph_slice section.
    token_budget: int = 4000
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
        references=(
            "skills/operator-analysis/references/codemap-build-gotchas.md",
        ),
        query_slices=(),
        token_budget=2500,
    ),
    "uo-investigate-investigate": ContextProfile(
        id="uo-investigate-investigate",
        description="Bounded unresolved residual investigation: blockers + nearby graph + gotchas.",
        references=(
            "skills/operator-analysis/references/codemap-authority.md",
            "skills/operator-analysis/references/codemap-completeness.md",
            "skills/operator-analysis/references/semantic-resolution.md",
            "skills/operator-analysis/references/codemap-build-gotchas.md",
        ),
        query_slices=(
            QuerySlice(method="neighbors", seed_from="unresolved_blockers", limit=8),
            QuerySlice(method="constraints_for", seed_from="unresolved_blockers", limit=8),
        ),
        token_budget=4500,
    ),
    "uo-query-kb-lookup": ContextProfile(
        id="uo-query-kb-lookup",
        description="Read-only CodeMap Q&A: query gotchas + nearby unresolved neighborhood.",
        references=(
            "skills/operator-analysis/references/codemap-query-gotchas.md",
            "skills/operator-analysis/references/uo-scenario-hooks.md",
            "skills/operator-analysis/references/codemap-authority.md",
        ),
        query_slices=(
            QuerySlice(method="neighbors", seed_from="unresolved_blockers", limit=6),
            QuerySlice(method="constraints_for", seed_from="unresolved_blockers", limit=8),
        ),
        token_budget=3500,
    ),
    "tg-init-bind-init": ContextProfile(
        id="tg-init-bind-init",
        description="Bind test-script columns to UO identifiers; write init.yaml draft.",
        references=(
            "skills/testcase-generation/references/test-script-repo.md",
            "skills/testcase-generation/references/construction-gotchas.md",
        ),
        query_slices=(
            QuerySlice(method="neighbors", seed_from="open_keys", limit=8),
        ),
        token_budget=3500,
    ),
    "tg-init-bind-review": ContextProfile(
        id="tg-init-bind-review",
        description="Primary reads both bind drafts; next pilot_run is PASS or REWORK.",
        references=(
            "skills/testcase-generation/references/test-script-repo.md",
        ),
        query_slices=(),
        token_budget=2000,
    ),
    "tg-plan-plan-fuse": ContextProfile(
        id="tg-plan-plan-fuse",
        description="Fuse intent into plan.md obligations rooted at CSV columns.",
        references=(
            "skills/testcase-generation/references/planning.md",
            "skills/testcase-generation/references/plan-heuristics.md",
            "skills/testcase-generation/references/planning-gotchas.md",
            "skills/testcase-generation/references/planning-context.md",
        ),
        query_slices=(
            QuerySlice(method="neighbors", seed_from="open_keys", limit=8),
            QuerySlice(method="constraints_for", seed_from="open_keys", limit=6),
        ),
        token_budget=4000,
    ),
    "tg-plan-plan-approve": ContextProfile(
        id="tg-plan-plan-approve",
        description="Host-owned approve of plan.md.",
        references=(),
        query_slices=(),
        token_budget=800,
    ),
    "tg-solve-construct-cases": ContextProfile(
        id="tg-solve-construct-cases",
        description="Construct case rows for approved obligations.",
        references=(
            "skills/testcase-generation/references/construction-contract.md",
            "skills/testcase-generation/references/closure-gotchas.md",
            "skills/testcase-generation/references/oracle.md",
        ),
        query_slices=(
            QuerySlice(method="constraints_for", seed_from="open_keys", limit=8),
        ),
        token_budget=3500,
    ),
    "tg-solve-analyze-round": ContextProfile(
        id="tg-solve-analyze-round",
        description="Write per-case worklog: scene, construction, narrowing, lemmas.",
        references=(
            "skills/testcase-generation/references/closure-gotchas.md",
            "skills/testcase-generation/references/oracle.md",
        ),
        query_slices=(
            QuerySlice(method="neighbors", seed_from="open_keys", limit=8),
        ),
        token_budget=4000,
    ),
    "ce-review-code-review": ContextProfile(
        id="ce-review-code-review",
        description="Dual-axis review of a captured git/PR diff; dialogue only.",
        references=(
            "skills/code-review/references/ascendc-checks.md",
            "skills/code-review/references/cross-layer-contracts.md",
            "skills/code-review/references/gotchas.md",
        ),
        query_slices=(
            QuerySlice(method="agent_query", seed_from="change_capture_identifiers", limit=6),
        ),
        token_budget=4500,
    ),
    "ce-review-report": ContextProfile(
        id="ce-review-report",
        description="Host-owned: suggest modify or suggest tests; do not persist review yaml.",
        references=(),
        query_slices=(),
        token_budget=800,
    ),
    "ce-plan-intent-grill": ContextProfile(
        id="ce-plan-intent-grill",
        description="Grill a requirement into in_scope / out_of_scope / acceptance before writing the plan.",
        references=(
            "skills/code-engineering/references/gotchas.md",
            "skills/code-engineering/references/intent-grill-staging.md",
            "skills/code-engineering/examples/deter-band-schedule_plan.md",
        ),
        query_slices=(
            QuerySlice(method="neighbors", seed_from="unresolved_blockers", limit=8),
        ),
        token_budget=3500,
    ),
    "ce-plan-grill-confirm": ContextProfile(
        id="ce-plan-grill-confirm",
        description="Host-owned confirm that the grilled intent is closed enough to write {slug}_plan.md.",
        references=(),
        query_slices=(),
        token_budget=800,
    ),
    "ce-plan-draft": ContextProfile(
        id="ce-plan-draft",
        description="Write ce/plan/{slug}_plan.md: analysis, plan, todos, test section.",
        references=(
            "skills/code-engineering/references/gotchas.md",
            "skills/code-engineering/examples/deter-band-schedule_plan.md",
        ),
        query_slices=(
            QuerySlice(method="neighbors", seed_from="unresolved_blockers", limit=6),
            QuerySlice(method="constraints_for", seed_from="unresolved_blockers", limit=8),
        ),
        token_budget=4000,
    ),
    "ce-plan-human-confirm": ContextProfile(
        id="ce-plan-human-confirm",
        description="Host-owned confirm of the named CE plan markdown.",
        references=(),
        query_slices=(),
        token_budget=800,
    ),
    "ce-apply-patch": ContextProfile(
        id="ce-apply-patch",
        description="Apply one unfinished todo from the current {slug}_plan.md.",
        references=(
            "skills/code-engineering/references/gotchas.md",
            "skills/code-engineering/examples/deter-band-schedule_plan.md",
        ),
        query_slices=(),
        token_budget=4000,
    ),
    "ce-apply-revise": ContextProfile(
        id="ce-apply-revise",
        description="Revise the current {slug}_plan.md from a goal delta; keep completed todos.",
        references=(
            "skills/code-engineering/references/gotchas.md",
            "skills/code-engineering/examples/deter-band-schedule_plan.md",
        ),
        query_slices=(),
        token_budget=3500,
    ),
    "ce-apply-report": ContextProfile(
        id="ce-apply-report",
        description="Host-owned: suggest review, tests, back to plan, or handoff.",
        references=(),
        query_slices=(),
        token_budget=800,
    ),
    "handoff-session": ContextProfile(
        id="handoff-session",
        description="Pointer-only session handoff markdown; next slash, no copied bodies.",
        references=(),
        query_slices=(),
        token_budget=1200,
    ),
}


def get_profile(profile_id: str | None) -> ContextProfile | None:
    if not profile_id:
        return None
    return PROFILES.get(str(profile_id).strip())
