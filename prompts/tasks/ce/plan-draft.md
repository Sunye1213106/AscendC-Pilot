<task>
根据当前用户需求写出命名 CE plan。
</task>

<inputs>
- 用户当前需求：见本轮对话
- 当前计划（若有）：`<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/plan/`
- UO：`<UO_ROOT>`（由当前 Action lease 提供）
- Domain knowledge：见 session method 指针
- Shape reference: session refs 中的 deter-band-schedule 例
</inputs>

<output>
写入 `ce/plan/{slug}_plan.md`。
若存在影响文件集的未决决策，保留为 unresolved。
</output>
