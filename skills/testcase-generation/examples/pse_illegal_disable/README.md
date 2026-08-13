# PSE illegal combination — Disable, do not run NPU

## Source

FAG illegal PSE combinations (worked-example comment C1/C3 → `P-ILLEGAL`). Corpus rows may already be `enable=disable`.

## Given

An optional PSE / mask combination that source or distilled notes mark illegal.

## Task (TG)

Emit the combination as Disable / exclusion. Do not call the NPU adapter. Do not invent a new scenario id.

## Correct outcome

- Scenario id: `P-ILLEGAL` (and `P-OPTIONAL` if the tensor is optional).
- CSV `enable` is `disable`.
- Harness run reason is `disabled_no_npu`.

## Why correct

Illegal combinations are not precision oracles. Running them on device is out of scope for the daily scenario overlay.
