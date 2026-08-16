<task>
把已记录的变更意图问到可分解：范围、不做的事、侧别和可验证验收。
</task>

<inputs>
- Intent: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/intent/intent.yaml`
- UO product root: `<UO_ROOT>`
- Draft root: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/intent_grill`
</inputs>

<output>
写入本步草稿（parts）。事实走 CodeMap / `acp ro-search --scope run-source-scope`，不要问人。
仅当存在会分出两条合法实现方向的 material decision 时，列出 3–5 题；无分叉则空列表。
</output>
