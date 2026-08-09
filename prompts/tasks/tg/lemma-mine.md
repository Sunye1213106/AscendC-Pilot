# Task

Bundle identity is authoritative. Do not replace identity from other artifacts.

证明或反驳指定的 TilingKey 引理 leads。

# Targets

`<TARGET_IDS_OR_FILES>`

# Context

- Project root: `<PROJECT_ROOT>`
- UO root: `<UO_ROOT>`
- TG root: `<TG_ROOT>`
- Topic: `<TOPIC>`
- Context pack: `<CONTEXT_PACK_PATH>`
- Leads: 仅消费封闭 lead 包（勿发明 lead）
- Evidence: 同批 evidence pack（若有）

# Method

遵循 `skills/domain/source-lemma-proof/SKILL.md`。
对每条 lead：关闭证明义务、主动寻反例、仅用源码证据做排除向结论。
返回 `PROVED` / `REFUTED` / `INSUFFICIENT`（不要自行映射排除集等级）。

# Done when

每条 lead 有证书摘要；产物写入本 Action 声明的 staging 范围；合同 `lemma-mine-v1`。
