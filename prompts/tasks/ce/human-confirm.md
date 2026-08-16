<task>
向用户展示已审变更计划，并请求明确确认。
</task>

<context>
- Intent: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/intent/intent.yaml`
- Feature plan: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/intent/feature_decomposition.yaml`
- Plan review: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/intent/plan_review.yaml`
</context>

<instructions>
1. 简要列出范围、关键锚点、验收条件和未决风险。验收应对得上后续 UT/ST/精度/profiling 收据，而不是「看起来没问题」。
2. 弹出 AskQuestion；选项必须原样使用控制面返回的 `ask_question.options`。
3. 只有用户明确确认后才完成本步；不得推断同意，不要自行提交正式确认。
4. 用户要求修改时保持未确认并说明需要回到的阶段。
</instructions>

<output>
不写文件。不要自行提交正式确认。
</output>
