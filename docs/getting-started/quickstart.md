# Quick Start

本页假设 AscendC-Pilot 已完成安装。

所有操作都应在**目标 AscendC 算子仓或算子目录**中进行，而不是在 AscendC-Pilot 自身仓库中。

## 1. 打开目标算子

例如要分析 `flash_attention_score_grad` 的 `arch35`，先在 OpenCode 中打开对应算子源码。

通过 **Tab** 切换到：

```text
AscendC-Pilot
```

然后直接描述任务：

```text
帮我为 flash_attention_score_grad 的 arch35 建立 CodeMap。
```

通常只需要明确目标算子和 architecture。UO 会根据实际构建上下文继续发现源码范围以及依赖的 common/header 文件。

也可以直接输入 workflow 命令：

```text
/uo-init
```

> OpenCode 安装会生成原生 `/uo-init`、`/tg-init`、`/tg-plan`、`/tg-solve`、`/ce-review` 等 command，并固定由 `ascendc-pilot` Primary 接管。它们不是 shell 命令；自然语言入口仍可通过 workflow Skill 发现。

---

## 2. 建立 Operator CodeMap

`/uo-init` 会运行完整的 UO pipeline：

```text
operator + architecture → source scope → Clang CompilerFacts
                        → semantic analysis → CodeMap → verify
```

其中 Source Scope 不局限于当前目录。只要公共文件属于当前 BuildVariant 的真实 include 或依赖关系，就会进入分析范围。

UO 的 `prepare / extract / analyze / commit / verify` 都是 deterministic Action。ACP 会把它们绑定到 `deterministic-uo-engine`；Primary 不会把这个 engine identity 当成 OpenCode Task agent。Host 可通过 `acp run-action auto` 连续执行确定性步骤并自动推进 phase，直到需要 LLM/人工交互或 workflow 完成。

成功后，正式 CodeMap 位于：

```text
<operator-repo>/.ascendc-pilot/uo/<op_name>.<arch>.uo
```

如果初始化失败，不建议直接继续 TG。可以先查看：

```bash
acp status
acp inspect-failure
```

如果只是外部环境修复，例如 CANN 或 Clang 路径补齐，可以使用：

```bash
acp retry-after-environment-fix
```

---

## 3. 查询算子

CodeMap 建立后，可以直接向 AscendC-Pilot 提问，不需要重新让 Agent 阅读整个算子源码。

例如：

```text
这个算子的 TilingKey 是怎么决定的？
```

```text
TilingKey 100000 对应哪个 Kernel 模板？
```

```text
这个 TilingData 字段在 Host 哪里写入，Kernel 哪里读取？
```

```text
输入 shape 是怎样影响 TilingKey 的？
```

```text
这个模板参数来自哪里？
```

```text
这个宏或者编译期变量最终影响了哪些 Kernel 路径？
```

```text
这个 Kernel 分支由哪个 Host 条件控制？
```

```text
帮我梳理 Host → TilingKey → TilingData → Kernel 的完整关系。
```

Kernel 侧也可以查询：

```text
这个 LocalTensor / Buffer 最终追到哪个 AscendC storage root？
```

```text
这个对象中间经过了哪些项目 wrapper？它们在哪里定义？
```

```text
这个 Kernel method 通过哪些 helper 最终调用了哪个 AscendC/CANN API？
当前还有哪些对象或调用无法追到 root？为什么？
```

对应显式入口为：

```text
/uo-query
```

如果需要调查 CodeMap 中尚未闭合的问题：

```text
当前还有哪些 unresolved？
```

或者：

```text
帮我调查这个 unresolved 为什么没有闭合。
```

对应：

```text
/uo-investigate
```

`/uo-query` 和 `/uo-investigate` 都不会直接修改正式 CodeMap。

---

## 4. 源码修改后更新 CodeMap

如果目标算子源码已经发生变化，不需要重新手工分析影响范围。

运行：

```text
/uo-update
```

或者直接告诉 Agent：

```text
我刚修改了这个算子，更新一下 CodeMap。
```

UO 会根据 source fingerprint 和已有 CodeMap 判断变化，并受控刷新相关结果。

TG 和 CE 应使用更新后的 CodeMap，而不是在旧 UO 基础上继续工作。

---

## 5. 建立测试覆盖

CodeMap 就绪后，可以开始 TG。

标准流程：

```text
/tg-init → /tg-plan → /tg-solve
```

也可以直接告诉 Agent：

```text
帮我为这个算子建立 TilingKey 全覆盖测试。
```

TG 的 deterministic Action 统一绑定 `deterministic-tg-engine`；`init_audit`、lemma producer/referee 和人工确认仍保持独立 LLM/Primary 边界。`acp run-action auto` 只会吃掉 deterministic 段，遇到这些交互 Action 会返回准确的 `actor_id` 和下一条 `acp run-action <action>`，不会把 engine 当 subagent，也不会跳过 referee/gate。

