# Semantic resolution

对当前 Action 列出的 ID 集合做证据驱动的语义闭合；证据不足则保持 unresolved。

## When to use

- KEY triage / resolution
- extract plan 语义候选
- TG 语义绑定缺口

## Method

1. 组合源码阅读 / 导航 / CodeMap 查询收集证据
2. 仅 high confidence 可闭合；否则保留 open 并写明缺证类型
3. 产出符合合同的 patch / 候选（不写裁判 verdict）

## Hard limits

- 不得伪造 high
- 不得在 batch 中塞 complex KEY
- 不得处理目标集外 ID

证据硬规则见 policy `evidence`。
