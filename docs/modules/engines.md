# Engines

Engines 是确定性实现包。它们通过 Pilot actions 或开发者 CLI 生产、校验 canonical artifacts。

| Engine | Package | 职责 |
| --- | --- | --- |
| `common` | `acp-common` | 共享 engine utilities。 |
| `understand-operator` | `uo_init` | UO CodeMap extraction、analysis、commit、query、dump。 |
| `testcase-generation` | `testcase_agent` | TG contract、plan、solve、closure、replay 相关逻辑。 |
| `code-engineering` | `code_engineering` | CE impact 与 review 支持。 |

## 规则

- Engine 只有通过声明的 Pilot action 或显式 developer CLI，才写 canonical products。
- `deterministic-uo-engine`、`deterministic-tg-engine` 这类 engine identity 是 authorization identity，不是 LLM agent。
- 新增 engine directory 时，必须在本页登记，并通过 docs check。

## 实现锚点

- `engines/common/`
- `engines/understand-operator/`
- `engines/testcase-generation/`
- `engines/code-engineering/`
- `agents/deterministic-uo-engine.yaml`
- `agents/deterministic-tg-engine.yaml`
