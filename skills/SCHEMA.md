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
| Primary routing | `agents/ascendc-pilot.yaml` + `pilot/ascendc_pilot/router/` | 显式 slash 确定性；自由 NL 由 Primary 直接形成 Task Plan，Router 不做业务语义分类 |
| Shared language | `agents/CONTEXT.md` | Compose 进 invariant pack；跨 UO/TG/CE 同名词表 |
| Templates | `skills/testcase-generation/templates/` | Structure-only snippets (not worked examples) |
| Authoring shared refs | `knowledge/shared-references/` | SSOT；默认五份投影到四个 skill（**不要**塞进 `code-engineering`）。`harness-oracle.md` **只**投影到 `testcase-generation` |
| Shared | `skills/_shared/` | **已删除，勿再添加。** 运行时不要复活；authoring SSOT 在 `knowledge/` |

Each cognitive skill must ship ≥2 worked example case directories under `examples/<case>/` with `README.md`, `input/`, `expected/`.

## Control plane

不存在第六个 `workflow-orchestration` skill，也不存在 Golden NL / 关键词路由。

- 用户显式 `/uo-*` `/tg-*` `/ce-*`：Router 精确 dispatch，只运行该 workflow。
- 自由 NL：Primary 根据用户目标、已有产物与 workflow description 一次形成有序 Task Plan；Runtime 只保存、验证与推进，不解释用户语义。
- `host_step.done`：若 Task Plan 有后继 workflow，直接继续该 step，不回到原始 NL 重路由。
- PR URL：source utility 建立隔离 exact-head workspace，确认 operator/architecture；PR 测试链由依赖约束保证 `uo-init → ce-review → tg-init → tg-plan → tg-solve`。
- CE/TG 需要算子语义时统一 `/uo-query`。

## Invocation

Cognitive skills 是 **method bundle**，不是 Host 发现的 slash：

- Cursor / Codex compose 会给认知 `SKILL.md` 加上 `disable-model-invocation: true`
- OpenCode 把它们投影到 `cognitive-skills/`，不进外部 Skill discovery
- 人侧发现入口是生成的 workflow slash（`/uo-init`、`/uo-query`、`/tg-plan`、`/ce-apply`、…）
- Action prepare 把该 Action 的 **METHOD.md** 物化进 lease bundle；`Agent.skill_ids` 只是 refs 授权上限，不拼接 SKILL 正文
- 纯确认（`primary_interactive`）不装载认知 Skill

不要把通用 `/implement`、`/tdd`、第二份 `code-review` 写进 `skill_ids`。工程主流程：grilling → `/ce-plan`（写出 `ce/plan/{slug}_plan.md`），改码 → `/ce-apply`（按该 md 未完成 todo），双轴审查 → `/ce-review`（对话不落正式 review 产品），交接 → `/handoff`。验证走 `/tg-plan`：核心输入是 `tg/init.yaml` + 已确定 Planning Context；PR 测试 flow 中该上下文来自 `/ce-review` 的 changed/affected scope、risks、test intent 和 validation targets。

## Writing

改认知 skill 时遵守：正向完成条件、指针质量、`SKILL.md` ≤200 行。稳定 Action procedure 放 METHOD；Prompt 只保留 invocation-specific input/output/delta；确定性 invariant 放 Engine/Checker。词表用 `agents/CONTEXT.md`。
