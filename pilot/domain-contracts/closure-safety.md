# Domain contract: closure safety

Owner: `solve` (`skills/solve/`).

Consumers: `source-proof`. Load only via the current Action's explicit refs;
do not open the owner skill from a foreign SKILL body.

Invariant: `T = (R ∩ T) ∪ E` and `R ∩ E = ∅`. Replay reject is not E.
