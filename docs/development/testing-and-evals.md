# 测试与 Evals

## 主要测试面

| 路径 | 作用 |
| --- | --- |
| `pilot/tests/` | Runtime、workflow、gates、leases、state、local extensions。 |
| `engines/understand-operator/tests/` | UO extraction 与 CodeMap 行为。 |
| `engines/testcase-generation/tests/` | TG planning、solve、closure、replay contracts。 |
| `engines/code-engineering/tests/` | CE impact 行为。 |
| `scripts/tests/` | Replay 与 script-level contracts。 |
| `evals/` | Routing、skills、harness 与 reusable fixtures。 |

## 常用命令

```bash
python scripts/check_docs.py
pytest
```

运行 skill eval：

```bash
python evals/skills/run_skill_eval.py
```

## Fixture 放置

大型或可复用测试数据放在 `evals/fixtures/`，不要放进 `docs/`。
