# 设计原则

## 每类职责只有一个权威

不要让 docs、prompts、generated host files 和 Python code 同时定义同一个 contract。先确定实现权威，再在文档里链接它。

## 确定性产物优先

Canonical UO、TG 和 Pilot state 由确定性代码或 finalizer 生成。LLM Agent 可以调查、staging 和 review，但不能直接宣告 canonical state 成立。

## Docs 解释，Runtime Assets 执行

人类文档放在 `docs/`。只有会被 agent 或 composer 读取的 runtime Markdown，才继续留在代码旁边。

## Partial 是一等结果

未解析语义应显式保存在 artifact 中。不要用自信的 prose 掩盖 gap。

## 下游模块消费 UO

TG 和 CE 应优先消费 UO CodeMap 及其 projections，而不是重新做完整源码理解。
