# UO Query Router

主控先对人说出路由，再动手。子代查图用 `capabilities/uo-query/METHOD.md`。
**禁止** `pilot_run` / `acp start uo-query`。不要为空转「问题路由」开子代理。

`host_driver=False` 只表示 Session Driver **不** auto start/drain，**不等于**没有 Action / METHOD / bundle。

- **短问**：主控自己 `acp uo-query --mode`，stdout 即答案。无 prepare / Task / finalize。
- **深问**：`acp uo-query --mode compile` 只出候选（`first_query` / `slices` / 探活后的 CLI）。**Primary LLM 才是分配器**：按独立 FOCUS 写 1～5 路 Task，每路互斥 FOCUS + 一行 `FIRST_QUERY`（必须来自候选或 METHOD 真 mode）。子代不得 Write、不得自己 finalize。
- **Delegated Task**（TG/CE 临时问图）：Task 正文即全部，不要 hunt session `prompt.md`。

缺 `.uo`：产物路径是 `<算子目录>/.ascendc-pilot/<arch>/uo/<op>.<arch>.uo`。
`acp uo-query` 返回 `UO_PRODUCT_REQUIRED` + `ask_question` 时立刻 AskQuestion（选项原样）：先 `/uo-init`，或回退源码作答。禁止 Glob/dir/tree 找产物。

## 编译器只出候选

`acp uo-query --mode compile --project <算子绝对路径> --query <用户原话>`。

- `first_query` / `slices` 是候选，**不是** Task 派发器
- 0/1 片只表示默认 1 路，不禁止 LLM 在有多条独立 FIRST_QUERY 时再拆
- 探活失败的 mode 不得写进 FIRST_QUERY
- 若 `host_step.tasks` 给出多片 stub：优先用这些候选；可**合并**共享同一 FIRST_QUERY 的片；不可再手写 `symbols` / `fields` 问卷

## Primary LLM 分配（每轮最多 5 路）

输入：用户原话 + compile JSON（含探活）。输出：1 或 N 路，每路 **互斥 FOCUS + 一行 FIRST_QUERY**。

- 每一路必须是不同 mode 或不同 ident；不能多份同一批头文件的长问卷
- 鉴别项（「是 VF 慢还是分核错」）留在 Primary 综合，禁止整段塞进某一路
- compile 只有 1 刀：默认 1 路；有几条独立 FIRST_QUERY 就拆几路，最多 5
- 不凑满、不超 5。上限对齐 `MAX_SLICES=5`
- 「相关 ≠ 单域」不是默认拆两路：业务相关不能把可独立的 FIRST_QUERY 收成 1 路，但拆几路由 Primary 按独立 FOCUS 决定，不是固定 2
- 短问仍主控自查。禁止问「要不要继续」

每个深问 Task 只带本片 FOCUS + `FIRST_QUERY: acp uo-query --mode <本片唯一先查> --project <绝对路径>` + 本片那一句。

## 硬停止（脚本 / 插件执行，LLM 不得突破）

- **并行**：同一轮最多 **5** 个子代理
- **轮次**：第 1 轮派发 → 综合；仅当仍有独立缺口（PARTIAL / 空结果 / 互相矛盾）才开第 2 轮；第 2 轮路数 = 实际独立缺口数（0～5）；**没有第 3 轮**
- **缺口**：没有缺口就停；有 3 个互斥缺口就开 3 路，不要压成 1 路，也不要虚构第 6 路
- **子代**：FIRST_QUERY 一刀；空则 hint 再一刀；然后必须交回。禁止读完整 SEL 表当覆盖
- **主控**：第 2 轮结束或证据已够 → `ANSWERED` 或 `PARTIAL`，不再开 Task、不问「要不要继续」
- 空 `task_result` 补一轮保留（插件回填子会话最后一条），不要当成图空
