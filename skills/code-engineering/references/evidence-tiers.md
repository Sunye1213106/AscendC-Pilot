# Evidence Tiers

- **Tier A — authoritative fact:** compiler/AST fact, exact source span,
  committed canonical CodeMap fact with direct provenance, test result, build
  result, trace, or declared external measurement tied to the reviewed version.
- **Tier B — reproducible derivation:** deterministic result computed from Tier
  A inputs, including bounded graph slices and ledger set arithmetic. Record
  algorithm parameters and boundaries.
- **Tier C — hypothesis:** lexical heuristic, model judgment, naming inference,
  analogy, unverified report, or any result with unresolved provenance.

Tier C is useful for finding anchors and proposing obligations. It cannot close
an obligation: only Tier A or a reproducible Tier B derivation grounded in Tier
A may add an item to `V` or support referee approval into `X`.
