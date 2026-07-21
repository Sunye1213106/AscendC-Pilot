# Ascend C PR Test Agent

面向 **Ascend C 自定义算子** 的 PR Agent 套件：先把算子理解成可查询知识库（KB），再做 **代码审查** 与 **测例规划/求解**。

| 组件 | 作用 |
| --- | --- |
| [understand-operator](./understand-operator/) | 建 KB、图查询、增量更新、`diff/` 影响面、**双路 code review** |
| [testcase-agent](./testcase-agent/) | 扫描测试工具契约，L0–L3 规划测例，Z3/SMT 求解 CSV |

支持安装到 **OpenCode / Codex / Cursor**。

---

## 功能一览

### Understand Operator（UO）

| 命令 / Skill | 功能 |
| --- | --- |
| `/uo-init` | Phase0 人工确认范围 → CBM 窄索引 → 抽取 Host/Kernel/Tiling/Bridge → **lean** 导出契约 + `kb_graph` + `human_overview` |
| `/uo-query` | 只读问答；硬门禁：overview / kb_graph → Grep 热文件 → 小窗 Read → CBM |
| `/uo-update` | 按 git 变更增量刷新 KB，写出 `diff/`（测例优先消费） |
| `/uo-diff` | 只读变更摘要（不写 durable 产品） |
| `/uo-code-review` | 默认 `both`：**Bug（CBM 主）** + **功能/语义（kb_graph 主）** |

**两图（物理分开，审查时混用）**

| 图 | 来源 | 用途 |
| --- | --- | --- |
| **CBM** | MCP `codebase-memory-mcp`（`/uo-init` Phase0 已索引） | Bug 冲击面、调用关系、源码 snippet |
| **kb_graph** | YAML KB 派生 `indexes/kb_graph.sqlite` | 语义实体、shape、约束、义务 |

不需要安装 `code-review-graph`。

### Testcase Agent（TG）

| 命令 | 功能 |
| --- | --- |
| `tg-contract` | 扫描测试工具 → `.testcase-generator/<op>/realization/` |
| `tg-plan` | 读 UO KB + 契约 → L0–L3 `plan/`（含人工审阅） |
| `tg-solve` | 人工 approve 后 **Z3** 求解 → CSV 测例行 |

| Level | 含义 |
| --- | --- |
| L0 | 功能属性冒烟 |
| L1 | 可达运行时分支 / 覆盖 / 边界 / reject |
| L2 | 可达 TilingKey 穷尽 |
| L3 | 主题定制套件（如 determinism） |

---

## 环境要求

| 类别 | 要求 |
| --- | --- |
| OS | Windows（PowerShell）或 Linux / macOS |
| Python | **≥ 3.10**，`python` / `pip` 可用 |
| Git | 算子仓为 git 仓库（变更检测 / revision） |
| Agent 平台 | OpenCode / Codex / Cursor **之一** |
| MCP | **codebase-memory-mcp（CBM）**— UO 建库与审查必需 |
| SMT | **z3-solver** — 仅 `tg-solve` 需要 |

### 需要安装什么（清单）

1. **Python 包**（见下方 `requirements.txt` / editable install）
2. **Agent skills**（根目录 `install.ps1` / `install.sh`）
3. **MCP：codebase-memory-mcp**（二进制 + 写入 Cursor/OpenCode MCP 配置）  
   说明：[understand-operator/docs/cbm-mcp-setup.md](./understand-operator/docs/cbm-mcp-setup.md)  
   仓库内也可参考 `understand-operator/thirdparty/codebase-memory-mcp.exe`（若已随包分发）
4. **不要**再装 code-review-graph（已用 CBM + kb_graph 替代）

---

## Python 依赖安装

在仓库根目录：

```powershell
# 方式 A：纯依赖列表
pip install -r requirements.txt

# 方式 B（推荐）：可编辑安装，带 CLI 入口（uo-* / tg-*）
pip install -e "./understand-operator"
pip install -e "./testcase-agent[solver]"
```

或一条命令：

```powershell
pip install -r requirements.txt -e "./understand-operator" -e "./testcase-agent[solver]"
```

验证：

```powershell
python -c "import yaml, jsonschema, z3; print('ok', z3.get_version_string())"
# 若已 editable 安装：
uo-kb-query --help
tg-solve --help
```

`requirements.txt` 内容概要：`PyYAML`、`jsonschema`、`z3-solver`。

---

## MCP 配置（CBM）

### Cursor

`~/.cursor/mcp.json`（或项目 `.cursor/mcp.json`）示例：

```json
{
  "mcpServers": {
    "codebase-memory-mcp": {
      "command": "C:/Users/<you>/bin/codebase-memory-mcp.cmd",
      "args": []
    }
  }
}
```

### OpenCode

在 `opencode.json` 的 `mcp` 中增加本地 command（指向同一 binary）。建议同时：

```json
{
  "permission": {
    "question": "allow"
  }
}
```

