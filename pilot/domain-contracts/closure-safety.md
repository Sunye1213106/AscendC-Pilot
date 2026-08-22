# Domain contract: closure safety

Owner: `solve` (`skills/solve/`).

Consumers: `source-proof` lemma Skill. Load only via the Action Context
Profile — do not open the owner skill from a foreign SKILL body.

Invariant: `T = (R ∩ T) ∪ E` and `R ∩ E = ∅`. Replay reject is not E.
