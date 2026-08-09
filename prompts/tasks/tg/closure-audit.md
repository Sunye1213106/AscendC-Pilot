# Task

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

遵循 `skills/domain/tg-closure/SKILL.md` 与 `references/closure-safety.md`、`references/certificate.md`。
验证 R/E 不变量与证书可 replay；不发明新排除规则。

# Done when

给出通过/退回及理由。
