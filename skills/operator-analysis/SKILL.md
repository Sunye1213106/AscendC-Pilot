---
name: operator-analysis
description: >
  构建、刷新与查询 AscendC 算子知识库（`.uo` Operator CodeMap）：API、Host、
  TilingKey 维度、TilingData 字段、Kernel、模板、宏、编译期变量与跨层关系。用户说建立知识库、
  建库、建 CodeMap、索引/分析算子、刷新知识库或只读查询时使用。建库走 uo-init /
  uo-update；只读查询由本 skill 做**可见 LLM 路由**（先对人说出自查或几个子代理，
  禁止 `pilot_run`），禁止外部 MCP 通用索引。
---

# Operator Analysis（UO CodeMap）

薄 router：按任务读对应入口，不要一次装载全部 references。

```text
query       → references/uo-product-map.md  + capabilities/uo-query/METHOD.md
build       → 下方「构建」+ references/codemap-build-gotchas.md
investigate → references/semantic-resolution.md
```

目标：把 AscendC 源码与 architecture 编译成可查询的源码语义图。

```text
prepare → extract → analyze → commit → verify
                  ↘ query (readonly)
                  ↘ investigate (optional; no .uo mutation)
```

## 职责边界

回答：**有什么、在哪里、谁调用、谁读写、受什么 guard 控制、Key/Data/Kernel 如何连接、证据来自哪里。**

覆盖证明、SAT/UNSAT、程序引理 → `source-proof` / `testcase-generation`。

## 查询（可见 LLM 路由）

查询**不是** workflow。完成条件：对人说出路由后再动手；答案来自 `acp uo-query` stdout 或 `uo-query` Task 全文。

1. 看一眼 **`references/uo-product-map.md`**，判断查什么（`tiling_key` / `field` / `kernel_launch` / `kernel_branch` / `locate` / `impact` / …）。
2. **缺 `.uo`**：产物路径是 `<算子目录>/.ascendc-pilot/<arch>/uo/<op>.<arch>.uo`。`acp uo-query` 返回 `UO_PRODUCT_REQUIRED` + `ask_question` 时立刻 AskQuestion，选项原样：先 `/uo-init`，或回退到源码作答。选 source 后只读算子源码作答。
3. **先对人说出路由**（必须出现在对用户的消息里，不能只藏在思考里）：
   - 水平：短问（一名字、一 mode、一两跳）| 深问单域（METHOD **一行**）| 深问多域（METHOD **≥2 行** / 画图+变体 / 多个结案条件）
   - 谁查：主控自查 | 1 个 Task | N 个并行 Task
   - 为什么：一句话（写 METHOD 行名，不要写「相关所以合并」）
4. **短问**（唯一自查路径）：一名字、一 mode、一两跳，**一次** `acp uo-query --project <算子绝对路径> --mode` 的 stdout 就能答完。
5. **深问**：METHOD 表打中 **≥2 行**，或同一问里有多个独立结案条件 → **同一轮并行**多个 Task（`agent=uo-query`）。按独立搜索空间拆（METHOD 一行一路），不要按「像不像一单故障」拆。禁止把整题丢给一个子代理再转述。相关 ≠ 单域。禁止「一条因果链 / 一个 agent 更连贯」收成 1 路。每个 Task 只带本片 FOCUS + `FIRST_QUERY: acp uo-query --mode <本片唯一先查> --project <绝对路径>` + 本片那一句；不要塞整段用户原问。全部返回后按各 Task 全文**综合**。METHOD 见 `capabilities/uo-query/METHOD.md`。
6. **未闭合再派 Task**：子代 PARTIAL / 未闭合 / 互相矛盾 / 没用 CodeMap 时，再开一轮 Task（FOCUS=缺口），直到结案或明确 PARTIAL 并列出缺的 span。高置信才 `acp inspect evidence-window`。未找到用 `UNKNOWN`。把 CLI stdout 或子代全文说给人听。

Hard guardrails（与上面完成条件配对）：禁止 `pilot_run`；缺 `.uo` 时用 AskQuestion 而不是 Glob/dir/tree 找产物；短问读 stdout 而不是 Glob/Read `answer.yaml`；深问用 Task 而不是主控连查；相关 ≠ 单域；禁止把整题丢给一个子代理；每个深问 Task 写 `FIRST_QUERY`；真正查图的 Task 才派，空转「只做分类」的子代理不派。

## 构建

Clang / include / 写入由 engine 执行。完成条件：`host_step.done` 后 Read `host_step.quality_path`，对人总结 graph 计数与 unresolved 桶。

已有 `.uo`、无活动写锁时再发 `/uo-init` 会得到 `UO_ALREADY_READY`。选「去查询」后停止 Host drive，等人提问。只有要推倒重来才选「删除重开」。测查询直接贴题。

1. **缺 architecture 时先扫再问**：`acp scan-architectures --project <算子目录>`，阅读 `layout` / 选项，再 AskQuestion（选项原样）。启动用 Host 工具 `pilot_run`，带 project 与 architecture。`force_new` 只在用户明确要求删除重开时使用。
2. **用户定目标，编译器定范围**：operator + arch 给定后，Source Scope 以 Clang include closure 为准。
3. **探针失败**：prepare 会自动补头文件搜索路径。仍失败则 `acp doctor`。见 `references/codemap-build-gotchas.md`。
4. **关系必须有证据**：CALLS / READS / WRITES / DERIVES 回到源码或 compiler provenance。
5. **复杂 Key producer** 保留 producer、写点、guards 与 source span。
6. **编译期是一等语义**：macro、compile var、template、BuildVariant、ARCH 显式建模。
7. **SHARED 进图**：`common/` 等进入范围后进入 CodeMap。
8. **单一产品权威**：`.ascendc-pilot/<arch>/uo/<op>.<arch>.uo`。
9. **保留 unresolved**：证不全的记入 `unresolved.yaml`。调查用 `/uo-investigate`。评价建库看 `uo/checks/quality.yaml` 的 `grade` / `locate_blocking`。
10. **过期投影**：engine 回退到正式 `.uo`。见 `references/uo-product-map.md`。
11. **建库结束**：Read `host_step.quality_path`（`.ascendc-pilot/<arch>/uo/checks/quality.yaml`）。`graph` 计数 + `unresolved` 桶；要名单再读同树 `uo/ir/unresolved.yaml`。对人总结节点/关系/未闭合及原因。桶含义见 `references/uo-gaps.md`。

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
