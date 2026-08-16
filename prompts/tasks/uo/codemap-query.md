<task>
回答用户对已有 AscendC Operator CodeMap（`.uo`）的问题。只读，不改正式 CodeMap。
</task>

<context>
先读 session `method.md`。用户问题见 stub「USER QUESTION」。
用 `acp uo-query --project <算子绝对路径> --mode` 查图，查完就答。Host cwd 是 Pilot 仓，不要只写算子名。
</context>

<instructions>
1. 看问题选 **一个** mode（kernel 找不到 → `template_match` 再 `legal_key`；分核 → `field`；三相 → `kernel_launch`，禁止第一跳 `search ProcessVec`；名字 → `locate`），直接查。`--pattern`（`--query` 同义）。若 USER QUESTION 含 `SLICE_ID=` 或 `FIRST_QUERY:`，只答 FOCUS，只跑 stub 写明的 First mode / FIRST_QUERY。
2. 空结果按 `hint` 再查一次。不要仓级 findstr。图不够再开最小源码窗。不要为 path:line 而 Read。
3. 最终消息用完整自然语言作答（file:line + 必要 snippet）。OpenCode Task 原样交回主控。不要只输出 YAML。文末可附很短 `kb-answer-v1` 状态头。不写文件，不推进工作流。
</instructions>

<output>
完整自然语言答案（Cursor Explore 风格：结论 + file:line + 必要 snippet）。
不要把答案压进 YAML。文末可选：

```yaml
schema: kb-answer-v1
status: ANSWERED   # 或 PARTIAL / UNKNOWN
question: "<用户原问>"
adequacy: ANSWERED
citations:
  - path: op_host/.../file.cpp
    lines: "1581-1650"
```
</output>
