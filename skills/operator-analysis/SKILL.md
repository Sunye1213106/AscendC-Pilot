---
name: operator-analysis
description: >
  构建、增量更新与查询 AscendC 算子知识库（`.uo` Operator CodeMap）：API、Host、
  TilingKey 维度、TilingData 字段、Kernel、模板、宏、编译期变量与跨层关系。用户说建立知识库、
  建库、建 CodeMap、索引/分析算子、增量刷新知识库或只读查询时使用。边界：只回答图上有什么；
  覆盖证明走 testcase-generation / source-proof。
---

# 算子分析（UO CodeMap）

薄入口：按任务读对应 METHOD / router / reference，不要一次装载全部。

```text
查询（子代）     → capabilities/uo-query/METHOD.md
路由（主控）     → routing/uo-query.md
构建             → 下方「构建」+ references/codemap-build-gotchas.md
增量更新         → 下方「增量更新」
调查             → capabilities/uo-investigate/METHOD.md
```

OpenCode 查询走插件 `pilot_cli`（command=`uo-query --project …`）。形态见 code-access 不变量。

目标：把 AscendC 源码与 architecture 编译成可查询的源码语义图，作为 TG / CE 的语义接口。

```text
prepare → extract → analyze → commit → verify
   ↘ heal（脚本 include-heal 失败才进入；staging → promote extras）
                  ↘ query（只读）
                  ↘ update（增量；已有 .uo）
                  ↘ investigate（可选；不改 .uo）
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

## 构建（`/uo-init`）

Clang / include / 写入由 engine 执行。输入：算子目录 + architecture。完成条件：`pilot_cli` `uo-query --status-only` 看产物是否就绪，向用户报告 graph 计数与 unresolved 分类。确定性步骤：主控只 `pilot_run`，不开 LLM 子代理。

1. 缺 architecture：Engine 回执已给出唯一 `(算子, architecture)` 时直接使用；否则必须先得到合法 architecture，再启动建库。禁止在没有路径令牌证据时默认 architecture。
2. operator + arch 给定后，Source Scope 以 Clang include closure 为准。
3. 探针失败见 `references/codemap-build-gotchas.md`。
4. 建库结束用 `pilot_cli` `uo-query --status-only`（`grade` / `locate_blocking`）。桶含义见 `references/uo-gaps.md`。

## 增量更新（`/uo-update`）

已有 `.uo` 上按工作区 / diff / PR 变更检测，按层选择性重建（host / kernel / compile / commit）。不是再跑 `/uo-init`。common / 头文件可能扩成全量抽取。没有 `.uo` 时先 `/uo-init`。同样是确定性引擎。

## 查询（`/uo-query`）

TG / CE 缺语义时走这里。简单查询与复杂查询见 `routing/uo-query.md`。

## 按需参考

| 需要 | 读取 |
|---|---|
| UO 产品短地图 | `references/uo-product-map.md` |
| 查询 METHOD | `capabilities/uo-query/METHOD.md` |
| 主控路由 | `routing/uo-query.md` |
| 调查 METHOD | `capabilities/uo-investigate/METHOD.md` |
| include-heal staging | `capabilities/propose-include-heal/METHOD.md` |
| 查询踩坑 | `references/codemap-query-gotchas.md` |
| 场景 hooks | `references/uo-scenario-hooks.md` |
| authority / 完整性 | `references/codemap-authority.md` / `references/codemap-completeness.md` |
