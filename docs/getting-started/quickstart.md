# Quick Start

本页假设 AscendC-Pilot 已完成安装。自然语言任务可以只给 **PR URL**（系统会自行获取代码）；显式 Slash 工作流仍应在**目标算子目录**中启动。

内部机制（Lease、Engine、Producer/Referee、Host Session Driver、Task Harness）见 [Agent Runtime](../architecture/agent-runtime.md)；覆盖算法见 [TG](../modules/tg.md)；各 workflow 阶段图见 [工作流流程图](../architecture/workflows.md)。

> 每执行一步任务时，Pilot 会发一张短时通行证（Action Lease），限定「谁能读写哪些路径」；本步结束或失败后作废。OpenCode 上优先走 Host 工具 `pilot_run`（传输环路由 Host 持有）。详情见 Runtime 文档。
>
> 工具怎么选、失败怎么查，见 [ACP 工具使用](acp-tools.md)。

## 0. 两条入口

```text
自然语言     →  先 Todo（有什么/要什么），再按格 pilot_run；获取代码才 workflow="auto"
Slash 专家   →  /uo-init /tg-plan /ce-review … 直接跑对应工作流
查询         →  仍走 pilot_cli / uo-query，不进 Harness
```

自然语言路径上，用户不必知道模块名，也不必手串 `/uo-init → /tg-*`。专家路径上，现有 workflow **全部保留**。

主示例：在 OpenCode 里对 `AscendC-Pilot` 说：

```text
帮我给这个 PR 生成针对 case
https://github.com/<org>/<repo>/pull/<id>
```

主控应先写出 Todo（获取代码 / uo-init / tg-init，再视产物缺口写消费格），再执行。系统会：在当前 OpenCode 打开目录下 **新建文件夹** clone PR exact-head（空打开目录只做 clone 锚点，**不**落下 `.ascendc-pilot`）→ Engine 回执列出 changed-files；路径令牌唯一时直接使用该 `(算子, architecture)`，多个才 AskQuestion（禁止在没有证据时默认 arch35）→ 建立或复用 CodeMap。**全部 init 先于任何消费**：缺 `.uo` 先 `/uo-init`；最终产物是用例且缺 `tg/init.yaml` 先 `/tg-init`（意图没有仓外测试脚本路径时第一步问人；仓内 `tests/` 未确认不得当 harness；主控不得把仓内 UT 填进 `test_script_root` 代答），再按产物缺口消费。禁止把 `/ce-review` 插在未完成的 init 之前。最终产物是用例、审查不是交付物时，用 `/uo-query` 作 Planning Context，不要把 `/ce-review` 推理成依赖。有 Planning Context 后再 `/tg-plan` / `/tg-solve`。需主控派 Task 的格串行。凭证失败会问人，这不是 UX 失败。显式 slash 只跑该格。不要按个别措辞选 slash。

## 1. 打开目标算子

在 OpenCode（或已接入的 Host）中打开算子源码，通过 **Tab** 切换到：

```text
AscendC-Pilot
```

然后直接描述任务，或使用 Slash Command。

> **Slash Command**： 聊天框里以 `/` 开头的快捷入口（如 `/uo-init`），用来显式启动某个工作流。
> 由 Host（OpenCode / Cursor 等）注册，**不是**终端里的 shell 命令；安装后会出现在补全列表里，并由 `ascendc-pilot` 主控接管。
> 也可以不敲 `/`，直接用自然语言描述目标。

Architecture 在 **建立 CodeMap（`/uo-init` / `/uo-update`）** 时从算子仓 `op_host/arch*` / `op_kernel/arch*` 中选择，必须同时有算子路径与 architecture。Engine clone 已唯一钉死的 architecture 直接使用。否则从发现的架构中选择，不会在没有证据时默认。Agent 侧优先用 clone 回执与 `pilot_cli` `scan-architectures --project <算子目录>`；唯一 pin 在选项内时不要再 AskQuestion。不要 Glob 仓根或翻 cmake 猜架构。

第一次启动不要传 `force_new` / `--force-new`。那是「删除重开」逃生口，会按策略 wipe 已有 `.uo`。已有未完成 run 时由 Host AskQuestion 选「继续上次」或「删除重开」，不要为了「确保能跑」先 wipe。

`acp doctor` 是环境预检（Python 包、CANN、Host 契约），**不需要** `--architecture`，也不会创建 `.ascendc-pilot/<arch>/`。建树由 Host `pilot_run` 启动工作流时完成。

TG / CE / 查询 **不以源码目录另选架构**：以已有 `.uo` 为准。没有 CodeMap 就直接跑 `/tg-init` 等，会提示先 `/uo-init`。

> OpenCode 安装会生成原生 `/uo-init`、`/tg-init`、`/tg-plan`、`/tg-solve`、`/ce-plan`、`/ce-apply`、`/ce-review`、`/handoff` 等 command，并固定由 `ascendc-pilot` Primary 接管。

