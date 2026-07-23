# semantic_bind — 有界语义绑定（Harness 托管）

> 勿在本文件推进 Harness 阶段；只执行 `harness next` 给出的 `semantic_bind`。

## Purpose

消化 `contract_build` 产出的 binding gaps。确定性产物已给出候选与源码窗；
LLM 只在允许的候选内完成绑定，禁止全仓搜索或发明字段。

## Inputs（只读）

- `tg/realization/llm_bind_prompt_bundle.yaml` — 候选、上下文、评分
- `tg/realization/binding_inventory.yaml`
- `tg/realization/binding_gaps.yaml` / `unresolved.yaml`
- `tg/realization/binding_lexicon.yaml` — 当前 lexicon（写入目标）

## Procedure

1. 读取 prompt bundle 中的当前 gap / candidate 子集（仅处理 Harness 给出的 ID）。
2. 对每个 gap：从候选中选择 `candidate_id`，给出 `key_id` + `expr`（或 token / csv alias）。
3. 写入 `tg/realization/semantic_bind_patch.yaml`，然后调用：
   `testcase_agent.semantic_bind.apply_semantic_bind_patch(out_root)`。
4. 脚本校验：必须引用 bundle 候选；空接受 / 越界候选 / 无 lexicon 变化 → reject。
5. 成功后 `unresolved.status` 变为 `ready`（仍有 gap 则保持 `ready_for_llm` 供下一轮）。

## Hard Constraints

- MUST NOT：全仓自由搜索；发明未在候选或源码窗中的字段/表达式
- MUST NOT：空 `accept` / `select` 却标记 resolved
- MUST NOT：调用 harness advance / complete
- MUST：证据不足 → 保留 gap，回报 blocking reason

## Output

- 合同 id：`semantic-bind-v1`
- 更新：`realization/binding_lexicon.yaml`、`unresolved.yaml`、`binding_gaps.yaml`
