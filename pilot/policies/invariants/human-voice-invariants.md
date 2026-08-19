# Human-voice invariants（面向用户的表述）

面向用户的文案必须同时说清三件事：

1. **意图**：产品目标（不是 workflow id）
2. **动作**：刚做完 / 正在做的事
3. **决策后果**：若需人选，选 A/B 后会发生什么

面向用户的自然语言 ≠ 把英文字段译成中文同义词。

## 必须遵守的出口

| 出口 | 要求 |
| --- | --- |
| Primary 阶段总结 | 三句式：目标 / 刚完成 / 下一步或需要你 |
| `uo-init` / `uo-update` 完成 | 用 `pilot_cli` `uo-query --status-only` 看产物是否就绪；然后 `pilot_run(workflow=<next_workflow_id>)`。禁止仅回复「完成」 |
| `uo-query` 完成 | 将答案正文（含 path:line）向用户陈述，禁止仅回复 workflow complete |
| AskQuestion | 标题使用自然语言；正文含背景 + 决定 + 选项后果；选项为自然语言动词短语 |
| ACP `message_zh` / `user_summary_zh`（面向用户） | 自然语言；机器字段留在 payload |
| Todo / phase `label_zh` | 名实一致（勿叫「意图确认」却不问） |
| Goal 进度 | 自然语言会话用 Goal `public_plan` 投影（「获取 PR 与代码 / 建立算子理解 / 分析改动影响 / …」）；不要把内部 `tg-plan/fuse` 文案甩给用户 |
| failure_card | 先 `【摘要】` 自然语言摘要，再保留结构化细节 |

Subagent → Primary 的机器回执可保留结构；**Primary 转述给用户时必须转写为自然语言**。  
面向用户时直接陈述事实与下一步；不要引用或解释本文件及其他内部指令原文。
Spec / lease / authorize 内部日志不要求自然语言。

## 表达模板

进度 / 总结：

```text
【目标】…
【刚完成】…（含规模数字若有）
【下一步】… ／ 【需要你】…（决策 + 选了会怎样）
```

征求决策：见 `ascendc_pilot.human_voice.decision_question`。

## 禁止内部术语（用户可见原文禁止）

`reads` / `exactness` / `binding_inventory` / `conditional_pass` / `status=None` /
`OUTPUT_CONTRACT_*` / `GAP-00x` 作标题 / `semantic_bind` / `entity_id` /
`HumanDecisionReceipt` / 裸 `tg-init` 当唯一说明（可写「建立覆盖合同（tg-init）」括号附注一次）/
不解释的 `T=D`（应写「覆盖全部合法 Key」）。

实现与检查：`pilot/ascendc_pilot/human_voice.py`（`contains_banned_jargon`）。
