# `/tg-solve` 命令块

```powershell
$PROJECT_ROOT = "<算子仓>"
$OP_NAME = "<op>"

tg-solve "$PROJECT_ROOT" --op-name $OP_NAME --level L0
```

## 启动失败

| ask / 码 | 动作 |
|---|---|
| `domain_asymmetry` | `tg-init --merge-uo-resolve`（必要时 uo-query），禁 Edit YAML |
| `APPROVE_BLOCKED` / 无批准 | 回 `/tg-plan` |
| 语义缺口 | Task uo-query → merge → **replan 一次** → 再 solve |

## HARD

- MUST NOT 修改 approved plan 或 lexicon
- 覆盖由脚本核对；禁止手算

详见：`skills/tg-solve/references/domain-symmetry.md`、`uncover-codes.md`。
