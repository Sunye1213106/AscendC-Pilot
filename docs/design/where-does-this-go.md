# 这句话应该写在哪一层？

决策表：避免把 Skill / Prompt / Agent / Harness 混进同一段 Markdown。

| 你想表达的内容 | 写到 | 不要写到 |
|----------------|------|----------|
| 领域里「怎么判断 / 常见踩坑」 | `skills/<skill>/SKILL.md` 或 `references/gotchas.md`（四技能：`operator-analysis` / `testcase-generation` / `source-proof` / `code-review`） | prompt、agent.yaml、Pilot Spec |
| API 细节、长示例、证书格式 | `skills/<skill>/references/*`；共用纪律见 `skills/_shared/` | SKILL.md 正文（保持 ≤200 行） |
| 这一次对哪些 id / 用什么证据 / 产出什么 | `prompts/tasks/<area>/<task>.md` | Domain Skill、Policy |
| 何时做哪一步、阶段顺序 | Pilot Spec + generated entry wrappers | Domain Skill |
| Action 身份 / 读写 / contract / checker | `pilot/.../workflows/specs.py`（compose 镜像 action.yaml） | Domain Skill、Prompt |
| 身份、写范围、forbidden | `agents/<id>.yaml` | prompt |
| 确定性引擎身份（非 LLM） | `agents/*.yaml` 且 `kind: deterministic_engine` | 宿主 agents MD（compose 跳过） |
| 检索 / 批处理怎么拿数据 | `tools/` 或 `pilot/runtime/` | Skill |
| 全局硬约束（证据、源码权威） | `pilot/policies/<id>/POLICY.md` | 单次 prompt |
| PASS/FAIL、lease、finalize、contract | Pilot harness（Python） | Prompt / Domain Skill |
| 最小上下文切片配方 | `pilot/.../context/profiles.py` | Agent 自己全文检索 |

## 快速口诀

```text
HOW（怎么想）     → Domain Skill + gotchas
WHAT NOW（这次）  → Prompt
WHO（隔离谁）     → Agent（仅当需要独立 context / 并行 / 权限 / 对抗审查）
WHEN/GATE（何时过）→ Harness
```

## Agent 必要性（摘要）

需要 **context isolation / 并行 / 工具权限隔离 / adversarial review** → Agent。  
否则 → Skill / Action / Engine。详见 [agents/README.md](../../agents/README.md)。

## Lint

可机检规则在 `scripts/check_skill_architecture.py`：

- Domain SKILL.md ≤200 行，不得 include 其他 Domain SKILL.md
- Domain 不得出现 Harness 协议词（finalize / declare_workflow_passed / execution_mode 等）
- 每个 Domain skill 必须有 `references/gotchas.md`（或等价 gotchas 文件）
- Prompt 不得承载 harness 协议字段
