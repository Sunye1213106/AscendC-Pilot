# AscendC-Pilot

AscendC-Pilot 是面向 **AscendC 算子开发流程的 AI Agent Harness 与知识基础设施**。

它通过对算子源码进行编译感知分析，构建结构化的 **Operator CodeMap**，将分散在 Host、Tiling、Kernel、模板实例、编译期条件和运行时分支中的隐式关系显式化。

基于 CodeMap，AscendC-Pilot 为后续 Agent 提供可靠的算子知识上下文，支持：

* 自动化算子理解与查询；
* TilingKey / runtime branch 覆盖闭环；
* 基于跨层关系的代码审查与影响分析。

与传统 Coding Agent 不同，AscendC-Pilot 不要求每个 Agent 重新阅读完整算子仓库，而是通过：

```
AscendC Source
        │
        ▼
Compiler-aware Analysis
        │
        ▼
Operator CodeMap
        │
        ├──────────────┐
        ▼              ▼
 Testcase Generation   Code Engineering
        │              │
        ▼              ▼
 Coverage Closure      Impact Analysis
```

将源码理解、测试生成和工程分析建立在统一的结构化知识模型之上。

当前项目处于 **active / experimental** 阶段。

核心设计原则：

> 源码事实、规范产物和状态迁移由确定性引擎与 Pilot Harness 控制；LLM Agent 只负责受约束的分析、阶段性产物生成和 referee 审查。

---

# 核心能力

## UO - Understand Operator

UO（Understand Operator）负责从 AscendC 算子源码构建 Operator CodeMap。

在目标构建变体和源码范围下，UO 使用 `libclang` 提取 Host / Kernel 编译信息，并通过确定性分析流程建立：

* 输入与派生状态关系；
* Host 条件与 TilingKey 关系；
* TilingData 字段来源；
* 模板实例与 Kernel 执行路径；
* 编译期条件与运行时分支关系；
* 架构纯净的 Kernel / TilingData 闭包；
* Kernel 操作、buffer/register、同步事件、数据依赖和 pipeline 派生视图。

当前 UO 的 Kernel 能力已经不止于识别入口和分支。它会在选定架构下重建 Kernel 调用边界、模板参数、ABI、TilingData 读取与 Host 写入者关系；在可解析范围内抽取 AscendC primitive operation、LocalTensor / GlobalTensor / TQue / TBuf / register 等存储对象、同步原语以及 RAW / WAR / WAW 依赖，并生成 CopyIn / Compute / CopyOut / Sync 等 pipeline 提示。无法唯一绑定的内部调用、字段读写或外部依赖仍会作为 gap 暴露，不会被猜测补齐。

最终生成：

* 可查询的 Operator CodeMap；
* 带来源追踪的关系；
* 明确的 unresolved gaps。

UO 的目标不是简单构建 AST，而是建立：

> **面向 AscendC 算子语义的跨 Host-Tiling-Kernel 关系模型。**

---

## TG - Testcase Generation

TG（Testcase Generation）基于 UO CodeMap 建立可审计的测试覆盖闭环。

它将：

* TilingKey；
* runtime branch；
* Host 控制逻辑；

转换为结构化测试义务（coverage obligations）。

TG 通过：

1. 约束搜索与候选生成；
2. Host replay；
3. 动态观测；
4. source-backed exclusion proof；
5. referee 审查；

逐步关闭覆盖目标。

只有以下证据可以关闭覆盖义务：

* 真实 replay 观测结果；
* 经过审查的不可达证明。

因此 TG 不等价于普通 testcase generator，而是：

> **基于证据的 coverage closure system。**

---

## CE - Code Engineering

CE（Code Engineering）利用 UO CodeMap 中已有的跨层关系，对代码修改进行影响分析和审查。

它关注：

* Host 状态变化；
* TilingData 传播；
* predicate 变化；
* Kernel 行为影响。

当前主要入口：

```
/ce-review
```

未来将扩展：

* 自动影响分析；
* 修改建议；
* Debug 辅助；
* PR 工程辅助。

---

# 总体架构

AscendC-Pilot 采用 Harness 驱动的 Agent 架构。

```
User
 │
 ▼
Host Adapter
 │
 ▼
Primary Agent
 │
 ▼
Pilot Runtime / Harness
 │
 ▼
Action Bundle
 │
 ├── Deterministic Engine
 │
 └── Bounded LLM Agent
        │
        ▼
      Skill / Prompt
 │
 ▼
Artifact
 │
 ▼
Gate / Referee
```

其中：

* **Harness** 负责 workflow、权限、状态和验证；
* **Deterministic Engine** 负责可信计算和规范产物生成；
* **LLM Agent** 负责受约束推理和分析任务；
* **Gate / Referee** 负责最终质量控制。

