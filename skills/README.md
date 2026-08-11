# skills

模型可读的专业能力包。Action / Workflow 编排权威在 `pilot/.../workflows/specs.py`。

```text
python scripts/compose_runtime.py --repo .
# → generated/<host>/{skills,agents,prompts}/
```

- 四个认知 Skill：`operator-analysis`、`testcase-generation`、`source-proof`、`code-review`
- Composer 另外生成 slash 入口（`uo-init`、`tg-solve` 等）与 Spec Action Bundle 镜像
- 禁止手改 `generated/`
- Agent 按 Skill `description` 自选加载；`acp route` 仅 slash
