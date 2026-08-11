# 这句话应该写在哪一层？

决策表：避免把 Skill / Prompt / Agent / Harness 混进同一段 Markdown。

| 你想表达的内容 | 写到 | 不要写到 |
|----------------|------|----------|
| 领域里「怎么判断 / 常见踩坑」 | `skills/domain/<id>/SKILL.md` 或 `references/gotchas.md` | prompt、agent.yaml、workflow |
| API 细节、长示例、证书格式 | `skills/domain/<id>/references/*` | SKILL.md 正文（保持 ≤200 行） |
| 这一次对哪些 id / 用什么证据 / 产出什么 | `prompts/tasks/<domain>/<task>.md` | Domain Skill、Policy |
| 何时做哪一步、阶段顺序 | `skills/workflows/<id>/SKILL.md` + `pilot/.../specs.py` | Domain Skill |
| Action 绑定的 method / 读写范围镜像 | `skills/actions/.../METHOD.md`（薄）+ Spec | 把领域算法写进 METHOD |
| 身份、写范围、forbidden | `agents/<id>.yaml` | prompt |
| 确定性引擎身份（非 LLM） | `agents/*.yaml` 且 `kind: deterministic_engine` | 宿主 agents MD（compose 跳过） |
| 检索 / 批处理怎么拿数据 | `skills/capabilities/<id>/` | Domain Skill |
| 全局硬约束（证据、源码权威） | `skills/policies/<id>/POLICY.md` | 单次 prompt |
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
- 每个 Domain skill 必须有 `references/gotchas.md`
- Prompt 不得承载 harness 协议字段
