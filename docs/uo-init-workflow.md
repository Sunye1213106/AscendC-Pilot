# /uo-init 人类说明（非可执行状态机）

**控制面权威**：`acp` + `workflows/specs.py`。  
**运行时方法**：`skills/actions/uo-init/**`（经 Composer 写入 `generated/`）。

## 循环

```text
acp start uo-init
acp next → phase_label_zh + allowed_actions
执行当前 Action 领域方法
acp advance | rework | complete
```

## 中文阶段

| id | label_zh |
|---|---|
| prepare | 环境准备 |
| scope | 范围确认 |
| extract | 结构抽取 |
| resolve | 语义闭合 |
| export | 导出与校验 |
| review | 产物审查 |

用户可见阶段使用中文名。内部产物目录：`runs/<run_id>/scope/`。

## 角色

| Agent | role |
|---|---|
| uo-semantic-resolve | producer |
| uo-key-resolve | producer |
| uo-confidence-review | referee |
| uo-kb-review | referee |
| deterministic-uo-engine | deterministic_engine |

## 边界

- 测项合同属 TG（`.ascendc-pilot/tg/`），UO 不写 `contracts/**`
- 完成态仅 `acp complete`
- 详见 [overview/workflows.md](./overview/workflows.md)
