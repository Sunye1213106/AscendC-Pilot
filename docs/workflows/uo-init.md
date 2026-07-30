# /uo-init

首次建立分层 UO KB。

## 阶段

prepare → scope → extract → normalize → export → review

## 引擎

Pilot `ENGINE_REGISTRY[("uo-init", *)]` → `uo_init.pilot_engines`（libclang 确定性抽取）。

## 启动

```powershell
acp start uo-init --project <算子目录> --architecture arch35
acp next
acp run-action <action_id>
```

范围步骤也可：`acp uo-scope prepare|scan|confirm`（包装同一 `pilot_engines`）。

## 不在本链

旧 `extract_plan` / `detect_score_*` / `adjudicate_llm_tasks` / `uo.scripts.*` 已删除。
