# Task

Bundle identity is authoritative. Do not replace identity from other artifacts.

对给定目标做源码级代码审查，报告有证据的缺陷或明确未确认/未决项。

# Targets

`<TARGET_IDS_OR_FILES>`

# Context

- Project root: `<PROJECT_ROOT>`
- UO root: `<UO_ROOT>`
- TG root: `<TG_ROOT>`
- Topic: `<TOPIC>`
- Context pack: `<CONTEXT_PACK_PATH>`

# Method

遵循 `skills/domain/code-review/SKILL.md`。先 Codemap/KB 定位，再读必要源码。

# Done when

每个目标给出 `FINDING` / `NO_CONFIRMED_ISSUE` / `UNRESOLVED`；输出符合合同 `code-review-v1`。
