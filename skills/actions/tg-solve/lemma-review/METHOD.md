# 引理资格审查

## Goal

对 `lemma_mine` 的 staging 候选做资格审查；只接受可进 E 的 sound 等级。不写 E。

## Input Interpretation

仅处理 `acp next` 提供的当前 unresolved / target 子集与上下文包。
优先读取同批 `tg-closure lemma-evidence` 产出的证据包（若存在）。

## Domain Procedure

1. 定位证据包：优先 `lead.evidence_path` → `tg/closure/lemmas/evidence/<lead_id>.yaml`；兼容 context pack 显式路径。
2. 对每个 staging 候选做**填空式**审查（缺项则 reject / defer，不得臆造）：

| 字段 | 要求 |
| --- | --- |
| `grade` | 仅 `source_lemma` / `solver_derived` |
| `proof.entry_branches_checked` | true，且 `evidence_entry_ids` 含入口/分流条目 |
| `proof.early_returns_checked` | true，且引用 early-return 条目 ID |
| `proof.all_writers_checked` | true，且引用全部赋值点条目 ID |
| `proof.execution_order_checked` | true |
| `proof.exception_branches_checked` | true |
| `certificate` / `combo_evidence` | 非空；引用证据包条目，不引用包外臆造行号 |

3. 反例：候选 `when` 不得命中当前 R（引擎也会验；审查侧先拒）。
4. 溯源：每条 accept 必须能指向构造→回放观测（REWRITE/REFUSE）；仅有 `construct_reasons`/pair-mine → reject。
5. 写 `review.yaml`；**不**写 `excluded.txt` / `active_rules.yaml`（那是 `lemma_apply`）。

## Domain Decisions

- 证据硬规则见 policy `evidence` 与 capability `tilingkey-closure`（LEMMA/PROOF），勿复述。
- 有证据包却无 `evidence_entry_ids` → 不得 accept（certificate 会 warning；审查应 reject）。
- 无 oracle 观测的「源码看起来不可达」→ reject。

## Output

- 合同 id：`lemma-review-v1`
- 不得写声明外路径。

## Cannot Decide

- 证据不足 → unresolved / needs_human
- 缺工具或 gate 前置 → 停止并回报 blocking reason

本文件不得描述 Pilot advance、complete 或其他阶段。
