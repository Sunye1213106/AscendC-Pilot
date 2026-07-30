# 任务备忘（非产品文档）

现行文档索引：`docs/README.md`。

## 引擎边界

- [x] `uo-init` → `uo_init.pilot_engines`
- [x] `uo-update` → `uo_init.update`；旧引擎目录已删除
- [x] `uo-query` / `uo-scope` / CBM client 迁入 Pilot + `uo_init`
- [ ] KeyField 三重全覆盖（见 `docs/debug/open-problems.md` / `docs/debug/handoff.md`）

## prepare 清场（可选回归）

- [x] prepare_layout 按新契约清 legacy
- [ ] 对目标算子跑通 prepare → scope → export，确认无旧 bridge/cbm 残留
