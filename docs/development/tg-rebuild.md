# TG 产物模型重建（2026-08-18）

这次不是在旧相位上打补丁。旧实现（`tilingkey_full_coverage` / T=D 默认、lemma/closure YAML 森林、init 旁路 YAML、scenario overlay 当 TG 模式）与「三份正式产物」冲突，**已删除，不再兼容**。有冲突的文件直接删，不留 shim。

对照失败会话：`uo-init` → `tg-init`（脚本仓在算子仓外）→ `tg-plan` 在 T=D 预检查上失败。根因是控制面被设成「全部合法 Key」，而不是脚本仓的列。

## 删掉什么

- 相位：`semantic_bind`、`init_audit`、`plan_intent`/`plan_build`、`lemma_*`、`closure_*`、`scenario_plan`、`contract_build`
- Agent：`tg-lemma-producer`、`tg-closure-referee`、`tg-init-audit`
- 引擎模块：`tg_plan_targets.py`、`tg_full_precheck.py`、`tg_compaction.py`
- Capability：旧合同骨架 `contract-building`（已从 `pilot/gates/` 删除）
- 产物：`tg/init/status.yaml`、`kb_fingerprint.yaml`、`audit_report.yaml`、`tg/plan/levels/**`、`tg/closure/**`、`binding_inventory.yaml`、`tg/plan/plan_intent.yaml`
- 默认模式：`tilingkey_full_coverage` / T=D。用户说「全量覆盖」仍可串联 init→plan→solve，但那是意图，不是 workflow overlay。
- 指纹权威：`init.yaml` 的 `uo_digest`，不再写 `init/kb_fingerprint.yaml`

Host replay 库（`HostOracle`、WSL replay、`tg-closure` CLI）保留，只作为 solve 的 Host tiling 回放，不再写 closure YAML 森林。

## 换成什么

| 阶段 | 一份正式产物 |
| --- | --- |
| init | `tg/init.yaml`（含 `uo_digest`、列映射、跑测口径） |
| plan | `tg/plan.md`（散文 + YAML 义务表） |
| solve | `tg/worklog.md` + 脚本可吃的 cases 表 |

确定性引擎在 `actions/tg_product.py`。LLM 只有 `tg-analyst`，只写 `runs/` 草稿。人确认仍走 `human_confirm` / `plan_approve`；收据 `consume=False` 直到 finalize 成功。

`init.yaml` 必须有：`table_kind`、入口与 `--case`、精度/性能怎么跑、列映射、值域、golden、脚本比对口径、`generate_inputs`、`uo_digest`。有仓但 mapping 空 → init 失败。扫描含 xls/xlsx。

plan 字段：`id, why, uo{query,span}, control{columns,recipe}, class, hit, cover`。`class` 只有 `replay` / `derived`。root 不到另列 `untestable.reason`。

## CE 边界

`/ce-apply` 的 `write_roots` 含 `test_script`。路径在 run-state `test_script_root` 下时映射为 `source:test_script/<rel>`，允许改算子仓外的测试脚本仓。TG 自己仍禁止写算子源码。

CE 不写、不投影、不传任何 yaml。`/tg-plan` 自己从 `ce/plan/{slug}_plan.md` 的「测试内容」节、同一会话的 review 对话、或 `session_handoff.md` 总结义务，写入 `tg/plan.md`。禁止读 `tg_plan_intent.yaml`。

## 怎么验证

```bash
python scripts/compose_runtime.py --repo . --host opencode
python scripts/compose_runtime.py --repo . --host cursor
python scripts/compose_runtime.py --repo . --host codex
python scripts/generate_reference_docs.py
python scripts/check_ownership_contracts.py
python scripts/check_docs.py
python scripts/check_runtime_graph.py
pytest
```

模块说明见 [TG](../modules/tg.md)。扩展时仍走 [extending.md](extending.md)：新相位进 `tg_specs.py`，不要再加旁路 YAML。
