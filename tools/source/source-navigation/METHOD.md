# 源码与 UO 图导航

## When to use

在 confirmed source scope 内定位符号、边和影响关系；需要验证实现时再取行号明确的窗口。

## Tools

- 插件 `pilot_cli` `uo-query`：先查已导出的 UO 图（command 不要前导 acp）
- `readonly-source-search` / 有界 `Read`：图不足时取证据窗
- 宏、模板、注册和构建条件：在已确认范围内做确定性源码闭包

## Output shape

- 命中：路径、符号、边或影响关系 + 可选窗口引用
- 未命中 / 查询失败 / 窗口不足：结构化 unresolved（不得把空结果当成“符号不存在”）

证据硬规则见 policy `evidence`，勿复述。
