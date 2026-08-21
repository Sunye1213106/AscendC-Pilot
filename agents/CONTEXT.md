# Context（agent 常驻词表）

模型常驻的跨工作流术语表。完整人类定义见 `docs/reference/glossary.md`。

仅当 CE / grill 发现**跨 session 易误用的新术语**时更新本表。
算子事实以 CodeMap 为准；编排规则不写在这里。

## 核心术语

**CodeMap / `.uo`** — `/uo-init` 按「算子目录 + architecture」建立的二进制源码语义图。不是通用 call graph。UO 查询、TG、CE 的语义底座。

**digest** — session binding 中的 `canonical_graph_digest`。`fresh` 表示当前 digest 匹配，不表示“最近建过库”。

**刷新 `.uo`** — `/uo-update`。基于工作区 / diff / PR 检测变更并增量重建受影响层；common / 头文件变更可退化为全量抽取。不是重新 `/uo-init`。

**查询** — `/uo-query` Command。调查：一路直接 `pilot_cli`，多路 fanout 子代理隔离主控窗口。不是 Host workflow。形态见 code-access 不变量。拆路见 intent-reasoning。

**简单查询** — 单一起始符号或参数形态，通常一两轮查询可闭合。
**复杂查询** — 含多个可独立查询的目标。

**`{slug}_plan.md`** — `/ce-plan` 确认后的用户变更计划，位于 `ce/plan/{slug}_plan.md`。输入是用户需求 + UO 语义，不是 PR。包含实现分析、todo 和测试内容。

**ce-apply** — 仅按计划中未完成 `- [ ]` 修改代码，也可按 TG 的 `test_harness_gap` 修改测试脚本。不查图、不做 review。

**两轴 review** — `/ce-review` 同时检查：

* **Spec**：是否完成计划；无计划时按现有 diff 推断粗粒度意图。
* **Standards**：是否符合仓规范。

review 结论只留在会话，可作为 **Planning Context**，但不是 `plan.md` 或 cases。

**Planning Context** — `/tg-plan` 用来确定测试范围的上下文。可来自当前会话、`/ce-review`、`{slug}_plan.md` 的测试内容、用户明确范围、`session_handoff.md`，或已有 `tg/init.yaml` + `/uo-query`。没有明确范围，不启动 `/tg-plan`。

**clone 事实** — `workflow=auto` 成功回执中的 worktree 与 changed-files。若路径唯一确定 `(算子, architecture)`，后续 `pilot_run` 沿用该绑定。

**Open** — TG `worklog.md` 顶部 `open:` 中尚未闭合的 obligation id。CE 不维护该账本。

**replay / derived** — TG solve 的两类可判定依据，均须 root 到 CSV/XLS 列或 `init.yaml` 已声明变量：

* `replay`：Host tiling 动态回放，验证 key / TD / OP_CHECK / 分支。
* `derived`：由当前输入与代码逻辑直接推出。

`Replay reject ≠ E`。

**init.yaml** — `/tg-init` 生成的测试前置契约。绑定测试输入与 UO 变量，并声明 golden、精度、性能等条件；无现成测试仓时可基于 `/uo-query` 建立 `kind=default_input` 控制面。不是 cases。

**plan.md** — `/tg-plan` 生成的测试义务计划：Planning Context + `init.yaml` → 有限覆盖目标及精度 / 性能要求。不是可执行用例。

缺少脚本、列或生成器时记录 `test_harness_gap`，交 `/ce-apply`；TG 不修改算子仓。

**cases 表** — `/tg-solve` 根据 plan 构造并经 Host replay / 引理闭合后的可执行用例。不是 `plan.md`。存在未落地 `test_harness_gap` 时不得 start。

**worklog.md** — TG 求解账本；临时草稿仅放 `runs/`。

**session_handoff.md** — `/handoff` 生成的会话交接摘要，位于 architecture 根目录。只引用已有产物与下一步 slash，不复制计划全文。

**quality.yaml** — `.uo` 建库质量以 `grade` / `locate_blocking` 为准，不以 unresolved 数量直接判断。

## 同名不可互换

跨 UO / TG / CE 传递时必须保留所属域，禁止仅按名字合并。

| 词             | UO                                    | TG                                | CE                                    |
| ------------- | ------------------------------------- | --------------------------------- | ------------------------------------- |
| `obligation`  | `key_field_obligations`（legacy）       | `plan.md` 中的测试义务                  | 计划中的“测试内容”散文；CE 不写 TG obligation YAML |
| `fingerprint` | graph histogram digest                | `init.yaml.uo_digest`             | git revision；fresh 与 handle digest 比较 |
| `kind`        | `EntityKind`，如 `FIELD ≠ TILING_FIELD` | column mapping kind               | 不作为 risk / workflow 路由账本              |
| `TilingKey`   | CodeMap 中的维度实体                        | 合法域来自 `product_uo.legal_key_rows` | 查询锚点；不等于默认全量覆盖                        |
