# Skills layout

Cognitive skills（五个，缺一不可——闭合集合，不承担自然语言编排）：

| # | id | 用途 |
| --- | --- | --- |
| 1 | `operator-analysis` | UO CodeMap 建库（`/uo-init` `/uo-update`）、查询与调查 |
| 2 | `testcase-generation` | TG harness 绑定、覆盖规划与闭环 |
| 3 | `source-proof` | 源码引理 / 不可达证明 |
| 4 | `code-review` | `/ce-review` 只读检视（Spec / Standards 两轴） |
| 5 | `code-engineering` | `/ce-plan` `/ce-apply` `/handoff`：命名计划、按 todo 改码、会话交接 |

| Kind | Path | Notes |
|------|------|-------|
| Cognitive skills | `skills/<id>/` | Self-contained `SKILL.md` + `references/` + `examples/` |
| Action METHOD | `skills/<id>/capabilities/<cap>/METHOD.md` | One LLM Action reasoning playbook. Spec `action_method_id="{skill}/{capability}"`. Prepare fail-closed if missing. Not for routers or engines. |
| Workflow spec | `pilot/ascendc_pilot/workflows/*.py` | 4+3+3 workflow 的状态、I/O、Action、gate 与可执行约束 |
| Primary routing | `agents/ascendc-pilot.yaml` + `pilot/ascendc_pilot/router/` | 显式 slash 确定性；自由 NL 由 Primary 写 Todo 再按格 `pilot_run`，Router 不做业务语义分类 |
| Shared language | `agents/CONTEXT.md` | Compose 进 invariant pack；跨 UO/TG/CE 同名词表 |
| Templates | `skills/testcase-generation/templates/` | Structure-only snippets (not worked examples) |
| Authoring shared refs | `knowledge/shared-references/` | SSOT；默认五份投影到四个 skill（**不要**塞进 `code-engineering`）。`harness-oracle.md` **只**投影到 `testcase-generation` |
| Shared | `skills/_shared/` | **已删除，勿再添加。** 运行时不要复活；authoring SSOT 在 `knowledge/` |

Each cognitive skill must ship ≥2 worked example case directories under `examples/<case>/` with `README.md`, `input/`, `expected/`.

## Control plane

不存在第六个 `workflow-orchestration` skill，也不存在 Golden NL / 关键词路由。

- 用户显式 `/uo-*` `/tg-*` `/ce-*`：Router 精确 dispatch，只运行该 workflow。
- 自由 NL：Primary 按「有什么 → 要什么 → 缺什么产物」写出有序 OpenCode Todo；一格对应一个可 `pilot_run` 的 slash（「获取 PR 代码」走 Engine acquire，不是 slash）。Runtime 只执行当前格。非 primary 不得再派 Task；`/ce-review` 双轴与复杂 `/uo-query` 留在主线。意图只是一次审查或一次查询时不要再包 coordinator。
- `host_step.done`：返回 Primary，勾掉当前格再 `pilot_run` 下一格。Host 不得 `continue_goal` 跨用户 slash。
- PR URL：Engine 建立隔离 exact-head workspace，返回 worktree / changed-files 事实。若路径令牌唯一确定算子目录 × architecture，将该对作为事实交回 Primary（可写 `pr_arch_pin`）。禁止 `selected_by: pr_changed_files` 静默自动开 `/uo-init`。多目标仍 AskQuestion。
- CE/TG 需要算子语义时统一 `/uo-query`（producer 只用 `pilot_cli`，禁止嵌套 Task）。
- 派发前写清算子路径、architecture、有无测试脚本；不确定先问人。occupancy 不冲突可并行。

## Invocation

Cognitive skills 是 **method bundle**，不是 Host 发现的 slash：

- Cursor / Codex compose 会给认知 `SKILL.md` 加上 `disable-model-invocation: true`
- OpenCode 把它们投影到 `cognitive-skills/`，不进外部 Skill discovery
- 人侧发现入口是生成的 workflow slash（`/uo-init`、`/uo-query`、`/tg-plan`、`/ce-apply`、…）
- Action prepare 把该 Action 的 **METHOD.md** 物化进 lease bundle；`Agent.skill_ids` 只是 refs 授权上限，不拼接 SKILL 正文
- 纯确认（`primary_interactive`）不装载认知 Skill

不要把通用 `/implement`、`/tdd`、第二份 `code-review` 写进 `skill_ids`。工程主流程：grilling → `/ce-plan`（写出 `ce/plan/{slug}_plan.md`），改码 → `/ce-apply`（按该 md 未完成 todo，也可按 tg-plan gap 说明书改测试脚本），双轴审查 → `/ce-review`（对话不落正式 review 产品），交接 → `/handoff`。验证走 `/tg-plan`：核心输入是 `tg/init.yaml` + 已确定 Planning Context（`/ce-review` 结论、`{slug}_plan.md`「测试内容」、用户已陈述范围、handoff、或只要用例时主控综合的 `/uo-query` 结论）。

## Writing

改认知 skill 时遵守：正向完成条件、指针质量、`SKILL.md` ≤200 行。稳定 Action procedure 放 METHOD；Prompt 只保留 invocation-specific input/output/delta；确定性 invariant 放 Engine/Checker。词表用 `agents/CONTEXT.md`。
