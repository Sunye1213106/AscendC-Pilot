# agents

Agent 稳定角色 YAML。由 Composer 生成宿主 Markdown 到 `generated/<host>/agents/`。

## kind

| kind | 含义 | 是否 compose 到宿主 agents/ |
|------|------|------------------------------|
| （缺省） | LLM 角色（primary / subagent） | 是 |
| `deterministic_engine` | 引擎身份：仅供 authorize / write_scopes；由 `acp run-action` 调 Python engine | **否**（`compose_runtime` 按 kind 跳过） |

`deterministic-tg-engine` 使用 `kind: deterministic_engine`。它不是「再包一层 LLM」，而是引擎身份声明。

## Agent Necessity Audit

**只有**满足以下至少一条时才保留为 Agent：

1. **Context isolation** — 需要独立 session / prompt，避免污染主对话
2. **Parallelism** — 可对多个 bundle/shard 并行派发
3. **Tool / write permission isolation** — 读写范围必须窄于 primary
4. **Adversarial review** — 独立 referee，禁止自审自批

否则：分析方法 → Domain Skill；执行步骤 → Action；确定性程序 → Engine（`kind: deterministic_engine` 或纯 Python）。

### 现存 agent 命中理由

| Agent | 命中 | 说明 |
|-------|------|------|
| `ascendc-pilot` | primary | 主会话；禁止自行 declare PASS |
| `uo-gap-investigator` | 1, 3 | 只读调查 unresolved；不写 canonical `.uo` |
| `uo-query` | 1, 3 | 只读查询隔离；不改 `.uo` |
| `ce-reviewer` | 1, 3, 4 | 独立审查上下文与写范围 |
| `tg-lemma-producer` | 1, 2, 3 | 有界引理 staging；禁写 excluded |
| `tg-closure-referee` | 1, 3, 4 | adversarial review；只写 review.yaml |
| `tg-init-audit` | 1, 3, 4 | init 审计 referee |
| `tg-semantic-bind` | 1, 3 | csv_consumer overlay 下的语义绑定 producer |
| `deterministic-uo-engine` | （非 LLM） | Engine 身份；`kind: deterministic_engine` |
| `deterministic-tg-engine` | （非 LLM） | Engine 身份；`kind: deterministic_engine` |

已删除：`tg-csv-contract`（死代码；契约构建由 deterministic engine 的 `contract_build` 承担）。
