# semantic_bind — 有界语义绑定（Harness 托管）

> 勿在本文件推进 Harness 阶段；只执行 `harness next` 给出的 `semantic_bind`。

## Purpose

消化 `contract_build` 产出的 binding gaps。确定性 prepare 已给出候选与源码窗；
LLM 只在允许的候选内写补丁；Harness finalize 确定性应用补丁。

## 职责划分

| 阶段 | 执行者 | 产物 |
|---|---|---|
| prepare | deterministic engine（自动） | inventory / bundle / fingerprint / session |
| produce | `tg-semantic-bind` | `semantic_bind_patch.yaml` |
| finalize apply | deterministic (`apply_semantic_bind_patch`) | lexicon / unresolved / apply receipt |
| gate | `bind_progress` | 无假闭合 |

## Inputs（只读）

- `tg/realization/llm_bind_prompt_bundle.yaml`
- `tg/realization/binding_inventory.yaml`
- `tg/realization/binding_gaps.yaml` / `unresolved.yaml`
- bundle 内源码窗口

## Procedure（Producer）

1. 读取 prompt bundle 中的当前 gap / candidate 子集。
2. 对每个可确认 gap：选择 `candidate_id`，给出 `key_id` + `expr`（或 token / csv alias）。
3. **只**写入 `tg/realization/semantic_bind_patch.yaml`。
4. 执行 `harness run-action semantic_bind --finalize`（finalize 会应用补丁并校验）。

## Hard Constraints

- MUST NOT：全仓自由搜索；发明未在候选或源码窗中的字段/表达式
- MUST NOT：空 `accept` / `select` 却标记 resolved
- MUST NOT：直接改 `binding_lexicon.yaml` / Harness state / 调用 advance
- MUST：证据不足 → 保留 gap，回报 blocking reason

## Output

- 合同 id：`semantic-bind-v1`
- Producer 写出：`semantic_bind_patch.yaml`
- Finalize 更新：`binding_lexicon.yaml`、`unresolved.yaml`、`binding_gaps.yaml`、`semantic_bind_apply.yaml`
