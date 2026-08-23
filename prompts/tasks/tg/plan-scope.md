<task>
弄清这次要测什么。像 uo-query：读对话和 `tg/init.yaml`，用自然语言回答。禁止 Write，不要交 YAML 文件。
</task>

<input>
- Init: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
- Optional intent: 用户这句话、`ce/plan/*_plan.md`、`session_handoff.md`
- Pin: `<PROJECT_ROOT>/.ascendc-pilot/control/change_contract.yaml`（只读；没有则不要 git diff HEAD）
- UO: `<UO_ROOT>`（只查询，不写）
</input>

<output>
最终消息直接回答：测哪条实现行为、什么条件下成立/不成立、还缺什么证据。不要 Write，不要交 `targets.yaml` / `plan.md`。Primary 读你的回答即可。
</output>
