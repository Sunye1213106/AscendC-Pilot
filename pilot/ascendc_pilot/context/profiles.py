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
        "full_memory",
        "unrelated_ir",
        "reference_bodies",
    )


# High-value Action profiles. Ids are declared explicitly on LLM Actions in specs.py.
PROFILES: dict[str, ContextProfile] = {
    "uo-investigate-investigate": ContextProfile(
        id="uo-investigate-investigate",
        description="Bounded unresolved residual investigation: blockers + nearby graph + gotchas.",
        references=(
            "skills/operator-analysis/references/codemap-authority.md",
            "skills/operator-analysis/references/codemap-completeness.md",
            "skills/operator-analysis/references/semantic-resolution.md",
            "skills/operator-analysis/references/codemap-build-gotchas.md",
            "skills/operator-analysis/references/evidence-quality.md",
            "skills/operator-analysis/references/cpp-semantics.md",
        ),
        query_slices=(
            QuerySlice(method="search", seed_from="unresolved_blockers", limit=12),
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
            "skills/operator-analysis/references/evidence-quality.md",
        ),
        query_slices=(
            QuerySlice(method="search", seed_from="unresolved_blockers", limit=8),
            QuerySlice(method="neighbors", seed_from="unresolved_blockers", limit=6),
        ),
        token_budget=3500,
    ),
    "tg-init-bind-init": ContextProfile(
        id="tg-init-bind-init",
        description="Bind test-script columns to UO identifiers; write init.yaml draft.",
        references=(
            "skills/testcase-generation/references/test-script-repo.md",
            "skills/testcase-generation/references/gotchas.md",
        ),
        query_slices=(
            QuerySlice(method="search", seed_from="open_keys", limit=8),
        ),
        token_budget=3500,
    ),
    "tg-init-human-confirm": ContextProfile(
        id="tg-init-human-confirm",
        description="Host-owned confirm of init.yaml to enter planning.",
        references=(),
        query_slices=(),
        token_budget=800,
    ),
    "tg-plan-plan-fuse": ContextProfile(
        id="tg-plan-plan-fuse",
        description="Fuse intent into plan.md obligations rooted at CSV columns.",
        references=(
            "skills/testcase-generation/references/planning.md",
            "skills/testcase-generation/references/plan-heuristics.md",
            "skills/testcase-generation/references/gotchas.md",
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
            "skills/testcase-generation/references/gotchas.md",
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
            "skills/testcase-generation/references/gotchas.md",
        ),
        query_slices=(
            QuerySlice(method="neighbors", seed_from="open_keys", limit=8),
        ),
        token_budget=4000,
    ),
    "ce-review-code-review": ContextProfile(
        id="ce-review-code-review",
        description="Code review: quick/file/PR, CodeMap-first hypothesis testing, Kernel vs Tiling.",
        references=(
            "skills/code-review/references/ascendc-checks.md",
            "skills/code-review/references/cross-layer-contracts.md",
            "skills/code-review/references/gotchas.md",
            "skills/code-review/references/finding-format.md",
        ),
        query_slices=(
            QuerySlice(method="entities_in_files", seed_from="impact_files", limit=20),
            QuerySlice(method="impact_of", seed_from="impact_files", limit=12),
            QuerySlice(method="neighbors", seed_from="impact_files", limit=8),
        ),
        token_budget=4500,
    ),
    "ce-review-persist": ContextProfile(
        id="ce-review-persist",
        description="Host-owned: speak review findings; persist reports only if asked.",
        references=(),
        query_slices=(),
        token_budget=800,
    ),
    "ce-verify-code-review": ContextProfile(
        id="ce-verify-code-review",
        description="Obligation-driven review during CE verify.",
        references=(
            "skills/code-review/references/ascendc-checks.md",
            "skills/code-review/references/cross-layer-contracts.md",
            "skills/code-review/references/precision-perf-findings.md",
            "skills/code-review/references/gotchas.md",
            "skills/code-engineering/references/evidence-tiers.md",
        ),
        query_slices=(
            QuerySlice(method="entities_in_files", seed_from="impact_files", limit=16),
            QuerySlice(method="impact_of", seed_from="impact_files", limit=10),
        ),
        token_budget=4000,
    ),
    "ce-verify-harness-evidence-check": ContextProfile(
        id="ce-verify-harness-evidence-check",
        description="Check harness receipts against scenario obligations.",
        references=(
            "skills/code-engineering/references/harness-oracle.md",
            "skills/code-engineering/references/evidence-tiers.md",
            "skills/code-engineering/references/evidence-discipline.md",
        ),
        query_slices=(),
        token_budget=2500,
    ),
    "ce-verify-exclusion-review": ContextProfile(
        id="ce-verify-exclusion-review",
        description="Referee review of verification-obligation exclusions.",
        references=(
            "skills/code-engineering/references/evidence-discipline.md",
            "skills/code-engineering/references/evidence-tiers.md",
            "skills/code-engineering/references/gotchas.md",
        ),
        query_slices=(
            QuerySlice(method="impact_of", seed_from="impact_files", limit=8),
        ),
        token_budget=3000,
    ),
    "ce-impact-impact-audit": ContextProfile(
        id="ce-impact-impact-audit",
        description="Audit impact ledger and verification obligations.",
        references=(
            "skills/code-engineering/references/evidence-discipline.md",
            "skills/code-engineering/references/evidence-tiers.md",
            "skills/code-engineering/references/risk-classes.md",
            "skills/code-engineering/references/gotchas.md",
        ),
        query_slices=(
            QuerySlice(method="entities_in_files", seed_from="impact_files", limit=16),
            QuerySlice(method="impact_of", seed_from="impact_files", limit=12),
            QuerySlice(method="neighbors", seed_from="impact_files", limit=8),
        ),
        token_budget=4000,
    ),
    "ce-impact-scenario-knobs": ContextProfile(
        id="ce-impact-scenario-knobs",
        description="Fill precision/perf scenario knobs from impact slice.",
        references=(
            "skills/code-engineering/references/scenario-infer.md",
            "skills/code-engineering/references/scenario-catalog.md",
            "skills/testcase-generation/references/precision-scenarios.md",
            "skills/testcase-generation/references/perf-scenarios.md",
        ),
        query_slices=(
            QuerySlice(method="entities_in_files", seed_from="impact_files", limit=12),
            QuerySlice(method="impact_of", seed_from="impact_files", limit=8),
        ),
        token_budget=3500,
    ),
    "ce-impact-scenario-confirm": ContextProfile(
        id="ce-impact-scenario-confirm",
        description="Host-owned confirm of inferred precision/perf ScenarioSet.",
        references=(),
        query_slices=(),
        token_budget=800,
    ),
    "ce-intent-feature-decompose": ContextProfile(
        id="ce-intent-feature-decompose",
        description="Decompose a change intent into CodeMap-anchored features.",
        references=(
            "skills/code-engineering/references/slice-primitives.md",
            "skills/code-engineering/references/risk-classes.md",
            "skills/code-engineering/references/gotchas.md",
            "skills/code-engineering/references/evidence-tiers.md",
        ),
        query_slices=(
            QuerySlice(method="entities_in_files", seed_from="impact_files", limit=12),
            QuerySlice(method="search", seed_from="unresolved_blockers", limit=8),
            QuerySlice(method="neighbors", seed_from="impact_files", limit=8),
        ),
        token_budget=4000,
    ),
    "ce-intent-intent-grill": ContextProfile(
        id="ce-intent-intent-grill",
        description="Grill an intent into in_scope / out_of_scope / acceptance before decompose.",
        references=(
            "skills/code-engineering/references/gotchas.md",
            "skills/code-engineering/references/risk-classes.md",
            "skills/code-engineering/references/evidence-tiers.md",
            "skills/code-engineering/references/intent-grill-staging.md",
        ),
        query_slices=(
            QuerySlice(method="search", seed_from="unresolved_blockers", limit=8),
            QuerySlice(method="entities_in_files", seed_from="impact_files", limit=8),
        ),
        token_budget=3500,
    ),
    "ce-intent-grill-confirm": ContextProfile(
        id="ce-intent-grill-confirm",
        description="Host-owned confirm that the grilled intent is closed enough to decompose.",
        references=(),
        query_slices=(),
        token_budget=800,
    ),
    "ce-apply-patch": ContextProfile(
        id="ce-apply-patch",
        description="Apply a confirmed CE intent to operator source at located anchors.",
        references=(
            "skills/code-engineering/references/gotchas.md",
            "skills/code-engineering/references/risk-classes.md",
        ),
        query_slices=(
            QuerySlice(method="entities_in_files", seed_from="impact_files", limit=12),
            QuerySlice(method="neighbors", seed_from="impact_files", limit=8),
        ),
        token_budget=4000,
    ),
    "ce-apply-code-review": ContextProfile(
        id="ce-apply-code-review",
        description="Two-axis review of an apply patch against intent and AscendC standards.",
        references=(
            "skills/code-review/references/ascendc-checks.md",
            "skills/code-review/references/cross-layer-contracts.md",
            "skills/code-review/references/finding-format.md",
            "skills/code-review/references/gotchas.md",
        ),
        query_slices=(
            QuerySlice(method="impact_of", seed_from="impact_files", limit=8),
            QuerySlice(method="entities_in_files", seed_from="impact_files", limit=8),
        ),
        token_budget=3500,
    ),
    "ce-apply-report": ContextProfile(
        id="ce-apply-report",
        description="Host-owned report of apply paths and Spec/Standards review conclusions.",
        references=(),
        query_slices=(),
        token_budget=800,
    ),
    "ce-handoff-session": ContextProfile(
        id="ce-handoff-session",
        description="Pointer-only CE session handoff; next slash, not skill names.",
        references=(),
        query_slices=(),
        token_budget=1200,
    ),
    "ce-intent-plan-review": ContextProfile(
        id="ce-intent-plan-review",
        description="Referee review of the change-plan decomposition.",
        references=(
            "skills/code-engineering/references/gotchas.md",
            "skills/code-engineering/references/slice-primitives.md",
            "skills/code-engineering/references/evidence-discipline.md",
        ),
        query_slices=(
            QuerySlice(method="impact_of", seed_from="impact_files", limit=8),
        ),
        token_budget=3000,
    ),
    "ce-intent-human-confirm": ContextProfile(
        id="ce-intent-human-confirm",
        description="Host-owned confirm of the CE change plan.",
        references=(),
        query_slices=(),
        token_budget=800,
    ),
}


def get_profile(profile_id: str | None) -> ContextProfile | None:
    if not profile_id:
        return None
    return PROFILES.get(str(profile_id).strip())
