---
name: tg-contract
description: >-
  Thin CSV consumer AST scan. Prefer /tg-init which embeds contract + binding.
  Does not invent operator semantics.
argument-hint: "<算子仓> --op-name <op> --test-script-root <测试工具>"
---

# /tg-contract（兼容；优先 /tg-init）

Thin AST：发现 CSV 列与 gaps，**不算子语义**。完整流程请用 `/tg-init`。

```powershell
tg-contract "<算子仓>" --op-name <op> --test-script-root "<测试工具>"
```

语义绑定 / uo-query / 人确认 → `/tg-init`。
