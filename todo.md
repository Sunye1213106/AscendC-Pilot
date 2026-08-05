# 任务：闭合 P0 控制平面合同

## 目标
让 full-mode tg-init 合同可 finalize；修路径错位；mode 传到 pipeline；referee 必须过才能 certify。

## 待办事项
- [x] 1. tg-init mode overlay + tilingkey-*-v1 Output Contracts
- [x] 2. 修 flat `.ascendc-pilot` 路径（lemma_mine / gates）
- [x] 3. preferred_pipeline / actions_for_phase 传 mode
- [x] 4. referee audit status 才能 certify
- [x] 5. lazy layout + 测试对齐 + 更新本文件

## 进度
5/5

## 本轮落地摘要
- tg-init 默认 full：intent→kb_ready→contract→bind→gate→confirm（无 merge/nest）
- 合同：tilingkey-contract/binding/integrity-v1；csv_consumer overlay 保留旧合同
- lemma_mine → agent_root/runs；gate coverage/context_pack 走 arch helper
- preferred_pipeline / actions_for_phase / runtime / machine 传 project_root
- closure_audit awaiting → ok=False；certify 要求 audit pass/accepted/auto_ok
- ensure_control/uo/tg/closure/ce/memory_layout 拆分；start/prepare 按需创建
- human_confirm full 模式不再写 binding_lexicon；require_merge 仅 csv
