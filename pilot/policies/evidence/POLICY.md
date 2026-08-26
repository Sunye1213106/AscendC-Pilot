# Policy: evidence

关键结论必须可追溯。查到 ≠ 已证明。证据不足必须显式 unresolved，不得猜测闭合。

1. 搜索 / 候选 / 命名 / score 只用于定位，不能单独证明语义。
2. `confidence: high` / `source_verified: true` 必须同时具备该窗口的 `evidence_files`、`evidence_lines`、`evidence_window_sha256` 与连续 `evidence_snippet`（窗口子串），以及 `decision_reason`。sha、范围和 snippet 必须属于同一窗口。禁止编造或拼接。
3. 会缩小语义空间的结论（字段 pin、`PROVEN_UNREACHABLE`、branch lemma）必须达到上一条。`partial` 不能单独证伪。
4. `mark_missing` 必须有机器可检查的否定证据，并证明检查范围完整。score 低或「搜了很多」不够。
5. 确定性工具可以补全或校验证据，不得凭空生成语义结论。下游不得用特判掩盖上游缺口。
