---
name: operator-analysis
description: >
  构建、审查与查询 AscendC `.uo` CodeMap：API、Host、TilingKey、TilingData、
  Kernel、模板、宏、编译期变量与跨层证据。首次建图、重建、完整性检查或只读查询时使用。
---

# Operator Analysis（UO CodeMap）

目标：把 AscendC 源码与 architecture 编译成可查询的源码语义图，并据此回答结构问题。

```text
prepare → extract → analyze → resolve → commit → review
                  ↘ query (readonly)
```

## 职责边界

回答：**有什么、在哪里、谁调用、谁读写、受什么 guard 控制、Key/Data/Kernel 如何连接、证据来自哪里。**

不回答：完整 TilingKey 可达性证明、全量 Key 的 SAT/UNSAT、程序引理证明（见 `source-proof` / `testcase-generation`）。

## 构建规则

1. **确定性提取优先**：Clang、source pass、写入与结构审查由 engine 执行。
2. **用户定目标，编译器定范围**：operator + arch 由用户/编排给定；Source Scope 由 entry TU + Build Context + Clang include closure 决定，不经人工文件清单确认。硬失败记 blocker。
3. **关系必须有证据**：CALLS / READS / WRITES / DERIVES 等必须回到源码或 compiler provenance。
4. **不为闭环制造公式**：复杂 Key producer 保留 producer、all-writes、guards、upstream roots 与 source span。
5. **编译期是一等语义**：macro、compile var、template、BuildVariant、ARCH 显式建模。
6. **SHARED 必须进 KB**：`common/` 等 SHARED 进入 ScopeSet 后，Host/Kernel walk 不得再用裸 `op_needle` 过滤掉。
7. **单一产品权威**：`.ascendc-pilot/uo/<op>.<arch>.uo`。

## 查询规则

1. **结构化查询优先**：最窄接口查实体/邻接/路径，再决定是否读源码。
2. **证据关系优先**：节点并存不构成关系。
3. **BuildVariant 隔离**。
4. **源码只做验证**：最小窗口；缺口显式 `PARTIAL` / `UNKNOWN`。
5. **定值写点优先**：TilingData 取值看 `value_defining_sites`。

## 按需参考

| 需要 | 读取 |
|---|---|
| authority / provenance | `references/codemap-authority.md` |
| 结构完整性 | `references/codemap-completeness.md` |
| extract 覆盖 | `references/codemap-extraction.md` |
| 构建踩坑 | `references/codemap-build-gotchas.md` |
| 查询踩坑 | `references/codemap-query-gotchas.md` |
| 共用证据纪律 | `_shared/evidence-quality.md` |
| 踩坑入口 | `references/gotchas.md` |
