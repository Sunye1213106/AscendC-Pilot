# Skills 布局

认知 skill（五个，缺一不可——闭合集合，不承担自然语言编排）：

| # | id | 用途 |
| --- | --- | --- |
| 1 | `operator-analysis` | UO CodeMap 建库（`/uo-init` `/uo-update`）、查询与调查 |
| 2 | `testcase-generation` | TG harness 绑定、覆盖规划与闭环 |
| 3 | `source-proof` | 源码引理 / 不可达证明 |
| 4 | `code-review` | `/ce-review` 只读检视（Spec / Standards 两轴） |
| 5 | `code-engineering` | `/ce-plan` `/ce-apply` `/handoff`：命名计划、按 todo 改码、会话交接 |

| 种类 | 路径 | 说明 |
|------|------|-------|
| 认知 skill | `skills/<id>/` | 自包含 `SKILL.md` + `references/` + `examples/` |
| Action METHOD | `skills/<id>/capabilities/<cap>/METHOD.md` | 一份 LLM Action 推理手册。Spec `action_method_id="{skill}/{capability}"`。缺失则 prepare 失败关闭。不给 router 或引擎用。 |
| Workflow spec | `pilot/ascendc_pilot/workflows/*.py` | 4+3+3 workflow 的状态、I/O、Action、gate 与可执行约束 |
| 主控路由 | `agents/ascendc-pilot.yaml` + `pilot/ascendc_pilot/router/` | 显式 slash 确定性；自然语言输入由 Primary 写 Todo 再按格 `pilot_run`，Router 不做业务语义分类 |
| 共用词表 | `agents/CONTEXT.md` | Compose 进 invariant pack；跨 UO/TG/CE 同名词表 |
| 模板 | `skills/testcase-generation/templates/` | 只给结构片段（不是做过的例子） |
| Shared | `skills/_shared/` | **已删除，勿再添加。** 全局纪律在 `pilot/policies/`，不要复活共享引用目录 |

每个认知 skill 必须在 `examples/<case>/` 下提供 ≥2 个做过的用例目录，含 `README.md`、`input/`、`expected/`。

## 控制面

不存在第六个 `workflow-orchestration` skill，也不存在黄金步骤表 / 关键词路由。自然语言输入的编排见 `pilot/policies/invariants/intent-reasoning.md`。

- 用户显式 `/uo-*` `/tg-*` `/ce-*`：Router 精确 dispatch，只运行该 workflow。
- 自然语言输入：Primary 按产物缺口写出有序 OpenCode Todo；一格对应一个可 `pilot_run` 的 slash（「获取 PR 代码」走 Engine acquire，不是 slash）。Runtime 只执行当前格。
- `host_step.done`：返回 Primary，勾掉当前格再 `pilot_run` 下一格。Host 不得 `continue_goal` 跨用户 slash。
- PR URL：Engine 建立隔离 exact-head workspace，返回 worktree / changed-files 事实。路径令牌唯一确定算子目录 × architecture 时将该对交回 Primary。禁止 `selected_by: pr_changed_files` 静默自动开 `/uo-init`。
- CE/TG 需要算子语义时统一 `/uo-query`（producer 用 `pilot_cli`）。
- 第一轮 `auto` 省略 architecture；clone 之后才写清算子路径。测试仓等到 `/tg-init` 再问。

## 调用

认知 skill 是 **method bundle**，不是 Host 发现的 slash：

- Cursor / Codex compose 会给认知 `SKILL.md` 加上 `disable-model-invocation: true`
- OpenCode 把它们投影到 `cognitive-skills/`，不进外部 Skill discovery
- 人侧发现入口是生成的 workflow slash（`/uo-init`、`/uo-query`、`/tg-plan`、`/ce-apply`、…）
- Action prepare 把该 Action 的 **METHOD.md** 物化进 lease bundle；`Agent.skill_ids` 只是 refs 授权上限，不拼接 SKILL 正文
- 纯确认（`primary_interactive`）不装载认知 Skill

不要把通用 `/implement`、`/tdd`、第二份 `code-review` 写进 `skill_ids`。工程入口：grill → `/ce-plan`，改码 → `/ce-apply`，审查 → `/ce-review`，交接 → `/handoff`，验证 → `/tg-plan`（输入是 `tg/init.yaml` + Planning Context，词表见 CONTEXT）。

## 写作

改认知 skill 时遵守：正向完成条件、指针质量、`SKILL.md` ≤200 行。稳定 Action procedure 放 METHOD；Prompt 只保留本次调用的输入/输出/增量；确定性 invariant 放 Engine/Checker。词表用 `agents/CONTEXT.md`。属主与去重：`docs/architecture/agent-content-rules.md`。
