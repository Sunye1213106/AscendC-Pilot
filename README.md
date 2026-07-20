# Ascend C PR Test Agent

面向 **Ascend C 自定义算子** 的 PR / 测例 Agent 套件：先把算子理解成可查询的知识库（KB），再基于 KB 与测试工程契约规划并生成测例。

| 组件 | 作用 |
| --- | --- |
| [understand-operator](./understand-operator/) | 从算子源码抽取 Host / Kernel / Tiling / Bridge，生成 `.understand-operator/<op>/` KB |
| [testcase-agent](./testcase-agent/) | 扫描测试工具契约，按 L0–L3 规划测例并用 SMT 求解 CSV 行 |

支持安装到 **OpenCode / Codex / Cursor**。

## 仓库结构

```text
Ascendc-PR-test-agent-upload/
├── install.ps1 / install.sh          ← 一键安装两个 Agent
├── understand-operator/              ← UO：建库 / 查询 / 增量更新
│   ├── install.ps1 / install.sh
│   ├── skills/   prompts/   agents/
│   └── uo/                           # Python 脚本与实现
└── testcase-agent/                   ← TG：契约 / 规划 / 求解
    ├── install.ps1 / install.sh
    ├── skills/   agents/
    └── testcase_agent/               # Python 包
```

## 环境要求

- **Windows**：PowerShell（推荐）；Linux / macOS 用 `install.sh`
- **Python** ≥ 3.10，且 `python` / `pip` 可用（testcase-agent 默认会 `pip install -e`）
- 已安装目标平台之一：OpenCode / Codex / Cursor
- understand-operator 完整流程还需要 [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp)（CBM），见 [understand-operator/docs/cbm-mcp-setup.md](./understand-operator/docs/cbm-mcp-setup.md)

## 安装

把本目录完整拷到目标机器后，在**本仓库根目录**执行：

### Windows

```powershell
# 默认安装到 OpenCode
./install.ps1 opencode

# 或 Cursor / Codex
./install.ps1 cursor
./install.ps1 codex

# 只装其中一个
./install.ps1 cursor -Only understand-operator
./install.ps1 cursor -Only testcase-agent

# 跳过 testcase-agent 的 pip 安装
./install.ps1 opencode -SkipPip

# 卸载
./install.ps1 -Uninstall opencode
./install.ps1 -Uninstall cursor
```

### Linux / macOS

```bash
chmod +x ./install.sh
./install.sh opencode
./install.sh cursor

ONLY=understand-operator ./install.sh cursor
ONLY=testcase-agent ./install.sh opencode
SKIP_PIP=1 ./install.sh opencode

./install.sh uninstall-opencode
./install.sh uninstall-cursor
```

安装后会在用户目录下创建 skill / plugin 的 **Junction（Windows）或符号链接**，指向本仓库源码。**源码目录不要随意移动或删除**，否则链接失效，需重新安装。

| 平台 | Skills 目录 | Plugin 链接 |
| --- | --- | --- |
| OpenCode | `~/.config/opencode/skills/` | `~/.config/opencode/{understand-operator,testcase-agent}-plugin` |
| Codex | `~/.agents/skills/` | `~/.agents/{...}-plugin` |
| Cursor | `~/.cursor/skills/` | `~/.cursor/{...}-plugin` |

OpenCode 建议在 `opencode.json` 中允许人工确认：

```json
{
  "permission": {
    "question": "allow"
  }
}
```

也可分别进入子目录单独安装，详见各子项目 README。

## 推荐工作流

```text
算子仓 ──/uo-init──► .understand-operator/<op>/（KB）
                          │
                          ├── /uo-query   自然语言查 KB
                          ├── /uo-update  按 git 变更增量刷新 + diff/
                          └── /uo-diff    只看变更摘要
                                │
测试工具 ──tg-contract──► realization/ 契约
                                │
              tg-plan（算子仓 + 测试工具|契约）──► plan/（L0–L3）
                                │ 人工 approve
                                ▼
                           tg-solve ──► CSV 测例行
```

### 1. Understand Operator（建库）

在**单个算子包目录**上调用（不要指向含多个算子的父目录）：

```text
/uo-init /path/to/flash_attention_score_grad --op-name flash_attention_score_grad
/uo-query /path/to/flash_attention_score_grad sparseMode 的取值域是什么？
/uo-update /path/to/flash_attention_score_grad
/uo-diff /path/to/flash_attention_score_grad
```

更多说明：[understand-operator/README.md](./understand-operator/README.md)

### 2. Testcase Agent（规划与求解）

前提：算子仓已有 `.understand-operator/<op_name>/`。

```powershell
# 测试工具 → 自动 contract + plan
tg-plan <project_root> --op-name <op_name> --level L0,L1 --test-script-root <test_tool_root>

# 或复用已有 contract
tg-plan <project_root> --op-name <op_name> --level L0,L1 --contract-root <realization_dir>

# 人工 approve 后求解
tg-solve <project_root> --op-name <op_name> --level L1

# 只刷新契约
tg-contract <project_root> --op-name <op_name> --test-script-root <test_tool_root>
```

规划级别简要：

| Level | 含义 |
| --- | --- |
| L0 | 功能属性冒烟：每个独立特征至少一条见证用例 |
| L1 | 可达运行时分支 / 功能覆盖 / 边界 / reject |
| L2 | 可达 TilingKey 穷尽覆盖 |
| L3 | 按主题定制套件（如 `--topic determinism`） |

更多说明：[testcase-agent/README.md](./testcase-agent/README.md)

## 换机 / 分发说明

- 拷贝**整个**本目录（至少包含两个子项目及其 `install.*`）
- 在目标机重新执行根目录 `install.ps1` / `install.sh`
- 无写死盘符或用户名；安装目标始终落在当前用户的 `$HOME`
- testcase-agent 若目标机暂不装 Python 依赖，使用 `-SkipPip` / `SKIP_PIP=1`

## 反馈

Issue / PR：https://github.com/Sunye1213106/Ascendc-PR-test-agent/issues
