<task>
回答用户对已有 AscendC Operator CodeMap（`.uo`）的问题。只读，不改正式 CodeMap。
</task>

<input>
先读 session `method.md`（若 stub 点名了）。用户问题见 stub「USER QUESTION」。
用 `acp uo-query --project <算子绝对路径>` 查图，查询完成后立即作答。Host cwd 是 Pilot 仓，不要只写算子名。
</input>

<delta_constraints>
1. 按 METHOD 的参数形态调用：标识符、Dim=V、`--file --line`、或无参数索引。不要传 `--mode`。若 USER QUESTION 含 FOCUS，只答该片。建议的首次调用先执行，再跟卡片 `next` / `hint`。
2. 卡片已带 file:line + snippet 视为已 Read，不要再 Read 同一段。路径从卡片 `file` / `next` 复制，禁止猜相对路径。空结果按 `hint` 再查。不要仓级 findstr。图不够再开最小源码窗。
3. 最终消息用完整自然语言作答（file:line + 必要 snippet）。不要只输出 YAML。文末可附很短 `kb-answer-v1` 状态头。不写文件，不推进工作流。
</delta_constraints>

<output>
完整自然语言答案（结论 + file:line + 必要 snippet）。不要把答案压缩为 YAML。
文末可选很短 `kb-answer-v1` 状态头（status / adequacy / citations）。
</output>
