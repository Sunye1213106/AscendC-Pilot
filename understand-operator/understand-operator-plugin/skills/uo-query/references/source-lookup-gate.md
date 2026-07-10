# Source Lookup Gate（uo-query 强制）

目标工作流：

```text
KB 快速起草答案
  → 若答案已 high-confidence 且无冲突：可直接输出（KB-only）
  → 若存在不确定 / medium / needs_alignment / conflict / unknown / 用户要源码证明：
      必须用 codebase-memory-mcp MCP 校验关键符号
      → MCP 成功：用返回的 file+line 可选小范围 Read（≤80 行）核对
      → MCP 失败（空/报错/未连接且已说明）：才允许 Grep 或整文件 Read
  → 用校验结果改写答案后再输出（禁止带着未校验的 medium caveat 收尾）
```

## 必须触发 MCP 校验的信号（任一即触发）

| KB 信号 | 动作 |
|---|---|
| `confidence: medium` / `low` | MCP 校验相关 symbol |
| `needs_alignment: true` | MCP 校验 alignment 相关入口/分支 |
| `unknown` / `conflicting` | MCP 定位真实条件 |
| Hot Risks / Caveat / “张力” / “待确认” | MCP 校验争议点 |
| 用户问“源码依据 / 行号 / 怎么证明” | MCP（+ 必要时 line-scoped Read） |
| KB 两处结论互相矛盾 | MCP 校验两边引用的函数 |

**错误示范：**  
KB 已写出 `Caveat (置信度=medium)` 并点名 `SetSplitAxis`，却输出 `源码查找: KB-only`，或去跑 `cbm_query.py`。  
**正确做法：** 立刻对 `SetSplitAxis` 等调 MCP `search_graph` / `get_code_snippet`，再给出校验后的结论。

## 禁止

| 禁止动作 | 为什么 |
|---|---|
| Shell `cbm_query.py` / `uo-cbm` / `cli` 做交互查询 | 冷启动慢；应用 MCP 常驻 |
| `Read` 整文件 / 大段源码（未先 MCP） | token 暴涨 |
| `Grep` 扫源码当“校验” | 绕过 MCP |
| 发现 medium 却不查 MCP，直接输出 caveat | 用户要校验后的答案 |

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
- `tiling/families.yaml` TF007
- …

**源码核实**
- `op_host/.../xxx.cpp:440-463` — swizzle 判断
- …

**置信度**
- 高（MCP 核实）— 理由；唯一不确定项（若有）

**源码查找**
- KB + MCP(search_graph/get_code_snippet) 已校验
```

**禁止**在答案含 `medium` / `needs_alignment` / `Caveat` 时写 `KB-only（未读源码）`。
