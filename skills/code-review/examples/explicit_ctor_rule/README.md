# FINDING — explicit ctor rule (real cannbot-skills material)

## Source

`cannbot-skills/ops/ascendc-code-review/references/cpp-general.md` rule 15.5.

## Given

Single-arg ctor without `explicit`; multi-arg ctor incorrectly marked `explicit`.

## Correct finding

Medium: enforce `explicit` on single-arg; do not mark multi-arg `explicit`.
