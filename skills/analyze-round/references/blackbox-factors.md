# Blackbox factors (distilled)

**When to load**: choosing knobs for a targeted scenario. Distilled from
ST design / blackbox L0–L2 intent. Do **not** run the factor solver or
emit a full ST CSV matrix.

## Level intent (not TG L2/L3)

| Intent | Scale | Use in targeted overlay |
| --- | --- | --- |
| L0 threshold | small, fast, each discrete factor once | smoke inside a scenario |
| L1 functional | typical / competitive shapes, pairwise on discrete factors | `F-SHAPE-TYPICAL`, default precision shape |
| L2 abnormal | empty, illegal combo, overflow | `P-TAIL`, `P-ILLEGAL` |

TG L2 means TilingKey closure. Do not confuse the names.

## Factor families

Existence, layout, rank, dtype, value-range (magnitude bands + boundary +
specials), list length, scalar/enum. Only build cross-parameter constraints
for real dependencies (broadcast, dtype lock-step, optional presence).

## Value-range trim

Three bands when the scenario needs numeric coverage: magnitude classes,
dtype/shape boundaries, specials (`±0` / inf / nan) if the op defines them.
Drop bands the op forbids (e.g. unsigned inputs drop negatives).

Targeted construction picks **one or two** values per attached factor, not
the cartesian product of the ST table.
