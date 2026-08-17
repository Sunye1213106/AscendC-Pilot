# Intent grill staging

本步草稿只写当前 action 目录，由 Host `grill_promote` 合并进 `ce/intent/intent.yaml`。

路径：

```text
<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/intent_grill/staging.yaml
```

也可拆成 `parts/*.yaml`。不要在仓库其它位置寻找 schema。

```yaml
schema: ce-intent-grill-staging/v1
in_scope: []
out_of_scope: []
acceptance: []
open_questions: []
side: ""
```

字段：

| 字段 | 含义 |
| --- | --- |
| `in_scope` | 本变更要覆盖的范围 |
| `out_of_scope` | 明确不做 |
| `acceptance` | 后续 `/ce-verify` 可关闭的验收 |
| `open_questions` | 未决决策（带推荐答案） |
| `side` | `kernel` / `tiling` / `host` / `mixed` |

超时或中止前，已用 `acp uo-query` 查到的结论仍须写进最终消息。
