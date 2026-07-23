---
name: understand-operator
description: >-
  AscendC 算子 KB 命令路由器。用户只说 understand-operator 未给子命令时用。
  优先引导 /uo-init | /uo-query | /uo-update | /uo-diff | /uo-code-review。
disable-model-invocation: true
argument-hint: "use /uo-init | /uo-query | /uo-update | /uo-diff | /uo-code-review"
---

# Skill: understand-operator

## Purpose

模糊入口 → **路由到唯一子 skill**（本文件不做建库/查询/更新本体）。

## Trigger

- 适用：用户说 `understand-operator` 但未指定子命令
- 不适用：已明确 `/uo-init` / `/uo-query` / `/uo-update` / `/uo-diff` / `/uo-code-review`（直接 Follow 对应 skill）

## Inputs

- 用户自然语言意图
- 可选：算子路径、是否已有 `$UO_ROOT`

## Outputs

- 明确告知应使用的子命令，并 **Follow** 对应 `SKILL.md`
- **禁止：** 在本 skill 内直接跑完整建库/查询流水；禁止在本目录发明脚本路径

## Invariants

- 旧单体 `/understand-operator` 流水线已退役
- 脚本唯一位置：`$PLUGIN_ROOT/engines/uo/uo/scripts`（见 `PATHS.md`）
- 用户可见语言默认中文（`prompts/common/language.md`）

## Tool Policy

### MUST use

- 按下表路由并 Read 目标 skill

### MUST NOT

- 在本 skill 托管 `.py` wrapper
- 猜测子命令后跳过目标 skill 的门禁

## Workflow

### Phase 1: 识别意图

| 用户意图 | Follow |
|---|---|
| 建库 / 初始化 / `/uo-init` | `../uo-init/SKILL.md` |
| KB 问答 / 绑定 KEY / `/uo-query` | `../uo-query/SKILL.md` |
| 增量刷新 / 要 `diff/` / `/uo-update` | `../uo-update/SKILL.md` |
| 只要变更摘要 / `/uo-diff` | `../uo-diff/SKILL.md` |
| 缺陷或需求审查 / `/uo-code-review` | `../uo-code-review/SKILL.md` |

### Phase 2: 移交

- **Exit：** 已打开并遵循目标 skill；本 router 结束
- **Failure：** 意图不清 → 列出上表请用户选择（`INVALID_INPUT`）

## Semantic Escalation

无。语义工作全部在目标 skill 内按各自 Tool Policy 执行。

## Failure Taxonomy

`INVALID_INPUT` · `UNKNOWN_INTENT`

## Quality Gate

- [ ] 已路由到恰好一个子 skill（或已请用户澄清）
- [ ] 未在本 skill 内伪造流水线产物

## Stop Conditions

- 意图无法唯一映射 → **STOP** 并列出命令表
