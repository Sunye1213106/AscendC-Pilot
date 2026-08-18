# CE：代码工程

CE（Code Engineering）在已有 Operator CodeMap 上做两件不要混用的事：**自己有需求时写出命名计划并改码**，以及**已有代码改动时做只读审查**。验证不在 CE：引导 `/tg-plan`。CE **不写任何 yaml**；正式产物只有 markdown。

两条场景：

| 场景 | 入口 | 不以什么为输入 |
| --- | --- | --- |
| 自己有需求，还没改码 | `/ce-plan` → `/ce-apply` | 不以 PR / diff 为输入 |
| 已有 PR 或工作区 diff | `/ce-review` | 不以设计改码为职责 |

`/handoff` 无 `ce-` 前缀，整理当前会话。旧 `/ce-intent` `/ce-impact` `/ce-verify` `/ce-handoff` 已删除。

## 正式产物

| 何时 | 写什么 |
| --- | --- |
| `/ce-plan` 确认后 | `.ascendc-pilot/<arch>/ce/plan/{slug}_plan.md` |
| `/handoff` | `.ascendc-pilot/<arch>/session_handoff.md` |
| `/ce-apply` | 算子源码；可勾选当前计划里的 `- [ ]` |
| `/ce-review` | 不落盘。结论留在对话 |

Grill 草稿只写 `runs/<run>/actions/intent_grill/` 下的 markdown。形状参考 `skills/code-engineering/examples/deter-band-schedule_plan.md`。

`/tg-plan` 自己从计划的「测试内容」节、同一会话的 review 对话、或 `session_handoff.md` 总结义务。不要等 CE yaml。

## 工作流

| 入口 | Skill |
| --- | --- |
| `/ce-plan`、`/ce-apply`、`/handoff` | `skills/code-engineering/` |
| `/ce-review` | `skills/code-review/` |

语义只走 `pilot_cli uo-query` 四种形态（标识符 / `Dim=V` / `--file --line` / 无参数索引）。不要传 `--mode`。禁止 `explain-*`、`search`、`locate`。LLM 禁止写 `.uo`；apply 刷图由引擎嵌套 `uo-update`。apply 不查图；查图是 plan / review。

### `/ce-plan`

```text
kb_ready [D] → grill [S ce-analyst] + [D] promote + [H]
           → draft [S] 写出 {slug}_plan.md → confirm [H] 去 apply 或继续改
```

持续 grill，直到范围、不做的事、测试内容够写计划。事实自己查 CodeMap，决策问人。不以 PR 为输入。

计划必须有：实现分析、分步计划、可勾选 todo、测试内容。文件路径写进反引号，便于 apply 收集声明文件集。

### `/ce-apply`

```text
gate [D] 当前计划有未完成 - [ ]
  → patch [S ce-applier] 一次一条 todo
  → guard [D] 改动落在计划声明的文件内
  → refresh [D] 嵌套 uo-update
  → report [H] 建议审查 / 建议测试 / 回计划 / 交接
```

没有未完成 todo 则先 `/ce-plan`。不内嵌双轴审查。验证走 `/tg-plan`。

### `/ce-review`

```text
scope [D] 从 intent 抽出 GitCode/GitHub PR URL。必须在对应算子仓打开且已有 `.uo`；向已配置且匹配的 remote fetch（禁止把用户 URL 加成 remote）；失败则在允许的主机上用 HTTPS 拉 patch（需 `GITHUB_TOKEN` / `GITCODE_TOKEN`），并按算子 pathspec 裁剪。有 PR URL 时禁止退回工作区 dirty tree。无 diff 则停。
  → review [S ce-reviewer ×2] Spec ∥ Standards
  → summary [H] 建议修改或建议测试
```

occupancy 为 `shared`。不写 `ce/review/`。有 `{slug}_plan.md` 时 Spec 轴对照计划；没有则只陈述变更理解。建议测试时 TG 读本轮对话。

### `/handoff`

```text
session [S ce-analyst] 写 session_handoff.md
```

只引用已有产物路径和下一步 slash，不把 `{slug}_plan.md` 全文抄进总结。

## occupancy

`ce-plan` / `ce-apply` 为 exclusive 组；`ce-review` 与 `handoff` 为 shared。apply 刷图另抢 `uo` 锁。

CodeMap 缺失或过期时先 `/uo-init` 或 `/uo-update`。跨层结构用四种 `uo-query` 形态，不要让子任务自行猜测 `.uo` 路径。

实现入口：`engines/code-engineering/code_engineering/`；工作流合同在 `pilot/ascendc_pilot/workflows/ce_specs.py`。
