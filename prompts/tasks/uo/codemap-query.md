<task>
回答用户对已有 AscendC Operator CodeMap（`.uo`）的问题。只读查询，不改写正式 CodeMap。
</task>

<context>
CodeMap 是 Host→TilingKey/TilingData→Kernel 的可追溯关系权威；你的结论必须能落回图证据或源码窗口。
方法细节见打包 Skill `operator-analysis`（勿假设 Host 物理路径）。
用户问题见本 prompt 的「User question」段，或 Task stub 中的 `USER QUESTION`。
</context>

<instructions>
1. 优先用最窄的 CodeMap / KB 查询（`acp uo-query`）定位实体、关系或路径。
2. 仅在结构化证据不足时，读取解决当前问题所需的最小源码窗口（`acp ro-search` / 窗口 Read）。
3. 不用“节点共存”推断关系；不跨 BuildVariant / architecture 混用证据。
4. 若 unresolved 影响问题，点名受影响关系与缺失证据；证据不足时标 `PARTIAL` / `UNKNOWN`，禁止猜测闭合。
5. **必须**把最终答案写入 lease 写面中的 `answer.yaml`（通常 `runs/<run_id>/actions/kb_lookup/answer.yaml`）。禁止写 `uo/checks/*`、禁止改 `.uo`。
6. 写完 `answer.yaml` 后，返回简短摘要即可；**禁止**自行 `--finalize`（由 Primary finalize）。
</instructions>

<output>
## answer.yaml（合同 `kb-answer-v1`，必写）

```yaml
schema: kb-answer-v1
status: ANSWERED   # 或 PARTIAL / UNKNOWN
question: "<用户原问>"
answer_zh: |
  <直接回答；先给 verdict，再列卡点/证据>
citations:
  - path: op_host/.../file.cpp
    lines: "1581-1650"
adequacy: ANSWERED   # 与 status 一致
```

## 聊天摘要
直接回答用户问题，勿复述工作流。每个事实结论附 `path:line` 或 `path:start-end`。充分度：`ANSWERED` | `PARTIAL` | `UNKNOWN`。
