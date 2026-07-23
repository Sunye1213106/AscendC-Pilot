## Task

执行 `scope_confirmation`。架构过滤只通过 scan 参数，不靠手工读目录。

## 严禁（违反即失败）

- 认为 acp「只是概念」而手工按 Actions 表执行
- 跳过 `prepare_layout`
- 用 Glob / Read / 心算制作「arch35 文件计数表」
- 只扫算子目录、漏掉 sibling/parent `common/`
- 直调 `python …/macro_scope_scan.py` 等

## 必须执行的命令顺序

工作目录 = 算子根（`flash_attention_score_grad`）：

```text
acp next --project .
# 若 next 是 prepare_layout：
acp run-action prepare_layout --project .

acp run-action scope_confirmation --project .
acp uo-scope scan --project . --architecture arch35
# ↑ 把完整 stdout（含 common 检测行与计数表）原样给用户确认
# AskQuestion: continue | revise | stop | manual_supplement

acp uo-scope checkpoint --project . --decision continue
acp uo-scope build-evidence --project .
acp uo-scope closure --project .
acp uo-scope stage --project .
# MUST：MCP index_repository → …/.ascendc-pilot/uo/cbm/index_stage  (mode=fast)
#       成功后必须存在 uo/cbm/index_meta.json 且 indexed_via=mcp
# 禁止跳过 MCP 直接 finalize
acp uo-scope finalize --project .
acp run-action scope_confirmation --finalize --project .
```

若 scan 输出没有 `Detected AscendC common library` / `common_files`，而仓库存在 `../common`，停止并报告，不要手补。

正式 Output Contract 产物：`uo/runs/*/scope/scope_confirmed.yaml` + `receipt.yaml` + `uo/cbm/index_meta.json`（不是 `uo/summary/scope_confirmed.yaml`）。

## Output Contract

`scope-confirmed-v1`
