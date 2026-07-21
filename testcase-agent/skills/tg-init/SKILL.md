---
name: tg-init
description: >-
  TG stage-1: intake + contract + binding. Parent agent MUST auto-spawn nested
  uo-query Tasks for every open mid-symbol until --verify-csv-closure passes;
  user never manually lists mids or writes half-chains.
argument-hint: "<算子仓> --op-name <op> --test-script-root <测试工具> | --merge-uo-resolve | --verify-csv-closure | --confirm"
---

# /tg-init（摄入 + 绑定一体）

## 用户 vs 父代理（HARD）

| 角色 | 做什么 |
|------|--------|
| **用户** | 只发 `/tg-init <算子仓> --op-name … --test-script-root …`（或等价一句话） |
| **父代理** | 全自动：KEY Task → merge → **读 mid_symbol_queue 自动开套娃 Task** → merge → verify → audit → confirm |

**禁止**向用户交代「请对 bnSparseLimit 开 Task」「请跑 --list-open-mids」——那是父代理自己的循环，不是用户清单。

## Lexicon = 可执行真值

`realization/binding_lexicon.yaml` 的 `key_derivations` 才是 `tg-solve` 吃的 CSV→KEY 表达式。  
`uo_query_resolve/KEY_*.yaml` 只是证据；**必须** `--merge-uo-resolve` 合并后才能 `--confirm`。

**HARD**：`confidence` 只许 `high`；`derivation_chain` 叶子必须到 `VAR_CSV_*`；禁止 medium / 半截 chain / `already_bound_in_kb`。  
不确定中间量 → 父代理 **自动套娃 Task**（`references/tg-mid-symbol-nesting.md`），直到 `--verify-csv-closure` pass。

禁止：父代理手写/改 lexicon；问用户代劳追符号。

## MUST — 父代理自动执行的 CLI 环

```powershell
tg-init "<算子仓>" --op-name <op> --test-script-root "<测试工具>"
# ↓ 父代理：每 KEY 并行 Task Follow uo-query
tg-init ... --merge-uo-resolve
# ↓ 若 merge.mid_symbol_queue.count>0 或 --list-open-mids 非空：
#    父代理对每个 symbol 自动 Task Follow uo-query（禁止跳过、禁止问用户）
tg-init ... --merge-uo-resolve   # 套娃写回后再 merge
# ↓ kernel unbound 同理自动 Task
tg-init ... --verify-csv-closure   # 非 pass → 继续套娃，禁止 confirm
# ↓ Task tg-init-audit
tg-init ... --confirm
```

## 父代理编排（HARD · 全自动）

1. 扫 `needs_binding_keys` → 并行 KEY Task（cap ~8）
2. `--merge-uo-resolve` → 读 `mid_symbol_queue` / merge 报告
3. **queue 非空 ⇒ 立即并行 mid Task**（每符号一 Task；子 Task 再撞 mid 再套娃）→ 再 merge  
   循环直到 queue 空或达上限后仍非空则 **停在 fail**（向用户只报 ask，不甩追符号作业）
4. kernel unbound 聚合 → 同样自动 Task → merge
5. `--verify-csv-closure` 必须 pass
6. Task `tg-init-audit` → pass 后 `--confirm`

详见 `references/tg-uo-query-escalation.md`、`references/tg-mid-symbol-nesting.md`。
