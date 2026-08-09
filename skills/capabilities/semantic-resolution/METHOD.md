# 语义闭合

## When to use

对当前 Action 列出的 ID 集合做证据驱动的语义闭合；证据不足则保持 unresolved。

## Tools

- 组合 `source-reading` / `source-navigation` / `kb-query` 收集证据
- 仅 high confidence 可闭合；否则保留 open 并写明缺证类型

## Output shape

- 符合合同的 patch / 候选（不写裁判 verdict）
- unresolved：缺证类型与未处理原因

硬限制：不得伪造 high；不得在 batch 中塞 complex KEY；不得处理目标集外 ID。

证据硬规则见 policy `evidence`，勿复述。
