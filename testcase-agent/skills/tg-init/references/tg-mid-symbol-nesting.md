# 中间符号套娃 Task（ses_07c3 模式）

**执行者 = 父代理 / 子 Task，不是用户。**  
不确定 / 停在 Host 中间量时：父代理 **必须自动** 开嵌套 Task Follow `uo-query` + CBM，挖到 `VAR_CSV_*`。  
禁止猜测、禁止 `already_bound_in_kb`、禁止停在 `depends on X`、**禁止把「请开 Task」甩给用户**。

## 自动触发（任一即开 Task，无需用户确认）

| 信号 | 父代理动作 |
|------|------------|
| `derivation_chain` 叶子 ∈ Host/KVAR（`bnSparseLimit`、`deterSparseType`、`splitAxis`…） | **立刻**新 Task，目标=该符号 |
| `merge.mid_symbol_queue.count > 0` 或 `--list-open-mids` 非空 | 按队列并行 Task（cap ~8），**不问用户** |
| 子 Task 交付想写 `confidence: medium` | 禁止 resolved；继续 CBM / 再套娃 |
| KB `set_by: missing` / `needs_alignment` | MCP → 展开 |
| abstract `UNBOUND_*`（非 LOOP_LOCAL/PLATFORM） | kernel 段自动套娃 |

## 父代理固定环（HARD）

```text
KEY Tasks
  → --merge-uo-resolve
  → 读 mid_symbol_queue
  → WHILE symbols 非空:
        并行 Task Follow uo-query（每 mid 一个；可再套娃）
        → --merge-uo-resolve
        → 刷新 queue
  → kernel unbound 同 WHILE
  → --verify-csv-closure   # 必须 pass，否则不得 audit/confirm
  → tg-init-audit → --confirm
```

向用户最终只报告：`verify pass/fail` + `ask=…`（若 fail）。**不要**输出「请你对 xxx 开 Task」类下一步。

## 子 Task 交付

```yaml
derivation_chain:
  - {id: VAR_KVAR_<sym>, deps: [VAR_CSV_...], via: set_by, evidence: "path:line"}
confidence: high
# 禁止: already_bound_in_kb / deter_branch / op:call / 未展开 Get*
```

## 强验证（父代理跑，用户不跑）

`--verify-csv-closure` / `--confirm` 内 `require_full_csv_closure`：queue 非空或占位 → fail。

## 禁止

- 问用户代开 mid Task / 代跑 list-open-mids
- 手写 lexicon / 伪 `already_bound_in_kb`
- 一个 Task 包办全部 KEY+全部中间量
- 半截 chain 标 resolved 后跳过套娃环
- verify 未 pass 就 confirm
