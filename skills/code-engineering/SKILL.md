---
name: code-engineering
description: >
  Plan, scope, and verify AscendC code changes with UO slices, evidence tiers,
  risk classes, and a persistent verification-obligation ledger.
---

# Code Engineering

Use this skill for `/ce-intent`, `/ce-impact`, and `/ce-verify`.

```text
intent -> bounded UO slice -> risk classification -> obligations
       -> verification evidence -> residual/exclusion review -> certificate
```

## Non-negotiable rules

1. Preserve evidence tier: Tier A is direct authoritative evidence, Tier B is
   deterministic derivation from Tier A, and Tier C is a hypothesis or lead.
2. Maintain `Open = O - V - X`, where `O` is all obligations, `V` is verified,
   and `X` is referee-approved exclusions.
3. Tier C evidence can discover or refine obligations, but cannot place an
   obligation in `V` or `X`.
4. A truncated slice or stale UO product is a disclosed boundary, never proof
   that impact is absent.
5. Precision and performance claims require declared external measurements.

## Capability routing

- Impact completeness and obligation audit:
  `capabilities/ce-impact-audit/METHOD.md`
- Exclusion review:
  `capabilities/ce-exclusion-review/METHOD.md`
- Evidence and slicing:
  `references/evidence-tiers.md`, `references/slice-primitives.md`,
  `references/evidence-discipline.md`
- Risk classification:
  `references/risk-classes.md`
