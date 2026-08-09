# Task

Bundle identity is authoritative. Do not replace identity from other artifacts.

Replay 引理 producer 的证明证书并给出裁决。

# Targets

`<TARGET_IDS_OR_FILES>`

# Context

- Project root: `<PROJECT_ROOT>`
- UO root: `<UO_ROOT>`
- TG root: `<TG_ROOT>`
- Topic: `<TOPIC>`
- Context pack: `<CONTEXT_PACK_PATH>`
- Lemma evidence pack: `<LEMMA_EVIDENCE_PATH>`
- Staging candidates: producer 声明的 staging 路径

# Method

遵循 `skills/domain/source-lemma-proof/SKILL.md`，并必读 `references/referee-replay.md`。
只 replay 证书；禁止自由开新 hypothesis。

# Done when

每条候选 `accept` / `reject` / `defer`；合同 `lemma-review-v1`。
