---
name: tg-solve
description: >-
  SMT+CSV for approved level with Allow solve:yes. Domain-symmetry gate at
  start; never hand-edit lexicon to unblock Z3.
argument-hint: "<project_root> --op-name <op> --level L0|L1-BRANCH|L1-REJECT|L2"
---

# /tg-solve

```powershell
tg-solve <project_root> --op-name <op> --level L0
```

启动前校验：approval + domain_review + **domain_symmetry**（lexicon 字面量 ∈ CSV 域）。  
失败 → `ask=domain_asymmetry` → `tg-init --merge-uo-resolve`，**禁止**会话 Edit YAML。

语义失败 → Task Follow uo-query → merge → replan 一次。
