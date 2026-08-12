# CE Exclusion Review Method

An exclusion moves an obligation from `Open` to `X`; it is not a weak form of
verification.

1. Identify the exact obligation and proposed non-applicability rule.
2. Require Tier A evidence, or a reproducible Tier B derivation grounded in
   Tier A, that covers the obligation's full scope.
3. Try to construct a counterexample through backward and forward UO slices.
4. Reject exclusions based on naming, an incomplete search, a truncated slice,
   stale artifacts, unsupported environment assumptions, or Tier C judgment.
5. Record reviewer, evidence references, scope, and invalidation conditions.
6. Recompute `Open = O - V - X`; never delete the obligation from `O`.
