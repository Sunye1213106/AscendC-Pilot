# 收集引理源码证据包

## Goal

对 `lemma_leads` 产出的每条 observation lead，确定性收集 Codemap / 源码证据条目，写入正式证据包供 mine / review 填空引用。

## Input Interpretation

仅处理 `acp next` 提供的当前 unresolved / target 子集与上下文包。  
优先读取：`tg/closure/lemmas/leads.yaml`。

## Domain Procedure

1. 读取 `leads.yaml`；只处理 `source: oracle_observation` 且含 `when` / `combo` 的 lead。
2. 对每条 lead 调用 `lemma_evidence.collect(combo, lead_id=...)`。
3. 写正式产物：`tg/closure/lemmas/evidence/<lead_id>.yaml`（及同名 `.json`）。
4. 回写 `lead_id → evidence_path` 到 `leads.yaml`；写 `evidence_receipt.yaml`。
5. 无 lead 时写空 receipt，不发明证据。

## Domain Decisions

- 证据条目 ID 必须稳定（`EV_…`）；review / certificate 只能引用包内 ID。
- 本步是 deterministic preprocessing，不写 E，不做资格审查。

## Output

- 合同 id：`lemma-evidence-v1`
- 不得写声明外路径。

## Cannot Decide

- leads 缺失或非法 → 停止并回报 blocking reason

本文件不得描述 Pilot advance、complete 或其他阶段。
