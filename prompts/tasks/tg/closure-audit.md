# Task

Bundle identity is authoritative. Do not replace identity from other artifacts.

审计 TilingKey 闭环是否满足可签发条件。

# Targets

`<TARGET_IDS_OR_FILES>`

# Context

- Project root: `<PROJECT_ROOT>`
- UO root: `<UO_ROOT>`
- TG root: `<TG_ROOT>`
- Topic: `<TOPIC>`
- Context pack: `<CONTEXT_PACK_PATH>`

# Method

遵循 `skills/domain/tg-closure/SKILL.md`（审计视角）与 `references/certificate.md`。
验证 R/E 不变量、证书可 replay、与当前 R 无冲突；不发明新排除规则。

# Done when

给出通过/退回及理由；合同 `closure-audit-v1`（以 Bundle 为准）。