---

## 2. 建立 Operator CodeMap

用自然语言或 Slash 启动均可，但都要带上算子目录与架构：

```text
帮我为 flash_attention_score_grad 的 arch35 建立 CodeMap。
```

```text
/uo-init --project <算子目录> --architecture arch35
```

`/uo-init` 在真实编译上下文中建立 CodeMap：

```text
operator + architecture → source scope → Clang CompilerFacts
                        → semantic analysis → CodeMap → verify
```

五个阶段均为 deterministic execution，不需要 LLM 生成 canonical CodeMap。

成功后正式产物位于：

```text
<operator-repo>/.ascendc-pilot/<arch>/uo/<op_name>.<arch>.uo
```

失败时先看：

```text
pilot_cli command=`status --project <算子目录>`
pilot_cli command=`inspect-failure --project <算子目录>`
```

外部环境修好后，Agent 用 `pilot_cli retry-after-environment-fix`；人类终端用 `python -m ascendc_pilot retry-after-environment-fix`。不要在 UO 失败时直接开始 TG。

---

## 3. 查询算子

CodeMap 建立后可直接提问，不必让 Agent 重读整个算子：

```text
这个算子里 SparseMode / Layout 这些维是怎么进最终 TilingKey 的？Host 侧从哪几个输入推出来？
某个 TilingData 字段（比如 blockDim 或 tiling 结构里的成员）Host 谁写、Kernel 谁读，中间隔了几层封装？
某个 Kernel 分支（比如走不同 template / 不同计算路径）到底由哪些 Host 条件或 TilingKey 约束触发？
LocalTensor / Buffer 最终落到哪类 AscendC 存储（GM / UB / L1 等），中间有没有项目自己的 wrapper？
```

显式入口：`/uo-query --project <算子目录>`。调查 unresolved：`/uo-investigate --project <算子目录>`。二者都不修改正式 CodeMap。

查询由主控做**可见 LLM 路由**（禁止 `pilot_run`）：先读 [`uo-product-map`](../../skills/operator-analysis/references/uo-product-map.md)，向用户说明将直接调用还是委派。简单查询主控直接调用 `pilot_cli` `uo-query`；复杂查询同一轮 `Task(agent=uo-query)`。形态见 code-access 不变量。调查 unresolved：`/uo-investigate`（仍走 Host `pilot_run`）。

默认 `/uo-init` 为 `UO_INIT_PROFILE=fast`（未设置即 fast：1 个 kernel dtype，keypath，fold / API clang 关闭）。全量 dtype / fold / API clang 需显式 `UO_INIT_PROFILE=full`。已有 `.uo` 要拿到新的分支 span / 全 dtype 事实，需要完整重跑 init，而不是增量猜测。

---

## 4. 源码修改后更新

```text
/uo-update --project <算子目录> --architecture arch35
```

或：

```text
我刚修改了这个算子，更新一下 CodeMap。
```

TG 和 CE 应使用更新后的 CodeMap，不要基于过期 UO 继续工作。

---

## 5. 建立测试覆盖

TG 消费已有 CodeMap：架构与算子身份以 `.uo` 为准。若尚未建库，会返回 `UO_PRODUCT_REQUIRED`，请先完成 §2。

**产品目标（推荐）**：说「全量 / 全覆盖 / tilingkey case / 建立 TilingKey 全覆盖测试」时，Pilot 会写入
`.ascendc-pilot/control/user_goal.yaml`，并按三步串联（每步用自然语言说明意图与下一步）：

1. **写出 init.yaml**（`/tg-init`）→ 主控裁判放行后直接结束，不再问是否进入规划  
2. **写出 plan.md**（`/tg-plan`）→ 向用户批准是否开始求解  
3. **写出 worklog.md + cases 表**（`/tg-solve`）

也可分步 Slash：

```text
/tg-init --project <算子目录>
/tg-plan --project <算子目录>
/tg-solve --project <算子目录>
```

（若该算子下有多个 `.uo`，再补 `--architecture`，选项来自已有产物，而不是重新扫 `arch*`。）

或：

```text
帮我为这个算子建立 TilingKey 全覆盖测试。
```

对用户可见说明会交代「目标 / 刚完成 / 下一步或请你决定」；不会用内部字段名当作唯一解释。

`/tg-solve` 按已批准 `plan.md` 构造脚本可读的 cases 表，跑 Host tiling 回放（无 NPU），把每条 case 写进 `worklog.md`，直到文首 `open: []`。详细算法见 [TG](../modules/tg.md)。无 WSL/CANN 时 `replay_round` 失败停住，不进入 analyze。

义务关闭方式：Host replay 命中，或 derived 公式成立。`Replay reject ≠ E`。

