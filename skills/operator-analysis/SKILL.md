---
name: operator-analysis
description: >
  构建、刷新与查询 AscendC 算子知识库（`.uo` Operator CodeMap）：API、Host、
  TilingKey 维度、TilingData 字段、Kernel、模板、宏、编译期变量与跨层关系。用户说建立知识库、
  建库、建 CodeMap、索引/分析算子、刷新知识库或只读查询时使用。边界：只回答图上有什么；
  覆盖证明走 testcase-generation / source-proof。
---

# Operator Analysis（UO CodeMap）

薄入口：按任务读对应 METHOD / router / reference，不要一次装载全部。

```text
query  (child)  → capabilities/uo-query/METHOD.md
route  (primary)→ routing/uo-query.md
build           → 下方「构建」+ references/codemap-build-gotchas.md
investigate     → capabilities/uo-investigate/METHOD.md
```

OpenCode 查询走插件 `pilot_cli`（command=`uo-query --project …`，不要前导 acp、不要 `--mode`）。禁止找 `acp.exe`，禁止名为 `acp` 的工具。

目标：把 AscendC 源码与 architecture 编译成可查询的源码语义图。

```text
prepare → extract → analyze → commit → verify
                  ↘ query (readonly)
                  ↘ investigate (optional; no .uo mutation)
```

## 职责边界

回答：**有什么、在哪里、谁调用、谁读写、受什么 guard 控制、Key/Data/Kernel 如何连接、证据来自哪里。**

覆盖证明、SAT/UNSAT、程序引理 → `source-proof` / `testcase-generation`。

## 领域不变量

- CodeMap 是结构事实权威。关系（CALLS / READS / WRITES / DERIVES）必须回到源码或 compiler provenance。
- partial graph 不能证明 absence。
- 编译期实体（macro、compile var、template、BuildVariant、ARCH）是一等语义。
- 单一产品路径：`<算子目录>/.ascendc-pilot/<arch>/uo/<op>.<arch>.uo`。
- 证不全的记入 `unresolved.yaml`；调查用 `/uo-investigate`，不要把 LLM 推断 merge 进 `.uo`。

## 构建

Clang / include / 写入由 engine 执行。完成条件：读 `uo/checks/quality.yaml`，向用户报告 graph 计数与 unresolved 分类。

1. 缺 architecture：必须先得到合法 architecture，再启动建库。
2. operator + arch 给定后，Source Scope 以 Clang include closure 为准。
3. 探针失败见 `references/codemap-build-gotchas.md`。
4. 建库结束读 `uo/checks/quality.yaml`（`grade` / `locate_blocking`）。桶含义见 `references/uo-gaps.md`。

## 按需参考

| 需要 | 读取 |
|---|---|
| UO 产品短地图 | `references/uo-product-map.md` |
| 查询 METHOD | `capabilities/uo-query/METHOD.md` |
| 主控路由 | `routing/uo-query.md` |
| 调查 METHOD | `capabilities/uo-investigate/METHOD.md` |
| 查询踩坑 | `references/codemap-query-gotchas.md` |
| 场景 hooks | `references/uo-scenario-hooks.md` |
| authority / 完整性 | `references/codemap-authority.md` / `references/codemap-completeness.md` |
| 共用证据纪律 | `references/evidence-quality.md` |
