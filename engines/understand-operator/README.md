# Ascend C understand-operator（UO CodeMap Compiler）

将 AscendC 算子源码 + 编译上下文 + 硬件架构编译为可查询的单一 CodeMap 产物：

```text
.ascendc-pilot/uo/<op_name>.<arch>.uo
```

| 项 | 说明 |
|----|------|
| 包名 | `uo_init`（`src/uo_init/`） |
| 公共 Action | `prepare` / `extract` / `analyze` / `resolve` / `commit` / `review` |
| 引擎入口 | `uo_init.pilot_engines.ENGINES` + `uo_init.codemap_engines` |
| 查询 | `uo_init.query.CodeMapQuery` / `uo_init.uo_query` |
| 调试导出 | `python -m uo_init dump`（`uo-dump`） |

## 架构

```text
Clang Frontend (CompilerFacts)
  → ReachabilityPass
  → Deterministic Passes → CodeMap IR
  → Semantic Gap Resolver
  → operator.<arch>.uo
```

包布局：

```text
uo_init/
  build.py
  frontend/   # clang / build_variant / preprocessor
  ir/         # entity / relation / codemap
  passes/     # reachability … host_kernel
  resolve/    # semantic_gap
  store/      # schema / writer / reader
  query/      # CodeMap API
  dump.py
```

已废弃的多层 YAML 流水线脚本见 `_archive/`（只读，禁止被 ENGINES 引用）。

## 文档

- 架构：[`docs/design/architecture.md`](../../docs/design/architecture.md)
- Domain：[`skills/domain/uo-codemap-build`](../../skills/domain/uo-codemap-build)

## 本地调试

```powershell
python -m uo_init dump path\to\op.arch35.uo --summary
python -m uo_init dump path\to\op.arch35.uo --path queryType KERNEL
```

冷启动预算与缓存环境变量（`UO_INIT_PROFILE` / `UO_TU_CACHE` 等）仍作用于内部 extract/derive 步骤。
