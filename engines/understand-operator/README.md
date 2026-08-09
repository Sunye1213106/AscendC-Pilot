# AscendC understand-operator（UO CodeMap Compiler）

将 AscendC 算子源码、编译上下文与硬件 architecture 编译为单一可查询 CodeMap：

```text
.ascendc-pilot/uo/<op_name>.<arch>.uo
```

| 项 | 说明 |
|---|---|
| 包名 | `uo_init`（`src/uo_init/`） |
| 公开阶段 | `prepare` / `extract` / `analyze` / `resolve` / `commit` / `review` |
| 编排入口 | `uo_init.codemap_engines` |
| 查询 | `uo_init.query.CodeMapQuery` / `uo_init.uo_query` |
| 调试导出 | `python -m uo_init dump`（`uo-dump`） |

## 执行模型

```text
source + compile context + architecture
  → Clang/frontend CompilerFacts
  → deterministic AscendC CodeMap passes
  → explicit unresolved gaps
  → semantic resolver（仅 unresolved）
  → deterministic patch merge
  → one operator.<arch>.uo
  → deterministic structural audit
```

确定性阶段不通过 Agent/Prompt 解释脚本行为。模型只处理确定性流程无法可靠闭合、并由当前 Action Bundle 明确分配的 semantic gap。

## 包布局

```text
uo_init/
  build.py
  frontend/   # clang / build_variant / preprocessor
  ir/         # entity / relation / codemap
  passes/     # reachability / compile-time / template / dataflow / tiling / kernel ...
  resolve/    # semantic gaps
  store/      # schema / writer / reader
  query/      # CodeMap API
  dump.py
```

兼容模块可以在 engine 内部读取迁移期中间事实，但 `.uo` 是对查询层与 Agent 暴露的产品 authority；兼容投影不是第二知识库。

## Agent-facing 文档

- 构建领域规则：`skills/domain/uo-codemap-build/SKILL.md`
- 查询领域规则：`skills/domain/uo-codemap-query/SKILL.md`
- Workflow：`skills/workflows/uo-init` / `uo-update` / `uo-query`

## 本地调试

```powershell
python -m uo_init dump path\to\op.arch35.uo --summary
python -m uo_init dump path\to\op.arch35.uo --path queryType KERNEL
```
