# 扩展 Agent

## 新增 Agent

1. 先判断新 identity 是否真的需要上下文隔离、并行、权限隔离或 referee 分离。
2. 新增 `agents/<id>.yaml`。
3. 只在需要它的 action 中从 `pilot/ascendc_pilot/workflows/specs.py` 引用。
4. 确认 write scopes 是权限上限，不是宽泛授权。
5. 重新生成 matrix：

```bash
python scripts/generate_agent_matrix.py
```

6. 运行检查：

```bash
python scripts/check_docs.py
python scripts/check_ownership_contracts.py
```

## 避免

- 不要为了放说明文字而创建 Agent。
- adversarial review 场景中，不要让 producer 和 referee 是同一个 identity。
- 不要把 canonical write paths 授给 staged producer。
