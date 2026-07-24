# skills（组合式）

业务规则只在本树、`prompts/`、`agents/` 维护。

```text
python scripts/compose_runtime.py --repo .
# → generated/<host>/{skills,agents,prompts}/
```

- Policy / Capability / Action Method / Role / Workflow Skill 分层
- Pilot Workflow Spec（`pilot/.../specs.py`）声明 Action 组合引用
- Composer 组装运行时指令；禁止手改 `generated/`
- 意图：Agent 按各 workflow skill 的 `description` 自选加载；`acp route` 仅 slash
- `/operator` 为可选助手（列候选 / 转发 slash），不做口语路由
