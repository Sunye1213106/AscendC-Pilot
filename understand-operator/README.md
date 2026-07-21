# Understand Operator

面向 **Ascend C 自定义算子** 的知识库（KB）插件。  
在算子仓库中自动抽取 Host / Kernel / Tiling / 桥接关系，生成可查询的分层 IR，并支持按 git 变更增量更新。

| | |
| --- | --- |
| 仓库 | [Sunye1213106/Ascendc-PR-test-agent](https://github.com/Sunye1213106/Ascendc-PR-test-agent) |
| 插件目录 | 仓库内 [`understand-operator/`](https://github.com/Sunye1213106/Ascendc-PR-test-agent/tree/refactor/uo-facts-graph-test-pipeline/understand-operator) |
| 推荐分支 | `refactor/uo-facts-graph-test-pipeline`（当前主开发线） |
| Agent | [OpenCode](https://opencode.ai) / [Cursor](https://cursor.com) |
| 代码图后端 | [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp)（CBM 证据） |
| 语义图 | `indexes/kb_graph.sqlite`（YAML KB 派生） |
| 审查结构图 | 已有 [codebase-memory-mcp](./docs/cbm-mcp-setup.md)（CBM，Bug 主图；复用 Phase0 索引） |

## 它解决什么问题

手写 AscendC 算子（如 FlashAttention）时，关键信息往往分散在：

- Host tiling / 模板 key
- Kernel 运行时分支与变量
- TilingData 字段桥接
- 可选的 `common/` 共享库

人工追调用链成本高，也难以稳定交给下游做「测例约束 / PR 影响面」消费。

Understand Operator 把上述信息整理成算子本地的一份 KB：

```text
<算子仓>/.understand-operator/<op_name>/
```

之后可用自然语言查询（例如变量取值域、tiling key 命中条件），或在代码变更后增量刷新，并产出面向 PR 的 `diff/` 摘要。

## 实现原理

核心思路是 **「确定性抽取 + 人工确认范围 + 有界 LLM 补洞」**，而不是让 Agent 全仓自由扫代码。

```text
算子源码
   │
   ├─ 1) 范围扫描（可上溯发现 sibling common/）
   ├─ 2) 人工确认分析范围（硬门禁，不可自动跳过）
   ├─ 3) 窄索引：只把确认文件 stage 进 CBM
   ├─ 4) 语法/规则抽取 Host · Kernel · TilingKey · Bridge IR
   ├─ 5) 有界语义补全（仅入口确认 / 残留 unresolved）
   └─ 6) 导出 contracts + validate + kb_graph
          │
          ▼
   .understand-operator/<op>/   ← 同构 KB + indexes/kb_graph.sqlite
          │
          ├─ /uo-update 时另写 diff/  ← PR 测例优先读
          └─ /uo-code-review         ← Bug(CBM主)+语义(KB主)
```

| 层级 | 职责 | 工具 |
| --- | --- | --- |
| 编排 | Skill / Prompt 驱动四条命令 | OpenCode / Cursor Agent |
| 脚本 | 扫范围、抽 IR、导出、增量更新 | `uo/scripts/*.py` |
| 代码图 | 符号 / 调用 / 片段检索 | CBM MCP |
| 契约 | 写权限、KB 布局、diff schema | `spec/` |

设计取舍：

- **KB 固定在算子子目录**：即使发现父级 `common/`，也不把 KB 抬到多算子 workspace。
- **源码证据优先走 CBM**；路径与文件结构用文件系统和 `rg`。
- **LLM 只补抽取器补不到的洞**，不重写整库。
- **`/uo-update` 产出两份结果**：刷新后的同构 KB + 专用 `diff/`。下游测例应先读 `diff/`，不确定时再回查 KB。

## 仓库结构

本插件是 monorepo 子目录，**安装与运行都以 `understand-operator/` 为根**：

```text
Ascendc-PR-test-agent/
└── understand-operator/           ← 插件根（PLUGIN_ROOT）
    ├── install.ps1 / install.sh
    ├── skills/                    # /uo-init /uo-query /uo-update /uo-diff /uo-code-review
    ├── prompts/
    ├── agents/
    ├── uo/                        # Python 实现（scripts + 库）
    ├── spec/
    ├── docs/                      # cbm-mcp-setup.md
    └── tests/
```

## 安装

### 1. Clone

```bash
git clone -b refactor/uo-facts-graph-test-pipeline \
  https://github.com/Sunye1213106/Ascendc-PR-test-agent.git
cd Ascendc-PR-test-agent/understand-operator
```

依赖：Python ≥ 3.10，以及可运行的 `codebase-memory-mcp`（见 `docs/cbm-mcp-setup.md`）。

### 2. 安装到 OpenCode

在 **`understand-operator/`** 目录下执行：

```powershell
./install.ps1 opencode
```

会创建：

- `~/.config/opencode/skills/uo-*` → 本目录 `skills/`
- `~/.config/opencode/understand-operator-plugin` → **本目录（PLUGIN_ROOT）**

脚本路径：`$PLUGIN_ROOT/uo/scripts`。

在 `~/.config/opencode/opencode.json` 中允许人工确认：

```json
{
  "permission": {
    "question": "allow"
  }
}
```

并配置 MCP `codebase-memory-mcp`（binary 路径按本机调整），详见 `docs/cbm-mcp-setup.md`。

### 3. 安装到 Cursor（可选）

1. Settings → Plugins → Add local plugin → 选择 **`understand-operator/`**（含 `skills/` 与 `uo/`）  
2. 或在该目录执行 `./install.ps1 cursor`

### 4. 可选：开发态

仍在 `understand-operator/` 下：

```bash
pip install -r requirements.txt
pip install -e .
python -m pytest tests -q
```

仓库根目录也可：`pip install -r ../requirements.txt`（见上级 [README](../README.md)）。

## 使用

在目标 **算子包目录** 上调用（例如 `flash_attention_score_grad/`），不要指向含多个算子的父目录。

- `--op-name` 可省略：路径下可唯一推断算子名时会自动推导。
- 默认分析架构为 `arch35`（也可在命令里写「只分析 arch35」）。

### 首次建库

```text
/uo-init /path/to/flash_attention_score_grad --op-name flash_attention_score_grad
```

或：

```text
/uo-init /path/to/flash_attention_score_grad 只分析 arch35
```

流程：创建 KB 目录 → 扫描范围 → **人工确认** → 窄索引 + 抽 IR → 语义补全 → 导出契约。

### 提问

```text
/uo-query /path/to/flash_attention_score_grad sparseMode 的取值域是什么？
```

优先读 KB；需要源码证明时再走 CBM。

### 增量更新

```text
/uo-update /path/to/flash_attention_score_grad
```

相对 `manifest` 中的 revision 算 git diff，按层重抽，并写出：

```text
.understand-operator/<op>/diff/
  index.yaml
  change_set.yaml
  impact.yaml
  unresolved.yaml
```

### 只看变更摘要（不写 KB）

```text
/uo-diff /path/to/flash_attention_score_grad
```

### 直接跑脚本

```powershell
python -X utf8 uo/scripts/prepare_operator.py <PROJECT_ROOT> --op-name <OP>
python -X utf8 uo/scripts/build_layered_kb.py <PROJECT_ROOT> --op-name <OP> --architecture arch35
# 默认 lean；调试 L2 穷举时：
# python -X utf8 uo/scripts/kb_query_export.py <PROJECT_ROOT> --op-name <OP> --profile full
python -X utf8 uo/scripts/export_human_views.py <PROJECT_ROOT> --op-name <OP>
python -X utf8 uo/scripts/update_operator.py <PROJECT_ROOT> --op-name <OP>
```

### 怎么读 KB（人 / AI）

1. `summary/human_overview.md`
2. `indexes/kb_graph.sqlite`（`uo-kb-query`）
3. Grep 热文件（`tiling/key_cards/*`、`kernel/runtime_conditions.yaml`）
4. 小窗 Read；**不要**整读 `ir/operator_graph.yaml` / `contracts/testcase.yaml` / `impact_graph`

## 反馈

Issue / PR：https://github.com/Sunye1213106/Ascendc-PR-test-agent/issues
