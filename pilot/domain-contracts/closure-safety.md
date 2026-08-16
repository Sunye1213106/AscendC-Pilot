# Domain contract: closure safety

Owner: `testcase-generation` (`skills/testcase-generation/references/closure-safety.md`).

Consumers: `source-proof` lemma METHOD. Load only via the Action Context
Profile — do not open the owner skill from a foreign METHOD body.

Invariant: `T = (R ∩ T) ∪ E` and `R ∩ E = ∅`. Replay reject is not E.
