# UO Query Router — 主控可见路由（不是子代 playbook）

主控先对人说出路由，再动手。子代查图用 `capabilities/uo-query/METHOD.md`。
**禁止** `pilot_run` / `acp start uo-query`。不要为空转「问题路由」开子代理。

缺 `.uo`：产物路径是 `<算子目录>/.ascendc-pilot/<arch>/uo/<op>.<arch>.uo`。
`acp uo-query` 返回 `UO_PRODUCT_REQUIRED` + `ask_question` 时立刻 AskQuestion（选项原样）：先 `/uo-init`，或回退源码作答。禁止 Glob/dir/tree 找产物。

## 编译器权威

若 `host_step.tasks` ≥ 2：同一轮**原样**并行派发每条 `tasks[i].task_prompt_stub`，全部返回后按各 Task 原生全文综合。不要自己再切一套。

## 启发式（仅当编译器给出 0 或 1 片）

看 **独立证据空间**，不是 METHOD 表行数，也不是「症状像不像一单故障」。

拆成并行 Task（`agent=uo-query`）当且仅当同时成立：

1. 子问题可以在相对独立的证据空间搜索
2. 子代不需要共享大量 evolving state
3. 主控能根据各 Task 全文综合结案

否则主控自查（短问：一名字 / 一 mode / 一两跳，一次 `acp uo-query --mode` stdout 即完成）或只派 1 个 Task。

**相关 ≠ 单域**：业务上相关不能成为合并搜索空间的理由。禁止「一条因果链 / 一个 agent 更连贯」把可独立探索的空间收成 1 路。禁止把整题丢给一个子代理再转述。

每个深问 Task 只带本片 FOCUS + `FIRST_QUERY: acp uo-query --mode <本片唯一先查> --project <绝对路径>` + 本片那一句。

## 未闭合

子代 PARTIAL / 未闭合 / 互相矛盾 / 没用 CodeMap 时，再开一轮 Task（FOCUS=缺口），直到结案或明确 PARTIAL。不要问「要不要继续」。禁止把深问降成主控连查收工。
