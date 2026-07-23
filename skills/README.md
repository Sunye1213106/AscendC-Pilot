# skills（组合式）

业务规则只在本树、`prompts/`、`agents/` 维护。

```text
python scripts/compose_runtime.py --repo .
# → generated/<host>/{skills,agents,prompts}/
```

- Policy / Capability / Action Method / Role / Workflow Skill 分层
- Pilot Workflow Spec（`pilot/.../specs.py`）声明 Action 组合引用
- Composer 组装运行时指令；禁止手改 `generated/`
- `/operator` 只调用 `acp route`