产物位于 `<operator-repo>/.ascendc-pilot/<arch>/tg/`：`init.yaml`、`plan.md`、`worklog.md`、`cases.csv`/`xls`/`xlsx`。

---

## 6. 改码或审查修改

自己有需求、还没改码：

```text
/ce-plan --project <算子目录>
```

问清范围后写出 `ce/plan/{slug}_plan.md`，再 `/ce-apply` 按未完成 todo 改码。验证不在 CE，接着 `/tg-plan`。

已有 PR 或工作区 diff、只要**审查**时（须在对应算子仓、该 arch 已有 `.uo`；HTTPS 回退需 `GITCODE_TOKEN` / `GITHUB_TOKEN`）：

```text
/ce-review --project <算子目录>
```

自然语言要生成用例且带 PR URL：先 Todo 再按格执行。获取代码走 Engine clone；`auto` 回执已唯一钉死 `(算子, architecture)` 时直接用于后续格，不要单独一条「确定算子/架构」Todo。全部 init 在前，再按产物缺口消费：最终产物是用例、审查不是交付物 → `/uo-query` 再 `/tg-plan` / `/tg-solve`；审查才是交付物 → `/ce-review`（若同时还要用例，审查结论作 Planning Context，不再加 `/uo-query`）。勾 Todo 后再 `pilot_run` 下一格，不要再调 `auto` 做 intake。`/tg-init` 缺测试仓会问人。需主控派 Task 的格串行。不要按个别措辞选 slash。


CE 沿已有 CodeMap 读图，不重新建立源码权威。语义只走 `uo-query`（形态见 code-access 不变量）。审查是双轴对话，不落盘。plan 不以 PR 为输入；review 不以设计改码为职责。旧 `/ce-intent` `/ce-impact` `/ce-verify` `/ce-handoff` 已删除。

---

## 常用入口

| 入口 | 用途 |
| --- | --- |
| 自然语言 + PR URL | 先 Todo 再执行。clone 仍是 Engine；主控 `git log` + `scan-architectures` 选算子/arch；`/tg-init` 缺测试仓会问人 |
| `/uo-init` | 第一次建立 Operator CodeMap（需算子路径 + architecture） |
| `/uo-update` | 源码变化后更新 CodeMap（需算子路径 + architecture） |
| `/uo-query` | 只读提问：简单查询直接 `pilot_cli` `uo-query`，复杂查询同一轮派子代理（需已有 `.uo`；不走 `pilot_run`） |
| `/uo-investigate` | 调查 unresolved（需已有 `.uo`） |
| `/tg-init` / `/tg-plan` / `/tg-solve` | 建立覆盖并闭环（需已有 `.uo`；架构以 UO 为准） |
| `/ce-plan` | 自己有需求：grill 并写出 `{slug}_plan.md` |
| `/ce-apply` | 按当前计划未完成 todo 改码（需已有 `.uo`） |
| `/ce-review` | 已有 diff / PR：只读双轴审查，不落盘 |
| `/handoff` | 会话交接：写 `session_handoff.md` |
| `python -m ascendc_pilot doctor` / `doctor --host opencode` | 环境预检；后者校验 Host Session Driver / plugin 契约 |
| `pilot_cli`：`inspect` / `ro-search` / `next` / `inspect-failure` / `status` | 证据窗、只读搜索、下一步、失败卡 |
| `pilot_cli`：`scan-architectures` | 快速扫描算子 `op_host`/`op_kernel` 布局与 `arch*` 选项 |
| `pilot_run`（OpenCode 工具） | Host Session Driver：自然语言第一次 `workflow=auto`；`workflow=<id>` 跑现有工作流 |
| 插件 `pilot_cli`（OpenCode 工具） | 查询与诊断；`command` 不要 `--help`，不要 `start`/`run-action auto`。用法见 [ACP 工具使用](acp-tools.md) |

正常使用时优先向 `AscendC-Pilot` 描述目标，或使用带参数的 Slash Command。

---

## 一次完整使用示例

自然语言（不必知道模块名）：

```text
帮我给这个 PR 生成针对 case
https://github.com/<org>/<repo>/pull/<id>
```

专家 Slash 仍可用：

```text
帮我为 sparse_flash_attention_grad 的 arch35 建立 CodeMap。
告诉我 TilingKey 的生成逻辑，以及每个 TilingKey 对应的 Kernel 模板。
/tg-plan
/ce-review
```

自己有需求时走 `/ce-plan` → `/ce-apply`；已有 diff 且只要审查走 `/ce-review`。验证走 `/tg-plan` 或自然语言生成 case。

主链：

```text
Source → UO CodeMap → Query / TG / CE
```

产物统一保存在 `<operator-repo>/.ascendc-pilot/`。UO 过期时先 `/uo-update`。
