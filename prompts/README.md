# prompts 布局（Skill 管流程 · Prompt 管局部任务）

| 目录 | 对应 skill | 内容 |
|---|---|---|
| `common/` | 全部 | `runtime.md`（语言/路径/工具）· `cbm.md` · 短入口文件 |
| `init/` | `/uo-init` | `workflow` 状态机 · `dispatch` 派发 · Phase0 菜单 · `tpl_*` |
| `update/` | `/uo-update` | 增量编排 |
| `query/` | `/uo-query` | 短指针（细节在 skill/references） |
| `review/` | `/uo-code-review` | 编排 + bug/functional 任务合同 |

原则见仓内文档 [`docs/skill-and-prompt-principles.md`](../docs/skill-and-prompt-principles.md)：

- **Skill**：输入/输出/阶段/门禁/失败码
- **Prompt / Agent**：单次有界任务、权威源、输出 schema、验收
- **脚本**：确定性逻辑（classify / apply / integrity）

子代理强制模板：`init/references/tpl_*.md`（含 `tpl_entrypoint.md` 任务 A）。  
Agent schema 细则：`agents/references/semantic-resolve-tasks.md`。  
可写面权威：`spec/ownership.yaml`。
