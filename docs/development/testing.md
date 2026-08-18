# 测试与评估

测试应跟随风险边界，而不是只验证某个函数返回了值。涉及 workflow、权限、gate 或 canonical 产物的修改，应覆盖成功路径与被拒绝、rework、过期输入等失败路径。

| 路径 | 覆盖范围 |
| --- | --- |
| `pilot/tests/` | workflow、lease、gate、state、local extension、运行时集成 |
| `engines/understand-operator/tests/` | 源码范围、Clang extraction、CodeMap 与 UO contract |
| `engines/testcase-generation/tests/` | init.yaml、plan.md、worklog、replay 与隔离门 |
| `engines/code-engineering/tests/` | plan md、apply todo、内存 diff、handoff |
| `scripts/tests/` | replay 和 script-level contract |
| `evals/` | routing、skill、harness 与可复用 fixture |

常用检查：

```bash
python scripts/generate_reference_docs.py
python scripts/check_docs.py
pytest
```

运行 skill eval：

```bash
python evals/skills/run_skill_eval.py
```

大型或可复用 fixture 放在 `evals/fixtures/`，不要放到说明文档中。局部改动优先运行所在模块测试；影响跨模块 contract 时，再扩展到 Pilot 集成测试或全量 `pytest`。
