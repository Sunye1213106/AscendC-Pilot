# Phase 1–2 落地笔记（2026-08-04）

## 问题
双权威（host_codemap vs operator_graph）+ tg-init 强制 CSV consumer，阻断 TilingKey 全量闭环进 `tg-solve`。

## 根因
1. `export_codemap` 读 `.probe_cache/fag_bundle.pkl`，与 KB 无 fingerprint 交叉校验。
2. `_require_consumer_root` 无条件调用；`mode` 不存在。
3. `apply_rules`/`report` 用 `excluded_by`（全 grade），`SOUND_GRADES` 形同虚设；`proof_rules.yaml` 误标 `grade: human`。

## 落点（公共层优先）
| 改动 | 路径 |
|---|---|
| TG Host View 投影 | `uo_init/host_codemap.py`、`kb_index.upsert_host_view_tables` |
| uo-init export 顺序 | `specs.py`：`export_kb → build_index → export_tg_host_view → export_integrity` |
| 禁止 probe 生产依赖 | `tk_cover_engines.export_codemap` 改为 reuse/delegate |
| mode + init_intent | `actions/engines.py` `_resolve_tg_ctx` / `_require_consumer_root` / `_run_tg_init_intent` |
| E 仅 sound grades | `closure/lemma.py` + `report.py` → `excluded_by_sound`；`proof_rules.yaml` → `source_lemma` |

## 状态
- Phase 1 单测：`test_tg_host_view.py` 通过
- Phase 2 单测：`test_tg_full_mode_without_consumer.py` 通过
- closure smoke（gap=0 + soundness）通过
- 未完成：Phase 4 学习循环进 `tg-solve` 状态机；lemma_review 前置；tk-cover 删除；compose 刷新
