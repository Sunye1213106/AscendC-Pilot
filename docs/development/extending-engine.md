# 扩展 Engine

Engine 是确定性 package。

## 新增或修改 Engine

1. 实现放在 `engines/<name>/`。
2. 添加 package metadata 与 tests。
3. 需要公开 CLI 时，在 package `pyproject.toml` 中登记。
4. 如果 Pilot authorization 需要，新增或更新 `agents/` 中的 deterministic engine identity。
5. 在 `pilot/ascendc_pilot/workflows/specs.py` 中接入 workflow action。
6. 在 [Engines](../modules/engines.md) 中登记。

## 检查

```bash
python scripts/check_docs.py
pytest engines/<name>/tests
```
