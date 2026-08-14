---
name: operator-analysis
description: >
  构建、刷新与查询 AscendC 算子知识库（`.uo` Operator CodeMap）：API、Host、
  TilingKey、TilingData、Kernel、模板、宏、编译期变量与跨层证据。用户说建立知识库、
  建库、建 CodeMap、索引/分析算子、刷新知识库或只读查询时使用。建库走 uo-init /
  uo-update；只读查询由本 skill 自己路由（短问 `acp uo-query`，深问再开子代理），
  禁止外部 MCP 通用索引。
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
                  ↘ query (readonly)
                  ↘ investigate (optional; no .uo mutation)
```

## 职责边界

回答：**有什么、在哪里、谁调用、谁读写、受什么 guard 控制、Key/Data/Kernel 如何连接、证据来自哪里。**

不回答：完整 TilingKey 可达性证明、全量 Key 的 SAT/UNSAT、程序引理证明（见 `source-proof` / `testcase-generation`）。

## 查询

主控用 skill **自己路由**，不要空转「问题路由」、也不要一上来就开子代理。

1. 看一眼 **`references/uo-product-map.md`**，大体判断查什么（`tiling_key` / `field` / `kernel_branch` / `locate` / `impact` / …）。
2. **缺 `.uo` 时不要找**：产物路径是确定的（`<算子目录>/.ascendc-pilot/<arch>/uo/<op>.<arch>.uo`）。`acp uo-query` / `pilot_run` 会返回 `UO_PRODUCT_REQUIRED` + `ask_question`。立刻 AskQuestion，选项原样使用：先 `/uo-init`，或回退到源码作答。禁止 Glob/dir/tree 找 `.uo`，禁止猜 `--op-name`。选 source 后只读算子源码作答，不要再调 `acp uo-query`。
3. **问得短、一两跳能答**：自己跑 `acp uo-query --mode`，**stdout JSON 就是答案**，直接对人说。禁止再 Glob/Read `answer.yaml`。
4. **问得深、要沿图走很多跳**：`pilot_run`（workflow=uo-query）会**立刻**返回 `dispatch_subagent`。马上用 OpenCode **原生 Task**（agent=`uo-query`，prompt=`task_prompt_stub` 原样）。用户可点 Task 卡片跳进子会话看思考。不要空等隐藏的内部 session。METHOD 见 `capabilities/uo-query/METHOD.md`。
5. 图证据不够再开最小源码窗。高置信才 `acp inspect evidence-window`。
6. 未找到用 `UNKNOWN`。查询结束把 `host_step.answer_zh` 或 CLI stdout 说给人听，不要只说「完成」，不要去翻 yaml。`host_step.kind=answer_from_source` 时按源码作答。

## 构建

Clang / include / 写入由 engine 执行。Agent 不改假编译环境、不补 prelude、不手改 `-I`。

1. **缺 architecture 时先扫再问**：`acp scan-architectures --project <算子目录>`，阅读 `layout` / 选项，再 AskQuestion（选项原样）。禁止仓根 Glob `arch*` 或翻 cmake 考古。启动用 Host 工具 `pilot_run`，带 project 与 architecture。**不要传 `force_new`**（那是删除重开，会 wipe `.uo`）。失败时不要翻 Pilot 源码。
2. **用户定目标，编译器定范围**：operator + arch 给定后，Source Scope 以 Clang include closure 为准。不经人工确认文件清单，也不接受「跳过验证」。
3. **探针失败**：prepare 会自动补头文件搜索路径。仍失败则 `acp doctor`，禁止用测试开关绕过。见 `references/codemap-build-gotchas.md`。
4. **关系必须有证据**：CALLS / READS / WRITES / DERIVES 等必须回到源码或 compiler provenance。
5. **不为闭环制造公式**：复杂 Key producer 保留 producer、写点、guards 与 source span。
6. **编译期是一等语义**：macro、compile var、template、BuildVariant、ARCH 显式建模。
7. **SHARED 必须进图**：`common/` 等进入范围后，不得按算子名把共享头丢掉。
8. **单一产品权威**：`.ascendc-pilot/<arch>/uo/<op>.<arch>.uo`。
9. **保留 unresolved**：证不全的记入 `unresolved.yaml`，不得用 LLM 补进正式 `.uo`。调查用 `/uo-investigate`。评价建库看 `uo/checks/quality.yaml` 的 `grade` / `locate_blocking`，不要用 unresolved 总条数。
10. **过期投影**：engine 回退到正式 `.uo`；不要把无法验证 freshness 当成 fresh。见 `references/uo-product-map.md`。
11. **建库结束**：Read `host_step.quality_path`（`.ascendc-pilot/<arch>/uo/checks/quality.yaml`，禁止无 arch 的 `.ascendc-pilot/uo/`）。`graph` 计数 + `unresolved` 桶；要名单再读同树 `uo/ir/unresolved.yaml`。对人总结节点/关系/未闭合及原因；不要打开 `.uo` 二进制，不要只说「完成」。桶含义见 `references/uo-gaps.md`。

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
