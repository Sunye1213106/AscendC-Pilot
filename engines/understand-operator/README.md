# Ascend C understand-operator（uo_init）

确定性控制来源闭合图引擎（libclang）。UO 唯一引擎包。

| 项 | 说明 |
|----|------|
| 包名 | `uo_init`（`src/uo_init/`） |
| uo-init | `uo_init.pilot_engines.ENGINES` |
| uo-update | `uo_init.update`（changes / plan / apply / diff） |
| uo-query | `uo_init.uo_query` |

## 主模块

| 模块 | 职责 |
|------|------|
| `clang_walk` / `host_ir` | Host AST 写点、守卫、RETURN_SLOT |
| `assemble_kb` | Host bundle、导出分层 KB |
| `tpl_dsl` / `tpl_bind` | TilingKey DSL 与 host 实参绑定 |
| `derive_key_fields` | 各 key 维度回溯到输入根 |
| `variable_model` / `predicate` | 变量域与 SMT-lite 谓词 |
| `materialize_tiling` | tiling 物化 / key 表 |
| `pilot_engines` | uo-init Action |
| `update/` | 增量更新管线 |
| `uo_query` | 只读查询 |

## 文档

- 索引：[`docs/README.md`](../../docs/README.md)
- 架构：[`docs/design/architecture.md`](../../docs/design/architecture.md)
- 控制闭合：[`docs/design/control-closure.md`](../../docs/design/control-closure.md)

## 本地派生

```powershell
acp run-action derive_key_fields
# 默认只保留 status/leaves/roots 等轻量元数据；value_expr/expanded 评分后丢弃。
# 需要 Z3 key 可达性或 tiling/expr 分片时再开深度求解：
$env:UO_DEEP_SOLVE=1; acp run-action derive_key_fields
```

## 静态抽取加速

| 目标 | 环境 | 说明 |
|------|------|------|
| 冷启动 ≤ 3 分钟 | `UO_INIT_PROFILE=fast`（默认）、`UO_COLD_BUDGET_S=180` | `closure_mode=keypath` + 跳过 pairwise fold |
| 热重跑 ≤ 2 分钟 | 源码未变 + TU/derive/fold 缓存 | `UO_WARM_REPLAY_BUDGET_S=120` |
| 完整闭包（可更慢） | `UO_INIT_PROFILE=full` | full controllability + kernel fold |

缓存目录：`.ascendc-pilot/<arch>/uo/cache/{tu,derive,fold}/`（可用 `UO_CACHE_ROOT` 覆盖）。

| Env | 默认 | 作用 |
|-----|------|------|
| `UO_INIT_PROFILE` | `fast` | `fast`=冷启动预算路径；`full`=完整闭包 |
| `UO_COLD_BUDGET_S` | `180` | 冷启动墙钟预算（秒） |
| `UO_KEYPATH_MAX_NODES` | `96` | fast 路径 controllability 上限 |
| `UO_FOLD_KERNEL` | 随 profile | 覆盖是否做 pairwise fold |
| `UO_TIMING` | `1` | stderr `[uo-timing]` 相位计时 |
| `UO_TU_CACHE` | `1` | libclang walk IR 磁盘缓存（按源文件 sha256 + 编译指纹） |
| `UO_DERIVE_CACHE` | `1` | `derive_key_fields` 按字段结果缓存 |
| `UO_FOLD_CACHE` | `1` | kernel `clang -ast-dump` fold 缓存 |
| `UO_CTRL_WORKERS` | `1` | controllability 并行度（保持 1；增大常回退） |
| `UO_WARM_REPLAY_BUDGET_S` | `120` | CI warm replay 预算（秒） |

下游 `_ensure_bundle` 在已有 host meta 时默认 `closure_mode=off`（显式传入仍优先）。
计时基线：`tools/timing_baseline.py` → `docs/design/uo-timing-baseline.md`。

覆盖门禁优先走沉淀包：`tg-closure report` / `testcase_agent.closure`。
