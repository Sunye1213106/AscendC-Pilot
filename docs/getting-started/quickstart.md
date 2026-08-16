# Quick Start

本页假设 AscendC-Pilot 已完成安装。所有操作都应在**目标 AscendC 算子仓或算子目录**中进行，而不是在 AscendC-Pilot 自身仓库中。

内部机制（Lease、Engine、Producer/Referee、Host Session Driver）见 [Agent Runtime](../architecture/agent-runtime.md)；覆盖算法见 [TG](../modules/tg.md)；各 workflow 阶段图见 [工作流流程图](../architecture/workflows.md)。

> 每执行一步任务时，Pilot 会发一张短时通行证（Action Lease），限定「谁能读写哪些路径」；本步结束或失败后作废。OpenCode 上优先走 Host 工具 `pilot_run`（传输环路由 Host 持有），不必让主控手搓 `acp start` / `auto` / `finalize`。详情见 Runtime 文档。

## 1. 打开目标算子

在 OpenCode（或已接入的 Host）中打开算子源码，通过 **Tab** 切换到：

```text
AscendC-Pilot
```

然后直接描述任务，或使用 Slash Command。

> **Slash Command**： 聊天框里以 `/` 开头的快捷入口（如 `/uo-init`），用来显式启动某个工作流。
> 由 Host（OpenCode / Cursor 等）注册，**不是**终端里的 shell 命令；安装后会出现在补全列表里，并由 `ascendc-pilot` 主控接管。
> 也可以不敲 `/`，直接用自然语言描述目标。

Architecture 在 **建立 CodeMap（`/uo-init` / `/uo-update`）** 时从算子仓 `op_host/arch*` / `op_kernel/arch*` 中选择，必须同时有算子路径与 architecture；缺一会要求从发现的架构中选择，不会静默默认。Agent 侧优先跑 `acp scan-architectures --project <算子目录>` 读目录摘要与选项，再 AskQuestion——不要 Glob 仓根或翻 cmake 猜架构。

第一次启动不要传 `force_new` / `--force-new`。那是「删除重开」逃生口，会按策略 wipe 已有 `.uo`。已有未完成 run 时由 Host AskQuestion 选「继续上次」或「删除重开」，不要为了「确保能跑」先 wipe。

`acp doctor` 是环境预检（Python 包、CANN、Host 契约），**不需要** `--architecture`，也不会创建 `.ascendc-pilot/<arch>/`。建树是 `acp start` 的事。

TG / CE / 查询 **不以源码目录另选架构**：以已有 `.uo` 为准。没有 CodeMap 就直接跑 `/tg-init` 等，会提示先 `/uo-init`。

> OpenCode 安装会生成原生 `/uo-init`、`/tg-init`、`/tg-plan`、`/tg-solve`、`/ce-review` 等 command，并固定由 `ascendc-pilot` Primary 接管。

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

```bash
acp status --project <算子目录>
acp inspect-failure --project <算子目录>
```

外部环境修好后可用 `acp retry-after-environment-fix`。不要在 UO 失败时直接开始 TG。

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

查询由主控做**可见 LLM 路由**（禁止 `pilot_run`）：先读 [`uo-product-map`](../../skills/operator-analysis/references/uo-product-map.md)，对人说出「短问自查 / 几个子代理」。短问自己 `acp uo-query --mode`；深问同一轮 `Task(agent=uo-query)`，禁止把深问改成主控连查。常用 mode：`tiling_key` / `tiling_data` / `kernel_branch` / `buffer` / `locate` / `kernel_api` / `impact` / `gaps`。调查 unresolved：`/uo-investigate`（仍走 Host `pilot_run`）。

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
`.ascendc-pilot/control/user_goal.yaml`，并按三步串联（每步用人话说明意图与下一步）：

1. **建立覆盖合同**（`/tg-init`）→ 人话确认是否进入规划  
2. **规划测试义务**（`/tg-plan`）→ 人话批准是否开始求解  
3. **求解并生成用例**（`/tg-solve`）

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

对人可见说明会交代「目标 / 刚完成 / 下一步或请你决定」；不会用内部字段名当作唯一解释。

`/tg-solve` 会生成候选输入并运行 Host Replay，根据实际结果继续搜索或证明剩余目标不可达，直到覆盖义务关闭或遇到需要人工处理的问题。详细算法见 [TG](../modules/tg.md)。

义务只有两种正式关闭方式：Replay confirmed，或 Reviewed exclusion proof。

产物位于 `<operator-repo>/.ascendc-pilot/<arch>/tg/`。

---

## 6. 审查代码修改

```text
/ce-review --project <算子目录>
```

或：

```text
帮我检查当前修改会影响哪些 Host、Tiling 和 Kernel 路径。
```

CE 沿已有 CodeMap 做跨层影响分析，不重新建立源码权威。三种入口：快速看风险、文件检视、PR 检视（PR 需要已有 diff）。无 diff 要定位改点用 `/ce-intent`；有 diff 要验证义务用 `/ce-impact` → `/ce-verify`。

---

## 常用入口

| 入口 | 用途 |
| --- | --- |
| `/uo-init` | 第一次建立 Operator CodeMap（需算子路径 + architecture） |
| `/uo-update` | 源码变化后更新 CodeMap（需算子路径 + architecture） |
| `/uo-query` | 只读提问：主控可见路由后自查或派 `uo-query` 子代理（需已有 `.uo`；不走 `pilot_run`） |
| `/uo-investigate` | 调查 unresolved（需已有 `.uo`） |
| `/tg-init` / `/tg-plan` / `/tg-solve` | 建立覆盖并闭环（需已有 `.uo`；架构以 UO 为准） |
| `/ce-review` | 只读检视（快速 / 文件 / PR；需已有 `.uo`） |
| `/ce-intent` | 无 diff：定位改哪里 |
| `/ce-impact` / `/ce-verify` | 有 diff：影响切片与验证证书 |
| `acp doctor` / `doctor --host opencode` | 环境预检；后者校验 Host Session Driver / plugin 契约 |
| `acp status` / `next` / `inspect-failure` | 状态与失败诊断 |
| `acp scan-architectures` | 快速扫描算子 `op_host`/`op_kernel` 布局与 `arch*` 选项 |
| `pilot_run`（OpenCode 工具） | Host Session Driver：启动并驱动 workflow |

正常使用时优先向 `AscendC-Pilot` 描述目标，或使用带参数的 Slash Command。

---

## 一次完整使用示例

```text
帮我为 sparse_flash_attention_grad 的 arch35 建立 CodeMap。
告诉我 TilingKey 的生成逻辑，以及每个 TilingKey 对应的 Kernel 模板。
帮我建立 TilingKey 全覆盖测试。
我修改了当前算子，更新 CodeMap，并检查这次修改影响哪些执行路径。
```

主链：

```text
Source → UO CodeMap → Query / TG / CE
```

产物统一保存在 `<operator-repo>/.ascendc-pilot/`。UO 过期时先 `/uo-update`。
