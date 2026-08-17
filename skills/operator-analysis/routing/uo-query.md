# UO Query Router

主控先向用户说明将如何查询，再执行。子代理查图用 `capabilities/uo-query/METHOD.md`。
**禁止** `pilot_run` / `acp start uo-query`。禁止仅为问题分类而委派子代理。不要为确认协议调用 `--help` 或 Glob 查找 routing。

`host_driver=False` 只表示 Session Driver **不** auto start/drain，**不等于**没有 Action / METHOD / bundle。

- **简单查询**：一个起始标识符或一种参数形态、一两轮调用能答完。主控直接调用 `acp uo-query`，根据 stdout 作答。不委派子代理，不调用 `kb_lookup`，不调用 `pilot_run` / `acp start`。
- **复杂查询**：用户原话里有 ≥2 个可独立作为首次调用的起始点。主控先说明将委派的子代理数量及各自 FOCUS，然后在同一轮并行调用 `Task(agent=uo-query)`（上限 5）。子代不得 Write、不得自己 finalize。综合只在主控。
- **Delegated Task**（TG/CE 临时问图）：Task 正文即全部，不要另行查找 session `prompt.md`。

缺 `.uo`：产物路径是 `<算子目录>/.ascendc-pilot/<arch>/uo/<op>.<arch>.uo`。
`acp uo-query` 返回 `UO_PRODUCT_REQUIRED` + `ask_question` 时立刻 AskQuestion（选项原样）：先 `/uo-init`，或回退源码作答。禁止 Glob/dir/tree 找产物。

## 如何数独立查询目标

输入：用户原话。输出：直接调用，或 1～N 路 Task（N = 独立起始点数，上限 5）。

从原话抽出能作为**首次调用**的起始点：标识符、`Dim=V`、已知 `--file --line`。
判定：这个起始点能否在**不依赖另一路结论**的情况下单独查完它所对应的那一问？能 → 单独一路。

**必须分别委派**

- 不同层的起始名（Host 函数、Kernel 宏、TilingKey 家族）
- 用户并列的多问，各有不同起始名

**允许收成一路**

- 同一家族的别名：从一个标识符跟卡片 `next` 就能覆盖
- 同一符号的多个子问

**禁止用来合并的理由**（这些只说明主控稍后要综合，不能减少 Task 路数）

- 需要交叉综合 / 设计评审要放在一起看
- 一个子代理更连贯 / 共享上下文
- 共享同一产品场景或 shape

相关 ≠ 单域：业务相关不等于单一查询目标。可独立查询的目标分别委派。综合只在主控。

每一路必须是不同的查询目标；不能把整段问卷复制多份。鉴别项留在主控综合，禁止整段塞进某一路。禁止用无实质内容的确认（例如「是否继续」）代替查询或第二轮委派。

## Task 正文（原样用）

每路只含下面三行，再加本片必要的场景约束。**禁止**写 `--mode`。建议的首次调用必须是四种参数形态之一。

```text
FOCUS: <本路唯一查询目标>
建议的首次调用: acp uo-query --project <算子绝对路径> [--architecture arch35] <标识符或 Dim=V>
本片那一句: <这一路要回答的那一句>
```

四种形态：标识符；`Dim=V`；`--file <path> --line <n>`；无参数索引。

## 硬停止

- **并行**：每轮最多 **5** 个子代理
- **轮次**：第一轮委派 → 综合；图上还能查的独立缺口必须自动开第二轮（路数=缺口数，≤5）
- **方向选择**：多路已有结论但结案条件仍不清时，主控 AskQuestion 给出选项（每项带推荐答案）
- **用户选择继续**某缺口 → 再开一轮 Task（FOCUS=该缺口），最多一次；用户选择停止 → PARTIAL 提交结论
- **主控**：证据已够 → `ANSWERED`。未够且仍是图上可查缺口 → 第二轮。未够且是方向选择 → AskQuestion
- 空 `task_result` 补一轮保留（插件回填子会话最后一条），不要当成图空
- 不调用 `kb_lookup --finalize` 写无人使用的 `answer.yaml`
