---
name: operator-analysis
description: >
  构建、刷新与查询 AscendC 算子知识库（`.uo` Operator CodeMap）：API、Host、
  TilingKey、TilingData、Kernel、模板、宏、编译期变量与跨层证据。用户说建立知识库、
  建库、建 CodeMap、索引/分析算子、刷新知识库或只读查询时使用。建库走 uo-init /
  uo-update；只读查询由本 skill 做**可见 LLM 路由**（先对人说出自查或几个子代理，
  禁止 `pilot_run`），禁止外部 MCP 通用索引。
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

## 查询（可见 LLM 路由，禁止 Host 润）

查询**不是** workflow。禁止 `pilot_run`、禁止空转「问题路由」子代理。切片由你分类，不以 Host 派发清单为准。

1. 看一眼 **`references/uo-product-map.md`**，判断查什么（`tiling_key` / `field` / `kernel_launch` / `kernel_branch` / `locate` / `impact` / …）。
2. **缺 `.uo` 时不要找**：产物路径是确定的（`<算子目录>/.ascendc-pilot/<arch>/uo/<op>.<arch>.uo`）。`acp uo-query` 会返回 `UO_PRODUCT_REQUIRED` + `ask_question`。立刻 AskQuestion，选项原样：先 `/uo-init`，或回退到源码作答。禁止 Glob/dir/tree 找 `.uo`。选 source 后只读算子源码作答。
3. **先对人说出路由**（必须出现在对用户的消息里，不能只藏在思考里），再动手：
   - 水平：短问（一名字、一 mode、一两跳）| 深问单域 | 深问多域（互不相关的层/路径/症状）
   - 谁查：主控自查 | 1 个 Task | N 个并行 Task
   - 为什么：一句话
4. **短问**：当前会话 `acp uo-query --project <算子绝对路径> --mode`，**stdout 就是答案**，对人说。禁止 Glob/Read `answer.yaml`。
5. **深问**：同一轮原生 Task（`agent=uo-query`）。每个 prompt 写清 FOCUS + 用户原问 + 绝对 `--project`。点 Task 卡片可看子代思考。N≥2 时全部返回后 **按各 Task 全文综合**：禁止只转述某一个，禁止发明子代理没引用的事实。METHOD 见 `capabilities/uo-query/METHOD.md`。
6. 图证据不够再开最小源码窗。高置信才 `acp inspect evidence-window`。未找到用 `UNKNOWN`。把 CLI stdout 或子代全文说给人听，不要只说「完成」。

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
