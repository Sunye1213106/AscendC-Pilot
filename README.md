# AscendC-Pilot

AscendC-Pilot 是一个面向 **AscendC 算子开发** 的 AI Agent 工具。

项目通过静态分析构建算子的结构化知识，使 Agent 不需要反复阅读大量 AscendC 源码，也能理解 Host、TilingKey、TilingData、Kernel 之间的关系，并在此基础上完成测试生成、代码审查和开发辅助。

目前主要包含三个能力：

- **UO — Understand Operator**：分析 AscendC 算子并构建算子知识库
- **TG — Testcase Generation**：基于算子知识生成测试并完成覆盖闭环
- **CE — Code Engineering**：基于算子知识进行代码审查和开发辅助

支持 **OpenCode / Cursor / Codex**。

---

## Features

### Understand Operator

```text
AscendC Source
      ↓
Static Analysis
      ↓
Operator Knowledge Base
```

分析：

- Host 控制流
- TilingKey
- TilingData
- Kernel Template / Branch
- 变量来源与依赖关系
- Host → Kernel 跨层关系

主要命令：

```text
/uo-init
/uo-query
/uo-update
```

---

### Testcase Generation

基于 UO 生成的算子知识：

- 构建测试输入约束
- 分析 TilingKey 可达性
- 自动生成测试用例
- Solver 求解
- Host Replay
- Coverage Closure
- L3 同 TilingKey 下 TilingData / Kernel 分支结果覆盖

主要命令：

```text
/tg-init
/tg-plan
/tg-solve
```

TG 推荐分两层运行：

```text
L2: Full TilingKey closure
D = R ∪ E
        ↓
L3: Runtime branch closure
same-key candidate
        ↓
real Host replay
        ↓
TilingData / STATE observation
        ↓
TD value-class + Kernel branch outcome
```

L3 **不会**把候选生成器的静态目标或 set-cover claim 当成覆盖。只有 Host replay 成功且实际返回目标 TilingKey 的观测才能结算 runtime obligation；缺少 TilingData decoder 时相关 debt 保持 open。

---

### Code Engineering

面向日常 AscendC 开发：

- Code Review
- 修改影响分析
- 算子语义查询
- Context 构建
- 后续代码修改与 Debug

当前入口：

```text
/ce-review
```

---

## Install

### Python Environment

```bash
pip install -r requirements.txt

pip install -e ./pilot
pip install -e ./engines/common
pip install -e ./engines/understand-operator
pip install -e "./engines/testcase-generation[ml]"
pip install -e ./engines/code-engineering
```

检查安装：

```bash
acp doctor
```

---

### Install Agent Host

#### OpenCode

Windows：

```powershell
./install.ps1 opencode
```

Linux：

```bash
./install.sh opencode
```

#### Cursor

```powershell
./install.ps1 cursor
```

#### Codex

```powershell
./install.ps1 codex
```

---

## Quick Start

在 AscendC 算子仓中运行：

```text
/uo-init
```

UO 会分析当前算子并在：

```text
<operator-repo>/.ascendc-pilot/
```

生成项目本地知识与运行数据。

完成后可以直接查询算子：

```text
/uo-query
```

例如：

```text
这个算子的 TilingKey 是怎么决定的？
```

```text
s1Inner 最终来自哪个输入？
```

```text
这个 Kernel 分支由哪些 Host 条件控制？
```

### OpenCode：全量 TilingKey + TilingData/Kernel 控制流

先初始化 TG：

```text
/tg-init
```

第一阶段先闭合全部 TilingKey。调用 `/tg-plan` 时明确要求 **level L2 / full TilingKey coverage**，随后运行：

```text
/tg-plan
/tg-solve
```

L2 结束的硬前置是：

```text
Declared TilingKeys = Replayed Reachable Keys ∪ Soundly Excluded Keys
D = R ∪ E
```

然后启动第二阶段。再次调用 `/tg-plan`，明确要求 **level L3 / TilingData + Kernel branch outcome coverage**，再运行：

```text
/tg-plan
/tg-solve
```

Pilot 会把 `level=L3` 持久化到当前 run；`tg-solve` 随后复用现有 closure 状态，对每个 reachable TilingKey 做 bounded runtime search。L3 不会重新发明一套 `td-*` workflow。

L3 生成出的实际 same-key replay case 会写入 TG replay artifacts，runtime obligation 与证据写入：

```text
<operator-repo>/.ascendc-pilot/tg/closure/
├── obligation_inventory.yaml
├── obligation_summary.yaml
├── branch_runtime.yaml
└── branch_rounds/
```

