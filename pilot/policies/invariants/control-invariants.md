# 控制不变量（面向模型，短）

Host Session Driver（`pilot_run` + `dispatch-result`）拥有传输，**不驱动 `uo-query`**。

1. 只执行 `pilot_run` / `dispatch-result` 返回的 Action / `host_step`。不得发明阶段，不得自行宣布 `done` / `passed`。
2. 工作流只用 `pilot_run`。禁止对 `uo-query` 调用 `pilot_run`（调查拆路见 intent-reasoning）。`host_step.tasks`≥2 时按 `task_prompt_stub` 原样派发。非 primary 不得再派发 Task。`primary_review` 下一发仅 `PASS` 或 `REWORK bind` / `REWORK harness,bind`。禁止 `--help`。禁止 `force_new` 除非用户明确删除重开。
3. `/uo-init` `/uo-update` 缺 architecture → AskQuestion，禁止猜测。第一轮 `workflow=auto` 省略 architecture。隔离 clone 走 `auto`。意图未给出仓外测试路径时 `/tg-init` 由 Host 问三项。禁止把仓内 `tests/` 填进 `test_script_root`。
4. 写入必须落在 `write_scopes` ∩ lease ∩ `write_roots`。
5. `host_step.kind=done`：看产物、勾 Todo、再下一格。禁止把卡片全文写入后续 intent。子代禁止 Write `answer.yaml`。
6. `/uo-init`/`uo-update` 必须带 `--project` 与 `--architecture`。TG/CE/查询以已有 `.uo` 为准。无 `.uo` 时 AskQuestion（查询：`/uo-init` 或源码作答；TG/CE 先 `/uo-init`），禁止 Glob 找产物。

全文：`pilot/policies/pilot-control/POLICY.md`。人/CI 传输细节：`host-runtime-contract.md`。
