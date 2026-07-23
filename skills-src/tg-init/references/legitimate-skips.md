# 合法 skip 白名单（唯一真值）

权威实现：`testcase_agent/resolve_policy.py` → `LEGITIMATE_SKIP_REASONS` + `EMPTY_KEY_ALLOWLIST` + `is_legitimate_skip()`。

文档（本文件）、`tg-init` SKILL、audit `unresolved_honesty`、`uo-query` Invariants **MUST** 同表。

## 允许的 unresolved（不阻塞 merge / verify / audit）

| 类别 | 判定 | 说明 |
|------|------|------|
| `empty_tensor` | `key_id` ∈ `EMPTY_KEY_ALLOWLIST`（如 `KEY_ISEMPTYTENSOR`） | **只认 key_id**；禁止伪造 `empty_allowlisted: true` |
| `phantom_key` / `phantom_key_not_in_tiling_key_space` | `skip_reason` 命中 | 不在 tiling key 空间 |
| `compile_time_constant` / `platform_macro_only` | `skip_reason` 命中 | 编译期 / 平台宏 |
| `not_input_derivable` | `not_input_derivable: true` 或 `input_derivable: false`，或 `skip_reason` 以 `not_input_derivable` / `kernel_local` 开头 | **核内局部**，不进 uo-query Task；UO 建库已标死则 TG 跳过。**注意**：`input_derivable: unsolved` 不是本行——仍派 uo-query 在 OUT_ROOT 做 CSV 映射，不回写 UO 图 |

同族别名（脚本亦认）：`kernel_local`、`kernel_local_batch_or_loop_index`。

## 禁止（伪 skip → fail / `ask=fake_not_csv_excuse`）

`cross_variable_*`、`*_not_csv_realizable`、`runtime_derived_*`、`runtime_shape_*`、
`template_selection_*`、`depends_on_*_chain`、伪造 `empty_allowlisted` 等。

跨变量比较写 LogicExpr（`eq`/`ne`），不得标 not_csv。
