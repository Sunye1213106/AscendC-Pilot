# Understand Operator / Testcase Agent — 仓库说明

面向 **Ascend C 自定义算子** 的 PR Agent 套件：先建可查询 KB，再做代码审查与测例规划/求解。

| 组件 | 作用 |
| --- | --- |
| [understand-operator](./understand-operator/) | 建 KB、图查询、增量更新、`diff/`、双路 code review |
| [testcase-agent](./testcase-agent/) | 测试工具契约 + L0/L1（可选 L2）规划 + Z3→CSV |

支持安装到 **OpenCode / Codex / Cursor**。

---

## 功能一览

### Understand Operator（UO）

| 命令 | 功能 |
| --- | --- |
| `/uo-init` | Phase0 人工确认 → CBM 窄索引 → 抽 IR → 导出 `kb_graph` |
| `/uo-query` | 定稿后问答（sqlite → detail_ref → CBM） |
| `/uo-update` | 增量刷新 KB + `diff/` |
| `/uo-diff` | 只读变更摘要 |
| `/uo-code-review` | Bug（CBM 主）+ 功能/语义（kb_graph 主） |

### Testcase Agent（TG）

| 命令 | 功能 |
| --- | --- |
| `/tg-init` | 测试工具 + 定稿 KB → confirmed realization |
| `/tg-plan` | 人输入 → LLM 定 KEY/变量（空=全部输入可达）；默认 **L0+L1**；可选 **L2** |
| `/tg-solve` | 已批准 level 上 Z3 → CSV |

| Level | 含义 | 默认 |
| --- | --- | --- |
| L0 | 功能冒烟（开关 / 可选输入取值） | ✅ 默认生成 |
| L1 | 范围内的 kernel branch | ✅ 默认生成 |
| L2 | 全部可达 TilingKey | 可选（`--level …,L2` 或 `all`） |

无 L3。无人工范围 = 全部输入可达（默认剔除 loopId/blockId 等核内不可控）。

UO 叶子停在算子接口面（`HOST_ATTR_*` 等）；TG 再映射到 `VAR_CSV_*`。

---

## 环境要求

| 类别 | 要求 |
| --- | --- |
| OS | Windows（PowerShell）或 Linux / macOS |
| Python | ≥ 3.10 |
| Git | 算子仓为 git 仓库 |
| Agent | OpenCode / Codex / Cursor 之一 |
| MCP | codebase-memory-mcp（UO 必需） |
| SMT | z3-solver（仅 `tg-solve`） |

---

## Python 依赖

```powershell
pip install -r requirements.txt -e "./understand-operator" -e "./testcase-agent[solver]"
```

---

## Agent 安装

在**本仓库根目录**：

```powershell
./install.ps1 opencode          # 或 cursor / codex
./install.ps1 opencode -Only understand-operator
./install.ps1 opencode -Only testcase-agent
```

CBM： [understand-operator/docs/cbm-mcp-setup.md](./understand-operator/docs/cbm-mcp-setup.md)

---

## 端到端流程

```text
/uo-init → （可选 /uo-query · /uo-update · /uo-code-review）
    → /tg-init → --confirm
    → /tg-plan                 # 默认 L0,L1；可选 --level L2 --topic <范围>
    → 人工 approve（Allow solve:yes）
    → /tg-solve --level L0|L1|L2
```

```powershell
# UO
/uo-init <op_path> --op-name <op>

# TG
tg-init  <op_path> --op-name <op> --test-script-root <test_tool>
tg-init  <op_path> --op-name <op> --confirm
tg-plan  <op_path> --op-name <op>                       # L0+L1 整仓
tg-plan  <op_path> --op-name <op> --level L0,L1,L2      # 加 L2
tg-plan  <op_path> --op-name <op> --topic determinism   # 限定 topic
tg-solve <op_path> --op-name <op> --level L0
```

更多：[understand-operator/README.md](./understand-operator/README.md) · [testcase-agent/README.md](./testcase-agent/README.md)

---

## 仓库结构

```text
Ascendc-PR-test-agent-upload/
├── requirements.txt
├── install.ps1 / install.sh
├── understand-operator/
│   ├── README.md
│   └── docs/uo-*-workflow.md · cbm-mcp-setup.md
└── testcase-agent/
    ├── README.md
    └── docs/tg-*-workflow.md
```

---

## 反馈

https://github.com/Sunye1213106/Ascendc-PR-test-agent/issues
