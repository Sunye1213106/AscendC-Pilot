# Closure audit — 就绪性审计，不发明 exclusion

审计当前 TilingKey closure 是否达到可 certify 状态。Closure 只能由 Replay confirmed 或经审查的 exclusion proof 正式关闭。

详见 `references/closure-safety.md`、`references/closure-gotchas.md`、`references/certificate.md`、`references/failure-patterns.md`。

## 方法

1. 核对义务账本、证据引用与未闭合 residual。
2. 发现证据链断裂、规则越权或目标集被静默扩大时驳回。
3. 返回 `PASS` 或 `REJECT`，并列出关键理由。

## 禁止

- 新增 exclusion 规则
- 把搜索失败当作不可达
- 静默扩大 T
