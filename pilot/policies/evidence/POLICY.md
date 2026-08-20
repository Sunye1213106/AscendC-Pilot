# Policy: evidence

## 目的

所有关键语义结论必须可追溯、可验证。证据不足时保持未解决，不允许通过猜测闭合。

本策略对所有语义 Action / Agent 生效。Skill 可以增加约束，但不得弱化、复制或建立例外。

## 规则

1. 关键结论必须有可验证证据，例如源码位置、UO 关系、确定性分析产物或 KB 引用。

2. search、候选结果、命名、score 只用于定位，不能单独证明语义。

3. `confidence: high` 不是模型主观判断。只有证据满足验证条件后才能成立。

4. 标记 `source_verified: true` 时，必须能够定位到真实源码窗口，并同时具备：
   - `evidence_files`
   - `evidence_lines`
   - `evidence_window_sha256`
   - 连续真实源码 `evidence_snippet`
   - `decision_reason`

5. `sha`、源码范围和 `snippet` 必须属于同一个源码窗口。禁止拼接 snippet、复用其他候选的 sha、使用占位证据或编造证据。

6. 推断必须明确保持为推断。证据不足时使用 `unresolved`、`partial`、`unknown`、`needs_binding` 或 `needs_human`，不得猜测闭合。

7. `true / false`、字段 pin、`PROVEN_UNREACHABLE`、branch lemma、`not_input_derivable` 等会缩小语义空间的结论，必须经过高等级证据验证。

8. `mark_missing` 必须有机器可验证的 negative evidence，并证明检查范围完整。score 低、搜索不到、样本未出现不能单独作为 missing 依据。

9. 确定性工具可以补全、校验或修复证据，但不得凭空生成语义结论。

10. 所有 Action 和 Agent 使用同一套证据规则。

## 硬约束

- 没有证据，不得闭合。
- 定位结果不等于证明结果。
- 未验证结论不得标记 `high` 或 `source_verified`。
- 不得编造 path、line、hash、KB 节点、snippet 或其他证据。
- 证据不足必须保留未解决状态。
- 下游不得通过特判掩盖上游证据缺口。
