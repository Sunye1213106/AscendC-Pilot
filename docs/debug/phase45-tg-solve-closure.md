# Phase 4–5：tg-solve closure 接线 + operator adapter 起步

## 问题

`tg-solve` 仍是 Z3/CSV 工具箱，闭环主循环未挂控制面；FAG 常量表散落在 `closure/*.py`，第二算子无法切入。

## 根因

引擎零件已在 `testcase_agent/closure/`，缺状态机 actions / engines / agents；算子边界文件未从 engine 迁出。

## 落点

- Phase 4：`tg-solve` pipelines = oracle→ledger→search→residual→(construct|lemma)→audit→certify；engines 注册；agents `tg-lemma-producer` / `tg-closure-referee`；capability 引用不复制证据规则；compose 已 sync。
- Phase 5 起步：`replay/package_data.py` + `inputs` 按 `UO_OPERATOR`/`UO_ARCH` 加载；FAG `construction_hints.yaml` / `feature_bindings.yaml` / `search_hints` 扩展；`operators/_synthetic_toy`（`_` 前缀不参与 auto-discover）；`test_second_operator_adapter_smoke`。

## 状态

Phase 4 完成；Phase 5 表迁出 + synthetic smoke 完成；Phase 6：`/tk-cover` 已改为 `alias_of: tg-solve`（无独立 pipeline）。**未删** `.probe_cache/`（体积大且可能仍有本地语料）——需你确认后再清理。

## 验证

相关 pytest 绿；`compose_runtime.py --repo .` ok（generated 不再编译独立 tk-cover skill）。请本地 `refresh-opencode.ps1` 后重启宿主以加载新 agents/skills。
