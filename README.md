# AscendC-Pilot

AscendC-Pilot 是面向 AscendC 算子开发的 AI Agent 控制面。它先从算子源码构建结构化的 Operator CodeMap，再基于这份 CodeMap 做测试生成、覆盖闭环和代码审查，避免每个 Agent 反复通读完整算子仓。

项目当前处于 active / experimental 状态。核心约束是：源码事实和规范产物由确定性引擎与 Pilot Harness 负责，LLM Agent 只做有边界的分析、阶段性产物或 referee 审查。

## 核心能力

**UO - Understand Operator**：分析 AscendC 算子并生成 CodeMap，覆盖 Host、TilingKey、TilingData、Kernel 分支、源码范围、未解析 gap 与可查询关系。

**TG - Testcase Generation**：消费 UO CodeMap，规划并求解测试义务，支持 TilingKey 闭环和 runtime branch outcome 覆盖。

**CE - Code Engineering**：消费 UO CodeMap 做代码审查和影响分析。当前公开入口是 `/ce-review`。

## 总体架构

```text
User
  -> Host Adapter
  -> Primary Agent
  -> Pilot Runtime / Harness
  -> Action Bundle
       -> deterministic engine
       -> bounded LLM agent
  -> Artifact
  -> Gate / Referee
```

架构总入口见 [docs/architecture/overview.md](docs/architecture/overview.md)，模块细节见 [docs/modules/](docs/modules/)。

## 环境要求

- Python 3.10+
- PyYAML
- UO 抽取需要 libclang
- TG 可选依赖：scikit-learn、pandas、numpy
- 支持的 Host：OpenCode、Cursor、Codex

## 安装

```bash
pip install -r requirements.txt
pip install -e ./pilot
pip install -e ./engines/common
pip install -e ./engines/understand-operator
pip install -e "./engines/testcase-generation[ml]"
pip install -e ./engines/code-engineering
acp doctor
```

安装 Host Adapter：

```powershell
./install.ps1 opencode
./install.ps1 cursor
./install.ps1 codex
```

Linux：

```bash
./install.sh opencode
```

## Quick Start

在目标 AscendC 算子仓里运行，不要在 AscendC-Pilot 自身 checkout 里运行：

```text
/uo-init
/uo-query
```

CodeMap 就绪后运行 TG：

```text
/tg-init
/tg-plan
/tg-solve
```

需要代码审查时运行：

```text
/ce-review
```

算子本地产物统一写入：

```text
<operator-repo>/.ascendc-pilot/
```

## 仓库结构

```text
adapters/          OpenCode / Cursor / Codex host overlay
agents/            Agent 与 deterministic engine 身份
engines/           UO / TG / CE / common 确定性引擎
evals/             routing、skill、harness eval 与 fixture
generated/         composer 生成的 host runtime
opencode-plugin/   OpenCode 集成
pilot/             workflow runtime、lease、gate、state、CLI
prompts/           task prompt asset
schemas/           local extension schema
scripts/           生成、校验、开发工具
skills/            runtime skill bundle 与 references
tests/             仓库级测试和 fixture
docs/              人类说明文档
```

职责归属见 [docs/reference/repository-layout.md](docs/reference/repository-layout.md)。

## 文档

从 [docs/README.md](docs/README.md) 开始。

常用入口：

- [架构总览](docs/architecture/overview.md)
- [Agent 系统](docs/architecture/agent-system.md)
- [Harness 与权限](docs/architecture/harness-and-permissions.md)
- [UO 模块](docs/modules/uo.md)
- [TG 模块](docs/modules/tg.md)
- [CE 模块](docs/modules/ce.md)
- [文档维护规则](docs/development/documentation.md)

## 开发

```bash
python scripts/check_docs.py
pytest
```

修改 `agents/*.yaml` 后重新生成 Agent Matrix：

```bash
python scripts/generate_agent_matrix.py
```

## License

当前 checkout 尚未声明 license 文件。
