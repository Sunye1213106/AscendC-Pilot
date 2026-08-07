## Task

执行 `scope_confirmation`（prepare 完成后的 primary 交互步骤）。

Bundle identity is authoritative.
Do not replace, infer, normalize, or copy identity from old artifacts.

## Mode

- mode: `primary_interactive`
- workflow_id: `<WORKFLOW_ID>`
- action_id: `<ACTION_ID>`
- actor_id: `<ACTOR_ID>`
- role_id: `<ROLE_ID>`
- run_id: `<RUN_ID>`
- action_session_id: `<ACTION_SESSION_ID>`
- architecture: `<ARCHITECTURE>`

## 严禁（违反即失败）

- 再次执行当前 Action 的 prepare（`run-action` 不含 `--finalize`）或把 primary 当 subagent 派发
- 认为 acp「只是概念」而手工按 Actions 表执行
- 跳过 `prepare_layout`
- 用 Glob / Read / 心算制作架构文件计数表
- 只扫算子目录、漏掉 sibling/parent `common/`
- 直调 `python …/macro_scope_scan.py` 等
- 硬编码算子名、架构或 project 路径

## 必须执行的命令顺序

工作目录 = `<PROJECT_ROOT>`（当前算子根）：

```text
acp uo-scope scan --project <PROJECT_ROOT> --architecture <ARCHITECTURE>
# ↑ 把完整 stdout（含 common 检测行与计数表）原样给用户确认
# AskQuestion: continue | revise | stop | manual_supplement

acp uo-scope checkpoint --project <PROJECT_ROOT> --decision <decision>
acp uo-scope finalize --project <PROJECT_ROOT>
acp run-action <ACTION_ID> --finalize --project <PROJECT_ROOT>
```

若 scan 输出没有 `Detected AscendC common library` / `common_files`，而仓库存在 `../common`，停止并报告，不要手补。

正式 Output Contract 产物：
`uo/runs/<RUN_ID>/scope/scope_confirmed.yaml` + `receipt.yaml`
（不是 `uo/summary/scope_confirmed.yaml`，也不是任意旧 run 的 `uo/runs/*/…`）。

## Output Contract

`scope-confirmed-v1`
