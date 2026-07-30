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
- 设计：[`docs/design/control-closure.md`](../../docs/design/control-closure.md)
- 重构记录：[`docs/design/kb-extraction.md`](../../docs/design/kb-extraction.md)
- 工作流：[`docs/workflows/uo-init.md`](../../docs/workflows/uo-init.md)

## 本地探针

```powershell
python scripts/_probe_derive.py
python scripts/_probe_derive.py --refresh
```
