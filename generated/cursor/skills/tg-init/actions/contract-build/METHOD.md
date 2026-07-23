# contract_build — 确定性合同骨架（Harness 托管）

> 勿在本文件推进 Harness 阶段；只执行 `harness next` 给出的 `contract_build`。

## Purpose

从测试脚本 / CSV 消费端目录动态抽取 CSV 合同、realization map、binding inventory 与
`llm_bind_prompt_bundle`。本 Action 由 `deterministic-tg-engine` 执行，不经 LLM。

## Inputs

- 定稿 UO KB
- `test_script_root` / `csv_consumer_root`（缺失则 `TEST_SCRIPT_ROOT_REQUIRED`）

## Procedure

1. Harness `run-action contract_build` 自动调用确定性 Engine。
2. Engine 解析消费端脚本表头、读写逻辑、默认值与枚举。
3. 写出 `tg/snapshot/`、`tg/realization/realization_map.yaml`、`binding_inventory.yaml`、
   `llm_bind_prompt_bundle.yaml`、`binding_gaps.yaml` / `unresolved.yaml`。
4. 证据不足处保留 gap，不得发明列名或 KEY。

## Output

- 合同 id：`csv-contract-v1`
- 下一步：若 `unresolved.status=ready_for_llm` → `semantic_bind`；否则可进入 merge。
