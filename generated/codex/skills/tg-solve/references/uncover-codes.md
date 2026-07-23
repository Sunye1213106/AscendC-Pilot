# Uncover / 失败原因码（tg-solve）

义务终态必须可机械核对：`covered` 或 `uncovered` + **稳定** reason_code。

常见码（脚本/门禁产出，勿臆造新同义词）：

| Code | 含义 |
|---|---|
| `UNSAT` | SMT 无解 |
| `DOMAIN_REVIEW_REQUIRED` | 列域未确认（回 init） |
| `domain_asymmetry` | 字面量∉CSV 域 |
| `KEY_DERIVATION_MISSING` | 绑定链未闭合 |
| `UNCOVERED` | 求解后仍无见证行 |
| `PROJECT_FAIL` | 模型无法投影到 CSV |
| `APPROVE_BLOCKED` | 无有效批准 |

禁止：假 `not_csv`、模糊 `skip`、无证据标 covered。
