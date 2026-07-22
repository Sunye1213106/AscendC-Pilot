# Testcase Agent

OpenCode / Cursor 上的 **Ascend C 测例生成插件**。消费 Understand Operator 定稿 KB + 测试工具 CSV 契约，规划覆盖义务并用 Z3 求解 CSV。

| | |
| --- | --- |
| Agent | [OpenCode](https://opencode.ai)（推荐）/ [Cursor](https://cursor.com) |
| 上游 | [understand-operator](../understand-operator/)（须先 `/uo-init`） |
| 产物根 | `<算子包>/.testcase-generator/<op_name>/`（`$OUT_ROOT`） |

详细工作流见 [`docs/`](./docs/)。

## 做什么

用户只接触三个命令：`/tg-init` → `/tg-plan` → `/tg-solve`。

UO 把语义追到**算子接口面**（`HOST_ATTR_*` 等）。本插件再映射到 **`VAR_CSV_*`**，形成可 SMT 执行的 lexicon，并按 level 求 CSV。

| 命令 | 用途 |
| --- | --- |
| `/tg-init` | 摄入测试工具 + KEY 绑定 → `init.status=confirmed` |
| `/tg-plan` | 人输入 → LLM 定 KEY/变量（空=全部输入可达）；默认 **L0+L1**；可选 **L2** |
| `/tg-solve` | 已批准 level → Z3 → CSV（禁改 approved plan） |

| Level | 含义 | 默认 |
| --- | --- | --- |
| L0 | 功能冒烟 | ✅ |
| L1 | 范围内的 kernel branch | ✅ |
| L2 | 全部可达 TilingKey | 可选 |

无人工范围 = 全部输入可达（默认剔除 loopId/blockId 等核内不可控）。

## 安装

```powershell
./install.ps1 opencode   # 或 cursor；默认 pip install -e ".[solver]"
```

须同时装好 [understand-operator](../understand-operator/README.md) 与 [CBM](../understand-operator/docs/cbm-mcp-setup.md)。

## 使用

```powershell
tg-init "<算子仓>" --op-name <op> --test-script-root "<测试工具>"
tg-init "<算子仓>" --op-name <op> --confirm

tg-plan "<算子仓>" --op-name <op>                         # 默认：全部输入可达 L0,L1
tg-plan "<算子仓>" --op-name <op> --focus "KEY_A KEY_B"  # 人/LLM 指定 KEY
tg-plan "<算子仓>" --op-name <op> --level L0,L1,L2        # 加 L2

tg-solve "<算子仓>" --op-name <op> --level L0
```

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/tg-init-workflow.md](./docs/tg-init-workflow.md) | `/tg-init` |
| [docs/tg-plan-workflow.md](./docs/tg-plan-workflow.md) | `/tg-plan` |
| [docs/tg-solve-workflow.md](./docs/tg-solve-workflow.md) | `/tg-solve` |
| [skills/PATHS.md](./skills/PATHS.md) | 路径与状态机 |
