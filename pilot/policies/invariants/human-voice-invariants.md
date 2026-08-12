# Human-voice invariants（对用户出口）

面向**人**的文案必须同时说清三件事：

1. **意图**：产品目标（不是 workflow id）
2. **动作**：刚做完 / 正在做的事
3. **决策后果**：若需人选，选 A/B 后会发生什么

人话 ≠ 把英文字段译成中文同义词。

## 必须遵守的出口

| 出口 | 要求 |
| --- | --- |
| Primary 阶段总结 | 三句式：目标 / 刚完成 / 下一步或需要你 |
| AskQuestion | 标题人话；正文含背景 + 决定 + 选项后果；选项为人话动词短语 |
| ACP `message_zh` / `user_summary_zh`（给人看） | 白话；机器字段留在 payload |
| Todo / phase `label_zh` | 名实一致（勿叫「意图确认」却不问） |
| Goal 进度 | 「全量覆盖 i/n：正在…」 |
| failure_card | 先 `【给你】` 白话摘要，再保留结构化细节 |

Subagent → Primary 的机器回执可保留结构；**Primary 转述给用户时必须翻译**。  
Spec / lease / authorize 内部日志不要求人话。

## 表达模板

进度 / 总结：

```text
【目标】…
【刚完成】…（含规模数字若有）
【下一步】… ／ 【需要你】…（决策 + 选了会怎样）
```

征求决策：见 `ascendc_pilot.human_voice.decision_question`。

## 禁黑话（用户可见原文禁止）

`reads` / `exactness` / `binding_inventory` / `conditional_pass` / `status=None` /
`OUTPUT_CONTRACT_*` / `GAP-00x` 作标题 / `semantic_bind` / `entity_id` /
`HumanDecisionReceipt` / 裸 `tg-init` 当唯一说明（可写「建立覆盖合同（tg-init）」括号附注一次）/
不解释的 `T=D`（应写「覆盖全部合法 Key」）。

实现与检查：`pilot/ascendc_pilot/human_voice.py`（`contains_banned_jargon`）。
