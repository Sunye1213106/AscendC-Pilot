<task>
回答当前用户对已生成 AscendC `.uo` CodeMap 的问题。
</task>

<instructions>
1. 先使用最窄的 `CodeMapQuery` 接口定位实体、关系或路径。
2. 只有结构化证据不足时，才读取解决当前问题所需的最小源码窗口。
3. 结论按 `ANSWERED`、`PARTIAL` 或 `UNKNOWN` 标记证据充分度。
4. 不用节点共存推断关系；不跨越当前 BuildVariant / architecture 混用证据。
5. 若 unresolved 影响问题，明确指出受影响的关系和缺失证据。
</instructions>

<output>
直接回答用户问题。只附支撑结论所需的 provenance / source span；不要复述工作流、Skill 或无关背景。
</output>
