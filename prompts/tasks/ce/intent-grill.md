<task>
把已记录的变更意图问到可写计划：范围、不做的事、侧别和测试内容。
</task>

<inputs>
- UO product root: `<UO_ROOT>`
- Draft root: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/intent_grill`
</inputs>

<output>
写入本步 markdown 草稿（本 action 目录下的 md，可拆 parts）。事实走 `uo-query`，不要问人位置问题。
仅当存在会分出两条合法实现方向的决策时列出 3–5 题。不要写 yaml。
</output>
