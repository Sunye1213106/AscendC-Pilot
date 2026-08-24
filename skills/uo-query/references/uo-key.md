# TilingKey 与 packing

按需阅读。权威仍在已 commit `.uo` 的 TILING_KEY 实体与 packing / registration 关系。

## 查什么

- 维名、`decl_order`、bit 布局、`allowed_values` / value domain  
- Host packing 表达式与 producer / overwrite sites  
- TPL / ARGS_SEL 展开的 legal key 空间（projection；须 freshness 合格）  
- 与 PREDICATE / BRANCH / KERNEL 的 SELECTS / CONTROLS / GUARDED_BY

## 推荐接口

```text
uo-query --project <op> Dim=V,Other=V
uo-query --project <op> <DimName>
```

OpenCode：插件 `pilot_cli`，command 即上列 argv。

「某维有没有编进 SEL」先看 `dim_coverage`（覆盖形态），不要 grep 第一块 ARGS_SEL。
「这组能不能编过」看 `matching_block_count`（与 `total_matched` 同义）。笛卡尔合法键数看 `legal_key_count`。
禁止手工构造整包 `legal_key_index` JSON 加载。

## Claim 提示

- 「某枚举值是否在声明域」→ domain  
- 「Host 是否写出该值」→ host-produced（看 packing + guards + final overwrite）  
- 「能否端到端触发」→ full reachability（常超出 UO-only）
