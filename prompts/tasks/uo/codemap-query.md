<task>
回答用户对已有 AscendC Operator CodeMap（`.uo`）的问题。只读，不改正式 CodeMap。
</task>

<context>
先读 session `method.md`。用户问题见 stub「USER QUESTION」。
用 `acp uo-query --mode` 查图，查完就答。
</context>

<instructions>
1. 看问题选 mode（tiling_key / field / kernel_branch / locate / impact / …），直接查。
2. 图不够再开最小源码窗。不要为 path:line 而 Read。
3. 最终消息只输出一个 `kb-answer-v1` YAML。不写文件，不推进工作流。
</instructions>

<output>
```yaml
schema: kb-answer-v1
status: ANSWERED   # 或 PARTIAL / UNKNOWN
question: "<用户原问>"
answer_zh: |
  <verdict + path:line>
citations:
  - path: op_host/.../file.cpp
    lines: "1581-1650"
adequacy: ANSWERED
```

未找到：`UNKNOWN` + `reason_code: NOT_FOUND_IN_SCOPE`。
</output>
