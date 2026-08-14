---
name: operator-analysis
description: >
  构建、刷新与查询 AscendC 算子知识库（`.uo` Operator CodeMap）：API、Host、
  TilingKey、TilingData、Kernel、模板、宏、编译期变量与跨层证据。用户说建立知识库、
  建库、建 CodeMap、索引/分析算子、刷新知识库或只读查询时使用；优先走 uo-init /
  uo-update / uo-query，禁止外部 MCP 通用索引。
---

# Operator Analysis（UO CodeMap）

薄 router：按任务读对应入口，不要一次装载全部 references。

```text
query      → references/uo-product-map.md  + capabilities/uo-query/METHOD.md
build      → 下方「构建」+ references/codemap-build-gotchas.md
investigate → references/semantic-resolution.md
```

目标：把 AscendC 源码与 architecture 编译成可查询的源码语义图，并据此回答结构问题。

```text
prepare → extract → analyze → commit → verify
                  ↘ query (readonly Explore)
                  ↘ investigate (optional; no .uo mutation)
```

## 职责边界

回答：**有什么、在哪里、谁调用、谁读写、受什么 guard 控制、Key/Data/Kernel 如何连接、证据来自哪里。**

不回答：完整 TilingKey 可达性证明、全量 Key 的 SAT/UNSAT、程序引理证明（见 `source-proof` / `testcase-generation`）。

## 查询（Explore）

1. 先读 **`references/uo-product-map.md`**（任务 → mode、权威分层、claim 层级）。
2. 按 METHOD 做 **claim-driven bounded exploration**：够 claim 就停；**无**固定证据槽表。
3. 结构化 `acp uo-query` 优先；`source_span` / packing site 的 path:line **足够引用**，不为行号而 Read。
4. 交付 `kb-answer-v1`（Explorer 不写文件）；未找到用 `UNKNOWN` + `reason_code=NOT_FOUND_IN_SCOPE`。
5. **复杂多 claim**：Primary 拆 2–4 个窄 `Task(actor=uo-query)` 并行，再合成确切答案；简单题单 Task。
6. 高置信：`acp inspect evidence-window --project … --path … --lines A-B` 取 sha + snippet。

## 构建

Clang / include / 写入由 engine 执行。Agent 不改假编译环境、不补 prelude、不手改 `-I`。

1. **缺 architecture 时先扫再问**：`acp scan-architectures --project <算子目录>`，阅读 `layout` / 选项，再 AskQuestion（选项原样）。禁止仓根 Glob `arch*` 或翻 cmake 考古。
2. **用户定目标，编译器定范围**：operator + arch 给定后，Source Scope 以 Clang include closure 为准。不经人工确认文件清单，也不接受「跳过验证」。
3. **探针失败**：prepare 会自动补头文件搜索路径。仍失败则 `acp doctor`，禁止用测试开关绕过。见 `references/codemap-build-gotchas.md`。
4. **关系必须有证据**：CALLS / READS / WRITES / DERIVES 等必须回到源码或 compiler provenance。
5. **不为闭环制造公式**：复杂 Key producer 保留 producer、写点、guards 与 source span。
6. **编译期是一等语义**：macro、compile var、template、BuildVariant、ARCH 显式建模。
7. **SHARED 必须进图**：`common/` 等进入范围后，不得按算子名把共享头丢掉。
8. **单一产品权威**：`.ascendc-pilot/<arch>/uo/<op>.<arch>.uo`。
9. **保留 unresolved**：证不全的记入 `unresolved.yaml`，不得用 LLM 补进正式 `.uo`。调查用 `/uo-investigate`。评价建库看 `uo/checks/quality.yaml` 的 `grade` / `locate_blocking`，不要用 unresolved 总条数。
10. **过期投影**：engine 回退到正式 `.uo`；不要把无法验证 freshness 当成 fresh。见 `references/uo-product-map.md`。

## 按需参考

| 需要 | 读取 |
|---|---|
| **UO 产品短地图（query 默认）** | `references/uo-product-map.md` |
| TilingKey / Data / Kernel / Template / Buffer / Gaps | `references/uo-key.md` 等域文档 |
| **uo-query METHOD** | `capabilities/uo-query/METHOD.md` |
| authority / provenance | `references/codemap-authority.md` |
| 结构完整性 | `references/codemap-completeness.md` |
| extract 覆盖 | `references/codemap-extraction.md` |
| 构建踩坑 | `references/codemap-build-gotchas.md` |
| 查询踩坑 | `references/codemap-query-gotchas.md` |
| unresolved 调查 | `references/semantic-resolution.md` |
| 共用证据纪律 | `references/evidence-quality.md` |
| SplitAxis 示例（non-normative） | `examples/uo-query-splitaxis/` |
| 踩坑入口 | `references/gotchas.md` |
| 查询如何喂精度/性能场景 | `references/uo-scenario-hooks.md` |
