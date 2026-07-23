# 中间符号套娃 Task（ses_07c3 模式）

**执行者 = 父代理 / 子 Task，不是用户。**  
禁止猜测、禁止 `already_bound_in_kb`、禁止伪 `not_csv_realizable`、禁止问「是否继续」。

## 自动触发

| 信号 | 动作 |
|------|------|
| chain 叶子 ∈ Host/KVAR 标识符 | 立刻 Task |
| `mid_symbol_queue` 非空（已滤算术垃圾） | 并行 Task，不问用户 |
| merge `ask=fake_not_csv_excuse` | 重写 KEY LogicExpr + 套娃，禁止再写伪 skip |
| audit/verify fail | **自动下一轮 WHILE**，禁止停手问用户 |

## 不进队列（噪声）

- 算术/比较碎片：`(p+q) gt m`、`HEAD_DIM_ALIGN le CUBE_BASEN`
- `ENABLE_*` / `CUBE_*` 平台宏
- LOOP_LOCAL / PLATFORM_MACRO / empty

## 父代理固定环

```text
WHILE not (verify_pass and audit_pass):
  Tasks → --merge-uo-resolve → --verify-csv-closure → audit
  # 仅当轮次用尽才向用户报 ask；中间不得提问
--confirm
```

查语义：子 Task **先 `uo_kb_query` sqlite 图**，再 MCP 单符号。
