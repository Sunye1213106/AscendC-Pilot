# FINDING — GM SetValue/GetValue loop (real cannbot-skills material)

## Source

`cannbot-skills/ops/ascendc-code-review/references/ascendc-api.md` (API-1).

## Given

Kernel loop uses `GlobalTensor::SetValue` / `GetValue` for bulk copy.

## Correct finding

High severity: element-wise GM access forbidden; should use `DataCopyPad` (or equivalent bulk API).

## Why

Matches published AscendC review rule with concrete bad/good snippets from cannbot-skills.
