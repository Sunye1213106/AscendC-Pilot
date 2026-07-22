# Source Lookup Gate（uo-query 强制）

目标工作流：

```text
先跑 uo_kb_query.py（--status-only + 至少一个 --pattern）
  → sqlite fresh：用 graph JSON 起草，query_backend=kb_graph
  → 再按需读 detail_ref YAML（禁止先 Grep key_cards），不要用 Grep 代替 graph
  → 若答案已 high-confidence 且无冲突：可直接输出
  → 否则（medium / low / needs_alignment / conflict / unknown / 用户要源码证明）：
      默认模式（非 fast）：循环调用 codebase-memory-mcp（search_graph /
        get_code_snippet / search_code / trace_path）校验争议符号，
        用返回的 file+line 可选小范围 Read（≤80 行），改写答案，
        直到置信度升到 high 或 MCP 明确失败（空/报错/未连接且已说明）
        → MCP 失败后才允许 Grep / 整文件 Read 兜底，仍尽量抬到 high
        → 未达 high 不得收尾（除非用户明确要求 fast）
      fast 模式（用户说 fast / 快速 / --fast）：允许直接输出 medium/low，
        标明置信度与未校验项；仍建议至少一次 MCP，但不必循环到 high
```

**TestAgent (tg-init) 例外覆盖 fast：** TG 交付 `$OUT_ROOT/realization/uo_query_resolve` 时 **禁止** `confidence: medium|low` 标 `resolved`；未达 high 必须继续 CBM/源码或标 `unresolved`（empty 白名单除外）。  
CSV↔HOST / `VAR_CSV_*` 叶子与 mid 套娃：**权威在** testcase-agent  
`skills/tg-init/references/tg-uo-query-escalation.md` 与 `tg-mid-symbol-nesting.md`（只写 OUT_ROOT，不改 UO 图）。  
撞上 Host 中间量 → 开嵌套 Task（见上述 TG 引用），禁止停在「depends on X」或写 `already_bound_in_kb`。

**禁止：** `--status-only` 成功后直接 Grep `tiling/key_cards/` / `ir/**` 而不跑 `--pattern`。  
**禁止：** TG 绑定任务写入 `$UO_ROOT/**` 或 `key_shape_resolve/`。

## 必须触发 MCP 校验的信号（任一即触发）

| KB 信号 | 动作（默认非 fast） |
|---|---|
| `confidence: medium` / `low` | 循环 MCP 校验相关 symbol，直到 high |
| `needs_alignment: true` | 循环 MCP 校验 alignment 相关入口/分支，直到 high |
| `unknown` / `conflicting` | 循环 MCP 定位真实条件，直到 high |
| Hot Risks / Caveat / “张力” / “待确认” | 循环 MCP 校验争议点，直到 high |
| 用户问“源码依据 / 行号 / 怎么证明” | 循环 MCP（+ 必要时 line-scoped Read），直到 high |
| KB 两处结论互相矛盾 | 循环 MCP 校验两边引用的函数，直到 high |
| 用户要求 `fast` / `快速` / `--fast` | 允许 medium/low 收尾；标注未校验项即可 |
| 复杂 unresolved / KEY shape expr 升级（见 `complex-unresolved-escalation.md`） | 按 KEY 并行 uo-query + MCP→high；禁止 bare unsolved 收尾 |
| 复杂 KEY / shape unresolved（`escalate_keys` / bind 缺 expr） | **不要** bare unsolved；走 `complex-unresolved-escalation.md`：每 KEY 一 subagent + `branches_for_key`/`affected_shapes` + MCP→high |

**错误示范：**  
默认模式下 KB 已写出 `Caveat (置信度=medium)` 并点名 `SetSplitAxis`，却输出 `源码查找: KB-only`，或只查一次就带着 medium 收尾，或去跑本地 CBM CLI。  
**正确做法：** 对 `SetSplitAxis` 等反复调 MCP `search_graph` / `get_code_snippet`，改写到 high 再输出；仅当用户要求 fast 时允许 medium 收尾。

## 禁止

| 禁止动作 | 为什么 |
|---|---|
| Shell 本地 CBM CLI 做交互查询 | 冷启动慢；应用 MCP 常驻 |
| `Read` 整文件 / 大段源码（未先 MCP） | token 暴涨 |
| `Grep` 扫源码当“校验” | 绕过 MCP |
| 默认模式下发现 medium 却不循环 MCP，直接输出 caveat | 默认必须抬到 high；仅 fast 允许 medium |

**允许且不需要 MCP：** 只读 `.understand-operator/<op>/` 下 YAML/MD，以及本 skill / prompts。

## MCP 怎么选工具

| 目的 | tool | 示例 |
|---|---|---|
| 找函数/类/符号 | `search_graph` | `name_pattern=".*SetSplitAxis.*"`, `label="Function"` |
| 找字符串/宏/分支关键字 | `search_code` | `pattern="IsTndSwizzle"` |
| 看函数摘要/片段 | `get_code_snippet` | qualified `symbol`（先 search_graph） |
| 跟调用链 | `trace_path` | `function_name=...`, `depth=5` |

优先从 KB `evidence_index.yaml` / Caveat 里的 **symbol 名** 构造 MCP 查询。

## 回答结尾：引用段（强制）

```markdown
## 引用

**KB**
- `facts/host.yaml` `VAR_DEMO_TILE`
- …

**源码核实**
- `op_host/.../xxx.cpp:440-463` — swizzle 判断
- …

**置信度**
- 高（MCP 核实）— 理由；唯一不确定项（若有）
- 或（仅 fast）：中/低 — 列出未校验符号与原因

**源码查找**
- KB + MCP(search_graph/get_code_snippet) 已校验（默认应循环至 high）
- 或（仅 fast）：KB ± 有限 MCP；未抬到 high 的项已列出
```

**禁止**在默认模式（非 fast）下以未校验的 `medium` / `needs_alignment` / `Caveat` 收尾，或写 `KB-only（未读源码）`。  
**fast 例外：** 允许 medium/low，但必须在「置信度」段标明模式与未校验项。