### `/tg-init`

从 UO CodeMap 建立 coverage contract，检查当前 CodeMap、TilingKey binding 和输入条件是否满足 TG 前置要求。

### `/tg-plan`

根据目标覆盖层级生成计划。

当前主要有两类覆盖：

**L2：TilingKey coverage**

```text
每个目标 TilingKey → replay 可达
                 或 → 有证据证明不可达
```

**L3：runtime branch coverage**

```text
固定已可达 TilingKey → 改变运行时输入
                     → replay
                     → 观察同 key 下的 branch outcome
```

### `/tg-solve`

根据计划寻找 candidate，并通过 Host Replay 验证。每轮 Replay 后立刻做 Round Analysis，不把引理证明留到最后：

```text
CodeMap → Obligation
  → Round: Candidate → Host Replay → Round Analysis
        ├ expected growth → lemma on rejects → E
        └ unexpected growth → directed construct from R + source
  → Closure when Open=∅
```

候选输入、SAT 结果或者模型判断本身都不算 coverage。

一个义务只有两种正式关闭方式：

```text
Replay confirmed
或
Reviewed exclusion proof
```

因此可以继续直接询问：

```text
当前还有哪些 TilingKey 没覆盖？
```

```text
为什么这个 TilingKey 一直没有 candidate？
```

```text
为剩余 TilingKey 继续生成候选并 replay。
```

```text
这个 TilingKey 已经可达，继续检查里面的 runtime branch。
```

TG 产物位于：

```text
<operator-repo>/.ascendc-pilot/<arch>/tg/
```

---

## 6. 审查代码修改

已有 CodeMap 后，可以直接分析当前代码修改：

```text
/ce-review
```

或者自然语言：

```text
帮我检查当前修改会影响哪些 Host、Tiling 和 Kernel 路径。
```

```text
这个 PR 修改了 Host 条件，会影响哪些 TilingKey？
```

```text
检查当前修改有没有遗漏对应的 Kernel 分支。
```

```text
分析这个 TilingData 字段变化最终会影响哪些 Kernel 行为。
```

CE 的 `code_review` 明确派发到 `ce-reviewer` subagent；Primary 只负责 workflow 控制，不代写 review 产物。CE 会尽量沿已有 CodeMap 做跨层影响分析，而不是重新从头构建另一套源码模型。

当前 CE 主要提供 review 和 impact analysis。

---

## 常用入口

| 入口                    | 用途                                  |
| --------------------- | ----------------------------------- |
| `/uo-init`            | 第一次建立 Operator CodeMap              |
| `/uo-update`          | 源码变化后更新 CodeMap                     |
| `/uo-query`           | 查询 Host / Tiling / Kernel 关系        |
| `/uo-investigate`     | 调查 unresolved                       |
| `/tg-init`            | 建立 TG contract 和 coverage domain    |
| `/tg-plan`            | 生成覆盖计划                              |
| `/tg-solve`           | 轮次：构造/Replay/分析（轮内引理或定向构造）至闭环 |
| `/ce-review`          | 代码审查与影响分析                           |
| `acp run-action auto` | 自动执行连续 deterministic Action，交互边界自动停下 |
| `acp doctor`          | 检查基础 Pilot 安装                       |
| `acp status`          | 查看当前 Workflow 状态                    |
| `acp next`            | 查看下一步可执行 Action                     |
| `acp inspect-failure` | 查看结构化失败原因                           |

正常使用时不需要记住所有底层 `acp` 命令。优先直接向 `AscendC-Pilot` 描述目标，或使用原生 Slash Command；Primary 只选择 workflow，后续 Action/engine 顺序由 ACP 决定。

---

## 一次完整使用示例

第一次分析：

```text
帮我为 sparse_flash_attention_grad 的 arch35 建立 CodeMap。
```

完成后：

```text
告诉我 TilingKey 的生成逻辑，以及每个 TilingKey 对应的 Kernel 模板。
```

继续：

```text
帮我建立 TilingKey 全覆盖测试。
```

完整覆盖控制面按以下顺序运行：

```text
/uo-init → /tg-init → /tg-plan → /tg-solve
```

其中每个 workflow 内的 deterministic 段由 ACP 自动执行；只有审查、lemma producer/referee 或明确人工确认才回到 LLM/Primary。

完成 L2 后：

```text
继续检查可达 TilingKey 内部的 runtime branch 覆盖。
```

修改代码后：

```text
我修改了当前算子，更新 CodeMap，并检查这次修改影响哪些执行路径。
```

这就是 AscendC-Pilot 当前的主要工作链：

```text
Source → UO CodeMap → Query / TG / CE
```

所有算子级状态和产物统一保存在：

```text
<operator-repo>/.ascendc-pilot/
```

如果 UO 已经过期，应先 `/uo-update`；不要让 TG 或 CE 基于旧 CodeMap 继续产生结论。
