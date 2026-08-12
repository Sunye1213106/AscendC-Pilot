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
build      → 下方「构建」+ references/codemap-build-gotchas.md / uo-build 段
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

1. 先读 **`references/uo-product-map.md`**（权威分层 + claim 层级 + 何时 fallback）。
2. 按 METHOD 做 **claim-driven bounded exploration**：够 claim 就停；**无**固定证据槽表。
3. 结构化 `acp uo-query` 优先；`source_span` / packing site 的 path:line **足够引用**，不为行号而 Read。
4. 交付 `kb-answer-v1`；未找到用 `UNKNOWN` + `reason_code=NOT_FOUND_IN_SCOPE`。

## 构建

1. **确定性提取优先**：Clang、source pass、写入与结构校验由 engine 执行。
2. **用户定目标，编译器定范围**：operator + arch 由用户/编排给定；Source Scope 以 Clang include closure 为权威（regex 仅 bootstrap）；`clang_scope_status=complete` 才能过 validate。不经人工文件清单确认，也不接受 `decision=yes` 绕过。探针 / include 失败时：对照算子仓官方编译文件修正 `build_context.yaml`（见 `references/codemap-build-gotchas.md`）。
3. **关系必须有证据**：CALLS / READS / WRITES / DERIVES 等必须回到源码或 compiler provenance。
4. **不为闭环制造公式**：复杂 Key producer 保留 producer、all-writes、guards、upstream roots 与 source span。
5. **编译期是一等语义**：macro、compile var、template、BuildVariant、ARCH 显式建模。
6. **SHARED 必须进 KB**：`common/` 等 SHARED 进入 ScopeSet 后，Host/Kernel walk 不得再用裸 `op_needle` 过滤掉。
7. **单一产品权威**：`.ascendc-pilot/uo/<op>.<arch>.uo`。
8. **保留 unresolved**：deterministic pass 无法闭合的语义 residual 写入 `unresolved.yaml`；**不得**默认用 LLM 补进 canonical `.uo`。部分 incomplete UO 合法（`semantic_completeness=partial`）。调查用 `/uo-investigate`。
9. **Projection freshness**：写入 `.uo` 前先 drop 未证边，再重投影并 stamp provenance（digest + counts + builder）；详见 map 与 `docs/architecture/artifacts-and-authority.md`。

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
