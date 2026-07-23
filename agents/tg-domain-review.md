---
name: tg-domain-review
type: subagent
description: >-
  RETIRED as user entry. Binding/domain orchestration lives in /tg-init.
  Follow prompts/init/dispatch.md and skills/tg-init/SKILL.md.
---

# Agent: tg-domain-review（兼容指针）

绑定与域确认已并入 **`/tg-init`**。

- 编排权威：`skills/tg-init/SKILL.md`
- 派发合同：`prompts/init/dispatch.md`
- 升级细则：`skills/tg-init/references/tg-uo-query-escalation.md`

父代理应：Task Follow `uo-query` → `tg-init --merge-uo-resolve` →
`--verify-csv-closure` → `tg-init-audit` → `--confirm`。

**MUST NOT** 再把本 agent 当作用户必经命令或第二套编排权威。
