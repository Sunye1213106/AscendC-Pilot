# Skills layout

Cognitive skills（五个，缺一不可——闭合集合，不是起点）：

| # | id | 用途 |
| --- | --- | --- |
| 1 | `operator-analysis` | UO CodeMap 建库（`/uo-init` `/uo-update`）、查询与调查 |
| 2 | `testcase-generation` | TG 覆盖规划与闭环 |
| 3 | `source-proof` | 源码引理 / 不可达证明 |
| 4 | `code-review` | `/ce-review` 只读检视（Spec / Standards 两轴） |
| 5 | `code-engineering` | `/ce-intent` `/ce-apply` `/ce-impact` `/ce-verify` `/ce-handoff` 变更闭环 |

| Kind | Path | Notes |
|------|------|-------|
| Cognitive skills | `skills/<id>/` | Self-contained `SKILL.md` + `references/` + `examples/` |
| Action METHOD | `skills/<id>/capabilities/<cap>/METHOD.md` | One LLM Action reasoning playbook. Spec `action_method_id="{skill}/{capability}"`. Prepare fail-closed if missing. Not for routers or engines. |
| Router | `skills/<id>/routing/*.md` | Primary-visible routing. Not an Action METHOD. |
| Shared language | `agents/CONTEXT.md` | Compose 进 invariant pack；跨 UO/TG/CE 同名词表 |
| Templates | `skills/testcase-generation/templates/` | Structure-only snippets (not worked examples) |
| Authoring shared refs | `knowledge/shared-references/` | SSOT；默认五份投影到四个 skill（**不要**塞进 `code-engineering`）。`harness-oracle.md` 只投影到 `testcase-generation` 与 `code-engineering` |
| Shared | `skills/_shared/` | **已删除，勿再添加。** 运行时不要复活；authoring SSOT 在 `knowledge/` |

Each cognitive skill must ship ≥2 worked example case directories under `examples/<case>/` with `README.md`, `input/`, `expected/`.

## Invocation

Cognitive skills 是 **method bundle**，不是 Host 发现的 slash：

- Cursor / Codex compose 会给认知 `SKILL.md` 加上 `disable-model-invocation: true`
- OpenCode 把它们投影到 `cognitive-skills/`，不进 Skill discovery
- 人侧发现入口是生成的 workflow slash（`/uo-init`、`/uo-query`、`/tg-plan`、`/ce-apply`、…）
- Action prepare 把该 Action 的 **METHOD.md** 物化进 lease bundle；`Agent.skill_ids` 只是 refs 授权上限，不拼接 SKILL 正文
- 纯确认（`primary_interactive`）不装载认知 Skill

不要把通用 `/implement`、`/tdd`、第二份 `code-review` 写进 `skill_ids`。工程主流程已经嵌进现有 CE：grilling → `/ce-intent`（冻结 `ce/intent/plan.md`），改码 → `/ce-apply`（对齐 plan / `ce/apply/todo.md`），双轴审查 → 并行 spec/standards 子代理（结论默认在会话中陈述，用户要落盘才写报告），交接 → `/ce-handoff`。`/ce-impact` 写出 `tg_plan_intent.yaml` 给 `/tg-plan` 消费。

## Writing

改认知 skill 时遵守：正向完成条件、指针质量、`SKILL.md` ≤200 行、METHOD/prompt 禁止 harness 泄漏（`finalize` / `run_id` 等）。词表用 `agents/CONTEXT.md`。