详细设计：

* [Architecture Overview](docs/architecture/overview.md)
* [Agent Runtime](docs/architecture/agent-runtime.md)

---

# 环境要求

AscendC-Pilot 的运行环境按使用场景分层。

| 场景        | 用途                       | 必需条件                                                                              |
| --------- | ------------------------ | --------------------------------------------------------------------------------- |
| 控制面与基础开发  | CLI、文档、基础测试、Host 安装      | Python 3.10+、PyYAML、jsonschema |
| UO/TG 约束分析 | key reachability、loop summary、coverage obligation 求解 | `engines/common` 提供 `acp_common.z3_backend`，并安装 `z3-solver` |
| UO 源码分析   | AscendC Host/Kernel 结构提取 | `libclang>=18.1.1`、clang 工具链、完整 CANN headers、目标算子依赖源码 |
| TG Host Replay | L2/L3 coverage closure   | Linux 或 Windows + WSL、CANN runtime、C++17 工具链、Host UT 构建环境、匹配的 `ops-transformer` checkout |

注意：

`acp doctor` 只能检查 Python 环境、runtime composition 和部分配置。

它不能替代：

* CANN 环境检查；
* Clang 配置检查；
* Host replay 构建与运行环境检查。

详细说明：

[Installation and Environment](docs/getting-started/installation.md)

---

# 安装

## Python 环境

```bash
pip install -r requirements.txt

pip install -e ./pilot
pip install -e ./engines/common
pip install -e ./engines/understand-operator
pip install -e "./engines/testcase-generation[ml]"
pip install -e ./engines/code-engineering

acp doctor
```

---

## 安装 Host Adapter

OpenCode：

```bash
./install.ps1 opencode
```

Cursor：

```bash
./install.ps1 cursor
```

Codex：

```bash
./install.ps1 codex
```

Linux：

```bash
./install.sh opencode
```

---

# Quick Start

> 以下命令应在目标 AscendC 算子仓中执行，而不是 AscendC-Pilot 自身仓库。

## 1. 建立 Operator CodeMap

```text
/uo-init
```

完成后可以查询：

```text
/uo-query
```

例如：

```
这个 TilingKey 是如何决定的？

这个 TilingData 字段来自哪里？

哪个 Host 条件控制了 Kernel 分支？
```

---

## 2. 生成测试闭环

在 CodeMap 就绪后：

```text
/tg-init
/tg-plan
/tg-solve
```

TG 将基于 UO 建立 coverage obligation，并通过 solver、replay 和 evidence 逐步关闭。

---

## 3. 代码审查

```text
/ce-review
```

CE 将结合 CodeMap 分析：

* 修改影响范围；
* 跨 Host/Tiling/Kernel 传播；
* 潜在行为变化。

---

所有算子相关产物统一写入：

```
<operator-repo>/.ascendc-pilot/
```

---

# Repository Structure

```
adapters/          Host Adapter 集成
agents/            Agent identity 与 deterministic engine 定义
engines/           UO / TG / CE / common 引擎
evals/             Agent、Skill、Harness evaluation
generated/         Runtime composer 生成文件
opencode-plugin/   OpenCode 集成
pilot/             Workflow runtime、state、gate、CLI
prompts/           Task prompt assets
schemas/           Extension schemas
scripts/           Generator 与 validation tools
skills/            Runtime skill bundles
tests/             Tests 与 fixtures
docs/              Project documentation
```

完整说明：

[Repository Layout](docs/reference/repository-layout.md)

---

# Documentation

从：

[docs/README.md](docs/README.md)

开始。

推荐阅读路径：

## 使用 AscendC-Pilot

```
Installation
      ↓
Quick Start
      ↓
UO
      ↓
TG / CE
```

## 开发 AscendC-Pilot

```
Architecture
      ↓
Agent Runtime
      ↓
Modules
      ↓
Extension Guide
      ↓
Reference
```

主要文档：

* [Architecture Overview](docs/architecture/overview.md)
* [Agent Runtime](docs/architecture/agent-runtime.md)
* [Artifacts and Authority](docs/architecture/artifacts-and-authority.md)
* [UO Module](docs/modules/uo.md)
* [TG Module](docs/modules/tg.md)
* [CE Module](docs/modules/ce.md)
* [Extension Guide](docs/development/extending.md)

---

# Development

运行文档检查：

```bash
python scripts/check_docs.py
```

运行测试：

```bash
pytest
```

修改 Workflow、Agent 或 CLI 后重新生成 Reference：

```bash
python scripts/generate_reference_docs.py
```

---

# License

当前仓库尚未声明 License。

---