重启 IDE 后确认 MCP 工具含：`index_repository`、`search_graph`、`get_code_snippet`、`trace_path`、`query_graph` 等。

---

## Agent 安装（Skills）

把本目录完整拷到目标机器后，在**本仓库根目录**执行：

### Windows

```powershell
./install.ps1 cursor          # 或 opencode / codex
./install.ps1 cursor -Only understand-operator
./install.ps1 cursor -Only testcase-agent
./install.ps1 opencode -SkipPip
./install.ps1 -Uninstall cursor
```

### Linux / macOS

```bash
chmod +x ./install.sh
./install.sh cursor
ONLY=understand-operator ./install.sh cursor
SKIP_PIP=1 ./install.sh opencode
./install.sh uninstall-cursor
```

安装后会在用户目录创建 skill / plugin 的 **Junction（Windows）或符号链接**，指向本仓库源码。**源码目录不要移动或删除**。

| 平台 | Skills | Plugin |
| --- | --- | --- |
| OpenCode | `~/.config/opencode/skills/` | `~/.config/opencode/{understand-operator,testcase-agent}-plugin` |
| Codex | `~/.agents/skills/` | `~/.agents/...-plugin` |
| Cursor | `~/.cursor/skills/` | `~/.cursor/...-plugin` |

---

## 当前端到端流程

```text
                    ┌─────────────────────────────────────┐
                    │  算子包目录（单个算子，非多算子父仓）   │
                    └─────────────────┬───────────────────┘
                                      │
                         /uo-init（人工确认范围）
                                      │
              ┌───────────────────────┼───────────────────────┐
              ▼                       ▼                       ▼
     CBM 窄索引（MCP）         YAML KB + contracts      indexes/kb_graph.sqlite
              │                       │                       │
              └───────────┬───────────┴───────────┬───────────┘
                          │                       │
               /uo-query（读图优先）      /uo-update → diff/
                          │                       │
                          └───────────┬───────────┘
                                      │
                         /uo-code-review（默认 both）
                    Bug: CBM 主 + KB 补
                    语义: KB 主 + CBM 补
                                      │
                                      ▼
                         review/** 报告（不改 diff/**）
                                      │
         （可选测例）tg-contract → tg-plan → 人工 approve → tg-solve(Z3) → CSV
```

### 1. 建库与审查（UO）

在**单个算子包目录**上调用：

```text
/uo-init   <op_path> --op-name <op>
/uo-query  <op_path> sparseMode 的取值域是什么？
/uo-update <op_path>
/uo-diff   <op_path>
/uo-code-review <op_path> --mode both
# 可选：--requirements DESIGN.md
```

脚本辅助示例：

```powershell
python -X utf8 understand-operator/uo/scripts/kb_query_export.py <op_path> --op-name <op> --profile lean
python -X utf8 understand-operator/uo/scripts/export_kb_graph.py <op_path> --op-name <op>
python -X utf8 understand-operator/uo/scripts/export_human_views.py <op_path> --op-name <op>
python -X utf8 understand-operator/uo/scripts/prepare_review_context.py <op_path> --op-name <op> --mode both
```

KB 阅读顺序：`summary/human_overview.md` → `kb_graph` → Grep 热文件 → 小窗 Read（勿整读 testcase / operator_graph / impact_graph）。

更多：[understand-operator/README.md](./understand-operator/README.md)

### 2. 测例规划与求解（TG）

前提：算子仓已有 `.understand-operator/<op_name>/`。

```powershell
tg-plan <project_root> --op-name <op> --level L0,L1 --test-script-root <test_tool_root>
tg-solve <project_root> --op-name <op> --level L1
tg-contract <project_root> --op-name <op> --test-script-root <test_tool_root>
```

更多：[testcase-agent/README.md](./testcase-agent/README.md)

---

## 仓库结构

```text
Ascendc-PR-test-agent-upload/
├── requirements.txt                 ← pip 依赖（含 z3-solver）
├── install.ps1 / install.sh         ← 一键装两个 Agent
├── understand-operator/
│   ├── docs/cbm-mcp-setup.md        ← CBM MCP 安装
│   ├── skills/  prompts/  agents/
│   └── uo/scripts/                  ← Python 实现
└── testcase-agent/
    ├── skills/  agents/
    └── testcase_agent/              ← tg-contract / plan / solve
```

---

## 换机 / 分发

- 拷贝**整个**本目录（含两个子项目与 `install.*`、`requirements.txt`）
- 目标机：`pip install -r requirements.txt`（或 editable）→ 配置 CBM MCP → 根目录 `install.ps1` / `install.sh`
- 无写死盘符或用户名；安装目标落在当前用户 `$HOME`
- 暂不装 Python 依赖时可用 `-SkipPip` / `SKIP_PIP=1`（`tg-solve` 仍需本机有 z3）

---

## 反馈

Issue / PR：https://github.com/Sunye1213106/Ascendc-PR-test-agent/issues
