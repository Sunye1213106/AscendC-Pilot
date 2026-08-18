# Skills layout

Cognitive skills（五个，缺一不可——闭合集合，不是起点）：

| # | id | 用途 |
| --- | --- | --- |
| 1 | `operator-analysis` | UO CodeMap 建库（`/uo-init` `/uo-update`）、查询与调查 |
| 2 | `testcase-generation` | TG 覆盖规划与闭环 |
| 3 | `source-proof` | 源码引理 / 不可达证明 |
| 4 | `code-review` | `/ce-review` 只读检视（Spec / Standards 两轴） |
| 5 | `code-engineering` | `/ce-plan` `/ce-apply` `/handoff`：命名计划、按 todo 改码、会话交接 |

| Kind | Path | Notes |
|------|------|-------|
| Cognitive skills | `skills/<id>/` | Self-contained `SKILL.md` + `references/` + `examples/` |
| Action METHOD | `skills/<id>/capabilities/<cap>/METHOD.md` | One LLM Action reasoning playbook. Spec `action_method_id="{skill}/{capability}"`. Prepare fail-closed if missing. Not for routers or engines. |
| Router | `skills/<id>/routing/*.md` | Primary-visible routing. Not an Action METHOD. |
| Shared language | `agents/CONTEXT.md` | Compose 进 invariant pack；跨 UO/TG/CE 同名词表 |
| Templates | `skills/testcase-generation/templates/` | Structure-only snippets (not worked examples) |
| Authoring shared refs | `knowledge/shared-references/` | SSOT；默认五份投影到四个 skill（**不要**塞进 `code-engineering`）。`harness-oracle.md` **只**投影到 `testcase-generation` |
| Shared | `skills/_shared/` | **已删除，勿再添加。** 运行时不要复活；authoring SSOT 在 `knowledge/` |

Each cognitive skill must ship ≥2 worked example case directories under `examples/<case>/` with `README.md`, `input/`, `expected/`.

## Control-plane skill

编排权威是 `skills/workflow-orchestration/`（**不是**第六个 cognitive skill）：

- Primary `skill_ids` 包含它；compose **不要**加 `disable-model-invocation`
- OpenCode 投影到 `generated/<host>/skills/workflow-orchestration/`（与 slash 入口同树，可被模型调用）
- 内容：每个 slash 的输入输出、交叉流水线（含 `.uo` → `/tg-init`）、主控怎么选下一步
- 认知 skill 仍是闭合五个；CE/TG 语义一律 `/uo-query`

## Invocation

Cognitive skills 是 **method bundle**，不是 Host 发现的 slash：

- Cursor / Codex compose 会给认知 `SKILL.md` 加上 `disable-model-invocation: true`
- OpenCode 把它们投影到 `cognitive-skills/`，不进 Skill discovery
- 人侧发现入口是生成的 workflow slash（`/uo-init`、`/uo-query`、`/tg-plan`、`/ce-apply`、…）
- Action prepare 把该 Action 的 **METHOD.md** 物化进 lease bundle；`Agent.skill_ids` 只是 refs 授权上限，不拼接 SKILL 正文
- 纯确认（`primary_interactive`）不装载认知 Skill

不要把通用 `/implement`、`/tdd`、第二份 `code-review` 写进 `skill_ids`。工程主流程：grilling → `/ce-plan`（写出 `ce/plan/{slug}_plan.md`），改码 → `/ce-apply`（按该 md 未完成 todo），双轴审查 → `/ce-review`（对话不落盘），交接 → `/handoff`。验证走 `/tg-plan`：TG 自己从计划 md、审查对话或 `session_handoff.md` 总结义务。CE 不写 yaml。

## Writing

改认知 skill 时遵守：正向完成条件、指针质量、`SKILL.md` ≤200 行、METHOD/prompt 禁止 harness 泄漏（`finalize` / `run_id` 等）。词表用 `agents/CONTEXT.md`。
