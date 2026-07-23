# skills-src（组合式）

业务规则只在本树、`prompts-src/`、`agents-src/` 维护。

```text
python scripts/compose_runtime.py --repo .
# → generated/<host>/{skills,agents,prompts}/
```

- Policy / Capability / Action Method / Role / Workflow Skill 分层
- Harness Workflow Spec（`harness/.../specs.py`）声明 Action 组合引用
- Composer 组装运行时指令；禁止手改 `generated/`
- `/operator` 只调用 `harness route`
