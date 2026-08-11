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
python -m pip install -r requirements.txt
```

安装完成后可以检查基础运行环境：

```bash
python scripts/dev/check_install.py
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

AscendC-Pilot 应在 **目标 AscendC 算子仓库** 中使用，而不是在 AscendC-Pilot 自身仓库中运行。进入目标仓后，在 OpenCode 中通过 **Tab** 切换到 AscendC-Pilot Agent，然后直接描述任务即可：

```text
帮我为当前算子的 arch35 建立 CodeMap
```

也可以直接使用命令：

```text
/uo-init
```

CodeMap 建立完成后，算子产物会保存在：

```text
<operator-repo>/.ascendc-pilot/
```

---

# 常用用法

## 建立和更新 CodeMap

首次分析当前算子：

```text
/uo-init
```

源码修改后更新已有 CodeMap：

```text
/uo-update
```

## 查询算子

CodeMap 建立后可用 `/uo-query` 询问 Host、Tiling、TilingData、Kernel 和 unresolved gap，例如：

```text
这个 TilingKey 是怎么决定的？
这个 TilingData 字段在 Host 哪里赋值？
这个 Kernel 分支由哪个 Host 条件控制？
当前还有哪些 unresolved gap？
```

## 生成测试覆盖

CodeMap 就绪后，TG 使用 UO 产物建立覆盖义务，并通过候选搜索和 Host replay 验证真实行为：

```text
/tg-init
/tg-plan
/tg-solve
```

你也可以直接说：

```text
帮我补齐当前没有覆盖的 TilingKey
检查这个 TilingKey 下还有哪些 runtime branch 没覆盖
```

覆盖目标只有在获得实际 replay evidence，或者经过审查的不可达证明后才会关闭。

## 代码审查与影响分析

CE 复用已有 CodeMap 分析当前 diff 对 Host、TilingData、TilingKey 和 Kernel 路径的影响：

```text
/ce-review
```

# 常用命令

| 目标 | 命令 |
| --- | --- |
| 建立或更新 CodeMap | `/uo-init`、`/uo-update` |
| 查询或调查 gap | `/uo-query`、`/uo-investigate` |
| 生成测试覆盖 | `/tg-init`、`/tg-plan`、`/tg-solve` |
| 代码审查 | `/ce-review` |

通常不需要记住全部命令，直接告诉 Agent 你想完成什么即可。

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
* Kernel Root Trace（buffer / register / sync 与 AscendC root 的源码可达性）
* Host → Kernel 数据关系

无法可靠确定的信息会保留为 unresolved，不会通过模型猜测补齐。

### TG

TG 将 CodeMap 中的 TilingKey 和 runtime branch 转换为测试覆盖目标，再通过有限谓词求值、候选枚举/搜索和 Host Replay 获得真实运行证据。不使用约束求解后端。

```text
UO → deterministic CodeMap / TG projection
  → TG: finite predicate evaluation
       + finite-domain candidate search
       + Host replay / observation
       + evidence closure
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