如果某轮候选发生 TilingKey rewrite，它只作为诊断证据保存，**不计入目标 key 的分支覆盖**。

需要代码审查时：

```text
/ce-review
```

---

## How It Works

AscendC-Pilot 将系统分成两个部分：

```text
Agent
  ↓
Pilot
  ↓
UO / TG / CE
  ↓
Operator Knowledge
```

**Pilot** 负责工作流、状态和执行编排。

**UO** 负责把 AscendC 源码转化为结构化算子知识。

**TG / CE** 不重新理解完整源码，而是优先消费 UO 已经建立的算子知识。

Agent 的规则、能力和任务分别由：

```text
skills/
prompts/
agents/
```

组合生成。

详细设计见：

```text
docs/
```

---

## Project Structure

```text
AscendC-Pilot/
│
├── pilot/                      # 控制面：Workflow Spec、State、Gate、Policy、runtime
├── engines/                    # UO / TG / CE 确定性引擎
├── skills/                     # 四个认知 Skill + _shared
├── tools/                      # 源码 / CodeMap 工具契约
├── adapters/hosts/             # OpenCode / Cursor / Codex overlays
├── prompts/                    # Task Prompt
├── agents/                     # Agent Role
├── schemas/                    # UO / TG / Local Extension schemas
├── tests/fixtures/             # synthetic / archived test packages only
├── opencode-plugin/            # OpenCode Adapter
├── scripts/                    # compose / 检查 / 开发工具
├── docs/                       # 设计文档
├── evals/                      # dry evals
│
├── install.ps1
├── install.sh
└── requirements.txt
```

### `skills/`

模型可读专业知识（progressive disclosure）：

- `operator-analysis` — UO CodeMap 构建与查询
- `testcase-generation` — 测例契约 / 计划 / 闭环
- `source-proof` — 源码引理证明
- `code-review` — 代码审查

Action / Workflow 编排权威在 `pilot/.../workflows/specs.py`；compose 生成 slash 入口与 Action Bundle 镜像。

### `pilot/`

AscendC-Pilot 控制面。

负责：

- Workflow
- State
- Gate
- Context
- Action 调度
- CLI
- Policies（`pilot/policies/`）
- Runtime capabilities（`pilot/runtime/`）
- OperatorWorkspace / Local Extension 加载

### `tools/`

源码阅读 / 导航与 CodeMap 查询的工具使用契约。

### `engines/understand-operator/`

UO 核心实现。

负责 AscendC 静态分析和 Operator Knowledge Base 构建。

### `engines/testcase-generation/`

TG 核心实现。

负责测试生成、约束求解和覆盖闭环。

### `engines/code-engineering/`

CE 核心实现。

负责 Code Review 和后续开发辅助能力。

### `prompts/`

具体任务使用的 Prompt。

### `agents/`

不同 Agent 的角色和职责定义（仅 LLM 执行者）。

### 算子知识与 Local Extension

Pilot 源码**不**保存任何具体算子知识。运行产物与本地补充能力一律在算子目录：

```text
<operator-root>/.ascendc-pilot/<arch>/
├── uo/                 # canonical .uo + projections
├── tg/
├── local/              # Local Extension（case-builder / tilingdata-decoder / …）
├── context/
├── runs/
└── config.local.yaml
```

测试用 synthetic / 归档 adapter 仅在 `tests/fixtures/`。

### `scripts/`

仓库级工具，包括：

- Runtime 生成
- Contract Check
- Operator independence lint
- Acceptance Test
- 开发辅助脚本

### `docs/`

保存详细设计。

包括：

- 系统架构
- UO 静态分析
- Relation Graph
- TilingKey Closure
- TG
- Skill / Prompt 设计
- Debug 与 Benchmark

---

## Runtime Data

AscendC-Pilot 不把算子分析产物写回自身源码目录。

所有算子级数据统一写入：

```text
<operator-repo>/.ascendc-pilot/
```

例如：

```text
.ascendc-pilot/
├── uo/
├── tg/
├── ce/
├── context/
├── memory/
├── runs/
└── state/
```

源码仓只维护工具本身，具体算子的 KB、Cache、Replay 和运行结果属于目标算子仓。

---

## Documentation

详细设计见：

```text
docs/README.md
```

主要包括：

```text
docs/design/
docs/fag/
docs/debug/
```

README 只描述项目如何使用。

具体的静态分析算法、Relation Graph、Knowledge Base Schema、TilingKey Closure 和 Agent Workflow 设计均放在 `docs/` 中维护。