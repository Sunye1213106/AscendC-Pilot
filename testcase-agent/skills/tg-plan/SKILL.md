---
name: tg-plan
description: >-
  TG stage-2 after tg-init confirmed + merge pass. L1-REJECT empty or KEY gaps
  → Allow solve: no (approve blocked).
argument-hint: "<算子仓> --op-name <op> [--level L0,L1,L2]"
---

# /tg-plan

门禁：`init.status=confirmed`（需先 `--merge-uo-resolve` 通过）。

`--level L1` → L1-BRANCH + L1-REJECT。空 L1-REJECT / 未闭合 `KEY_DERIVATION_MISSING` → **Allow solve: no**，禁止 approve。

```powershell
tg-plan "<算子仓>" --op-name <op> --level L0,L1,L2
```

缺口大 → 回 `tg-init` Task uo-query + `--merge-uo-resolve`，勿手改 lexicon。
