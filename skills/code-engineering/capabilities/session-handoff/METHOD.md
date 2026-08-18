# Session handoff

把当前会话写成便携总结。用户主动调用 `/handoff`；不要自己触发。

落盘：`<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/session_handoff.md`

## 必须有

- `next:` 一条 slash（例如 `/ce-apply` / `/tg-plan` / `/ce-review`）
- `why:` 一两句
- `artifacts:` 只引用路径，不复制 `{slug}_plan.md` / diff / `tg/init.yaml` 正文
- `open:` 未决事项
- `suggested:` 建议的下一步 slash

若 `next:` 是 `/tg-plan`，用散文写下「该测什么」，以便换会话后 TG 仍能读这份 md。

## 禁止

- 写成 yaml
- 复制计划或审查正文
- 写入密钥；脱敏为占位
- 占 uo/tg/ce 锁
