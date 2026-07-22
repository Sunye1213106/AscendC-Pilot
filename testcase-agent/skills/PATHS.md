# Testcase Agent 路径与三入口

## 用户只接触

| Skill | 状态转换 |
|---|---|
| `/tg-init` | 测试工具 + 定稿 KB → **confirmed** realization（内嵌 contract + 绑定/域） |
| `/tg-plan` | confirmed → **已批准** coverage plan（Allow solve:yes） |
| `/tg-solve` | approved plan → CSV rows + uncover 原因码（**禁改** approved plan） |

已退役用户 Skill（不安装）：`tg-contract`、`tg-domain-review`。  
已退役 agent（**不复制到** `~/.cursor/agents`）：`tg-domain-review.md`（仓内 compat 指针）。

## PLUGIN_ROOT（装机后文档根）

| 平台 | `PLUGIN_ROOT` |
|------|----------------|
| OpenCode | `$HOME/.config/opencode/testcase-agent-plugin` |
| Cursor | `$HOME/.cursor/testcase-agent-plugin` |
| Codex | `$HOME/.agents/testcase-agent-plugin` |

Agent / Prompt 引用 schema、skills、prompts 时 **MUST** 用：

`$PLUGIN_ROOT/agents/references/...` · `$PLUGIN_ROOT/skills/...` · `$PLUGIN_ROOT/prompts/...`

禁止依赖「当前工作目录相对 `agents/references`」（装到 `~/.cursor/agents/` 后不存在）。

## 其它权威路径

| 变量 | 含义 |
|---|---|
| `PROJECT_ROOT` | 算子仓 |
| `UO_ROOT` | `$PROJECT_ROOT/.understand-operator/$OP_NAME` |
| `OUT_ROOT` | `$PROJECT_ROOT/.testcase-generator/$OP_NAME` |

## 确定性 vs LLM

| 脚本 | LLM / Task |
|---|---|
| AST contract、merge、verify-csv-closure、Z3、域对称、覆盖核对 | KEY/中间量语义（MUST uo-query）、inventory 内 LLM bind |

禁止手算覆盖率 / 手写全量 unresolved 对齐。

## UO 边界（硬隔离）

- `$UO_ROOT`：**只读**；缺库 / integrity fail → `/uo-init` 或 `/uo-update`
- `$OUT_ROOT`：TG 唯一写入根（contract / realization / init / plan）
- KEY→CSV 绑定断边：MUST Task Follow `uo-query` → 写 `OUT_ROOT/.../uo_query_resolve/`；禁父循环 `uo_kb_query`；cap=8
- 禁止把 `VAR_CSV_*` 或映射写进 UO 图；CSV 映射由 TG（测试脚本 + KB）生成
- skip 白名单：`skills/tg-init/references/legitimate-skips.md`（与 resolve_policy 同表）

内部 agents：`tg-csv-contract`、`tg-init-audit`。派发：`prompts/init/dispatch.md`。
