# 最终置信度门禁（强制 high）

`/uo-init` 收工前：凡已闭合交付的 KEY 必须 `confidence: high`。

## 规则

| 情况 | 动作 |
|---|---|
| 图/脚本已闭合且 `confidence: high` | 可交付 |
| `unsolved` 或 confidence≠high | **必须**派 `uo-semantic-resolve`（任务 E / 残留）LLM 解析 |
| LLM 仍无法 high 闭合 | 写 `summary/confidence_report.md`，逐 KEY 中文说明原因；**禁止伪标 high** |

## 父代理步骤

1. LLM 批跑断边（`tpl_input_derivable.md`），仅采纳 `confidence: high` 的 patch。
2. 重跑 `classify_input_derivable.py`。
3. 跑门禁：

```powershell
python -X utf8 "$SCRIPT_DIR/check_final_confidence.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

4. `status=fail` → 继续 LLM，或补全报告「原因」（不可留 TODO）。
5. `status=pass`（全 high）或 `reported`（剩余项报告已写满原因）→ 才可 integrity / kb-review。
6. 若 `reported`：向用户展示 `summary/confidence_report.md` 摘要。

## 报告路径

- `summary/confidence_report.md` — 人类可读
- `checks/confidence_gate.yaml` — 机器状态

报告每节必须含非空 `- 原因：...`（禁止 `TODO` / `（待…）` 占位）。
