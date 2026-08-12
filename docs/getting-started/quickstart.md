# Quick Start

本页假设 AscendC-Pilot 已完成安装。所有操作都应在**目标 AscendC 算子仓或算子目录**中进行，而不是在 AscendC-Pilot 自身仓库中。

内部机制（Lease、Engine、Producer/Referee）见 [Agent Runtime](../architecture/agent-runtime.md)；覆盖算法见 [TG](../modules/tg.md)。

## 1. 打开目标算子

在 OpenCode（或已接入的 Host）中打开算子源码，通过 **Tab** 切换到：

```text
AscendC-Pilot
```

直接描述任务，或使用 Slash Command。Architecture 由仓内 `op_host/arch*` / `op_kernel/arch*` 发现；多架构时需选择，也可在任务中显式指定。

```text
帮我为 flash_attention_score_grad 的 arch35 建立 CodeMap。
```

```text
/uo-init
```

> OpenCode 安装会生成原生 `/uo-init`、`/tg-init`、`/tg-plan`、`/tg-solve`、`/ce-review` 等 command，并固定由 `ascendc-pilot` Primary 接管。它们不是 shell 命令。

---

## 2. 建立 Operator CodeMap

`/uo-init` 在真实编译上下文中建立 CodeMap：

```text
operator + architecture → source scope → Clang CompilerFacts
                        → semantic analysis → CodeMap → verify
```

UO 五个阶段均由 deterministic execution 执行，不需要 LLM 生成 canonical CodeMap。

成功后正式产物位于：

```text
<operator-repo>/.ascendc-pilot/uo/<op_name>.<arch>.uo
```

失败时先看：

```bash
acp status
acp inspect-failure
```

外部环境修复后可用 `acp retry-after-environment-fix`。不要在 UO 失败时直接开始 TG。

---

## 3. 查询算子

CodeMap 建立后可直接提问，不必让 Agent 重读整个算子：

```text
这个算子的 TilingKey 是怎么决定的？
这个 TilingData 字段在 Host 哪里写入，Kernel 哪里读取？
这个 Kernel 分支由哪个 Host 条件控制？
这个 LocalTensor / Buffer 最终追到哪个 AscendC storage root？
```

显式入口：`/uo-query`。调查 unresolved：`/uo-investigate`。二者都不修改正式 CodeMap。

---

## 4. 源码修改后更新

```text
/uo-update
```

或：

```text
我刚修改了这个算子，更新一下 CodeMap。
```

TG 和 CE 应使用更新后的 CodeMap，不要基于过期 UO 继续工作。

---

## 5. 建立测试覆盖

```text
/tg-init → /tg-plan → /tg-solve
```

或：

```text
帮我为这个算子建立 TilingKey 全覆盖测试。
```

`/tg-solve` 会生成候选输入并运行 Host Replay，根据实际结果继续搜索或证明剩余目标不可达，直到覆盖义务关闭或遇到需要人工处理的问题。详细算法见 [TG](../modules/tg.md)。

义务只有两种正式关闭方式：Replay confirmed，或 Reviewed exclusion proof。

产物位于 `<operator-repo>/.ascendc-pilot/<arch>/tg/`。

---

## 6. 审查代码修改

```text
/ce-review
```

或：

```text
帮我检查当前修改会影响哪些 Host、Tiling 和 Kernel 路径。
```

CE 沿已有 CodeMap 做跨层影响分析，不重新建立源码权威。

---

## 常用入口

| 入口 | 用途 |
| --- | --- |
| `/uo-init` | 第一次建立 Operator CodeMap |
| `/uo-update` | 源码变化后更新 CodeMap |
| `/uo-query` | 查询 Host / Tiling / Kernel 关系 |
| `/uo-investigate` | 调查 unresolved |
| `/tg-init` / `/tg-plan` / `/tg-solve` | 建立覆盖并闭环 |
| `/ce-review` | 代码审查与影响分析 |
| `acp doctor` / `status` / `next` / `inspect-failure` | 环境与状态诊断 |

正常使用时优先向 `AscendC-Pilot` 描述目标或使用 Slash Command。

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
