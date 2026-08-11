# AscendC-Pilot

AscendC-Pilot 是面向 **AscendC 算子开发的 AI Agent Harness 与代码知识基础设施**。

它通过 Clang 和 CANN 编译环境分析 AscendC 源码，构建面向 Host、Tiling、TilingKey、TilingData、Kernel 模板和运行时分支的 **Operator CodeMap**，并在此基础上支持测试覆盖、代码审查和影响分析。

当前主要能力：

* **UO · Understand Operator**：构建和查询 Operator CodeMap
* **TG · Testcase Generation**：根据 CodeMap 建立 TilingKey / runtime branch 覆盖闭环
* **CE · Code Engineering**：基于跨 Host / Tiling / Kernel 关系进行代码审查和影响分析

```text
AscendC Source → UO → Operator CodeMap → TG → Coverage
                                  └────→ CE → Review / Impact
```

> 项目当前处于 **active / experimental** 阶段。

---

# 安装

要求 Python 3.10+。

```bash
pip install -r requirements.txt

pip install -e ./pilot
pip install -e ./engines/common
pip install -e ./engines/understand-operator
pip install -e "./engines/testcase-generation[ml]"
pip install -e ./engines/code-engineering
```

安装完成后可以检查基础运行环境：

```bash
acp doctor
```

完整 UO 分析还需要 Clang、CANN headers 和目标算子源码；TG Host Replay 需要对应的 CANN、Host UT 和 C++ 构建环境。

详细环境要求见：

[Installation](docs/getting-started/installation.md)

## 接入 OpenCode

Windows：

```powershell
./install.ps1 opencode
```

Linux：

```bash
./install.sh opencode
```

也支持 Cursor 和 Codex：

```powershell
./install.ps1 cursor
./install.ps1 codex
```

安装脚本只负责将 AscendC-Pilot 接入对应 Host，正常使用时不需要反复运行。

---

# 快速开始

AscendC-Pilot 应在 **目标 AscendC 算子仓库** 中使用，而不是在 AscendC-Pilot 自身仓库中运行。

OpenCode 中进入目标算子仓后，通过 **Tab** 切换到 AscendC-Pilot 对应的 Agent，即可直接使用自然语言描述任务。

例如：

```text
帮我为 flash_attention_score_grad 的 arch35 建立 CodeMap
```

Agent 会根据任务进入对应的 UO workflow。

你也可以直接使用命令：

```text
/uo-init
```

CodeMap 建立完成后，所有算子产物都会保存在：

```text
<operator-repo>/.ascendc-pilot/
```

---

# 常用用法

## 建立 CodeMap

可以直接告诉 Agent：

```text
帮我为 sparse_flash_attention_grad 的 arch35 建立 CodeMap
```

或者：

```text
分析当前算子的 arch35，并建立 UO CodeMap
```

对应命令：

```text
/uo-init
```

当源码发生修改后：

```text
/uo-update
```

用于更新已有 CodeMap，而不是重新从头建立全部知识。

---

## 查询算子

CodeMap 建立后，可以直接询问算子实现。

```text
/uo-query
```

常见问题例如：

```text
这个 TilingKey 是怎么决定的？
```

```text
TilingKey 100000 对应哪个 Kernel 模板实例？
```

```text
这个 TilingData 字段在 Host 哪里赋值？
```

```text
这个 Kernel 分支由哪个 Host 条件控制？
```

```text
输入 shape 是怎样影响最终 TilingKey 的？
```

```text
这个模板参数是从哪里来的？
```

```text
某个宏或者编译期变量最终影响了哪些 Kernel 路径？
```

```text
这个算子的 Host → TilingData → Kernel 数据流是什么？
```

```text
某个 LocalTensor / GlobalTensor 在 Kernel 中经过了哪些操作？
```

```text
CopyIn、Compute、CopyOut 之间的 buffer 和同步关系是什么？
```

对于 CodeMap 中无法确定的关系，也可以直接问：

```text
当前还有哪些 unresolved gap？
```

或者：

```text
调查这个 unresolved 为什么没有闭合
```

---

# 生成测试

CodeMap 建立完成后，可以开始 TG workflow：

```text
/tg-init
/tg-plan
/tg-solve
```

也可以直接描述目标：

```text
帮我为这个算子建立 TilingKey 全覆盖测试
```

或者：

```text
检查当前还有哪些 TilingKey 没有被 testcase 覆盖
```

