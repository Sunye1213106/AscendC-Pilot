# 扩展 Workflow

Workflow 权威在 `pilot/ascendc_pilot/workflows/specs.py`。

## 修改 Workflow

1. 在 `WORKFLOWS` 中新增或更新 states、transitions、actions、gates、write roots。
2. 为每个 action 设置 `agent_id`、`role_id`、`execution_mode`、task prompt、capabilities 和 output contract。
3. action paths 变化时更新 `pilot/ascendc_pilot/ownership.py`。
4. 新增或更新 `prompts/tasks/`。
5. 为 phase movement、gate behavior 和 lease scope 增加测试。
6. 重新 compose runtime：

```bash
python scripts/compose_runtime.py --repo . --host opencode
python scripts/compose_runtime.py --repo . --host cursor
python scripts/compose_runtime.py --repo . --host codex
```

## 检查

```bash
python scripts/check_ownership_contracts.py
pytest pilot/tests
```