```text
为这些未覆盖的 TilingKey 生成候选输入并进行 replay
```

TG 会从 CodeMap 中建立 coverage obligation，通过约束搜索、候选生成和 Host Replay 验证实际行为。

对于同一个 TilingKey 内部仍存在运行时分支的情况，也可以继续分析：

```text
检查这个 TilingKey 下还有哪些 runtime branch 没覆盖
```

覆盖目标只有在获得实际 replay evidence，或者经过审查的不可达证明后才会关闭。

---

# 代码审查与影响分析

CE 当前主要提供代码审查能力：

```text
/ce-review
```

例如：

```text
分析我当前这个 PR 会影响哪些 Host、Tiling 和 Kernel 路径
```

```text
检查这次修改有没有遗漏对应的 Kernel 分支
```

```text
这个 Host 条件修改后会影响哪些 TilingKey？
```

```text
分析当前 diff 对 TilingData 和 Kernel 行为的影响
```

CE 会尽量复用已有 CodeMap，而不是重新扫描整个算子仓库。

---

# 常用命令

| 命令                | 用途                                |
| ----------------- | --------------------------------- |
| `/uo-init`        | 为当前算子和架构建立 CodeMap                |
| `/uo-update`      | 源码修改后更新 CodeMap                   |
| `/uo-query`       | 查询 Host / Tiling / Kernel 语义关系    |
| `/uo-investigate` | 调查 unresolved gap                 |
| `/tg-init`        | 根据 UO 初始化测试覆盖目标                   |
| `/tg-plan`        | 生成 testcase / coverage plan       |
| `/tg-solve`       | 搜索、replay 并关闭 coverage obligation |
| `/ce-review`      | 进行代码审查和影响分析                       |

通常不需要记住全部命令。直接告诉 Agent 你想完成什么即可，例如：

```text
帮我建立这个算子的 CodeMap
```

```text
告诉我这个 TilingKey 从输入到 Kernel 是怎么走的
```

```text
帮我把当前没有覆盖的 TilingKey 补齐
```

```text
分析我当前修改会影响哪些执行路径
```

---

# UO / TG / CE

### UO

UO 使用目标 BuildVariant、Clang 和 CANN 编译环境解析实际源码，并构建跨 Host、Tiling 和 Kernel 的 Operator CodeMap。

它不仅记录函数和文件关系，还关注 AscendC 中更重要的：

* 宏和编译期条件
* 模板参数和模板实例
* TilingKey
* TilingData
* Kernel branch
* buffer / register / synchronization
* Host → Kernel 数据关系

无法可靠确定的信息会保留为 unresolved，不会通过模型猜测补齐。

### TG

TG 将 CodeMap 中的 TilingKey 和 runtime branch 转换为测试覆盖目标，再通过候选生成和 Host Replay 获得真实运行证据。

```text
CodeMap → Coverage Obligation → Candidate → Replay → Evidence → Closure
```

### CE

CE 基于 CodeMap 分析代码变化在 Host、Tiling 和 Kernel 之间的传播，用于代码审查和影响分析。

---

# 项目结构

```text
adapters/          OpenCode / Cursor / Codex 接入
agents/            Agent identity
engines/           UO / TG / CE 引擎
evals/             Agent、Skill 和 Harness eval
pilot/             Workflow、Action、Gate、State、CLI
prompts/           Task prompts
skills/            Agent skills
schemas/           Extension schemas
scripts/           Generator 与 validation tools
tests/             Tests
docs/              Documentation
```

---

# 文档

第一次使用建议阅读：

[Installation](docs/getting-started/installation.md) → [Quick Start](docs/getting-started/quickstart.md)

进一步了解模块：

* [UO](docs/modules/uo.md)
* [TG](docs/modules/tg.md)
* [CE](docs/modules/ce.md)

了解内部设计：

* [Architecture](docs/architecture/overview.md)
* [Agent Runtime](docs/architecture/agent-runtime.md)
* [Artifacts and Authority](docs/architecture/artifacts-and-authority.md)

开发和扩展：

* [Extension Guide](docs/development/extending.md)
* [Repository Layout](docs/reference/repository-layout.md)

完整文档入口：

[docs/README.md](docs/README.md)

---

# 开发

运行测试：

```bash
pytest
```

检查文档：

```bash
python scripts/check_docs.py
```

修改 Workflow、Agent 或 Reference 定义后：

```bash
python scripts/generate_reference_docs.py
```

---

# License

当前仓库尚未声明 License。
