# UO · TilingKey

按需阅读。权威仍在已 commit `.uo` 的 TILING_KEY 实体与 packing / registration 关系。

## 查什么

- 维名、`decl_order`、bit 布局、`allowed_values` / value domain  
- Host packing 表达式与 producer / overwrite sites  
- TPL / ARGS_SEL 展开的 legal key 空间（projection；须 freshness 合格）  
- 与 PREDICATE / BRANCH / KERNEL 的 SELECTS / CONTROLS / GUARDED_BY

## 推荐接口

```text
acp uo-query --mode template_match --pattern Dim=V,Other=V
acp uo-query --mode legal_key --pattern Dim=V,Other=V
acp uo-query --mode search --kind TILING_KEY --pattern <DimName>
acp uo-query --mode tiling_key --pattern <DimName|value>
acp uo-query --mode constraints --pattern <entity_id>
acp uo-query --mode branches --pattern <key_or_id>
```

「某维有没有编进 SEL」先看 `template_match.dim_coverage`（O(组)），不要 grep 第一块 ARGS_SEL。
「这组能不能编过」才用 `legal_key.total_matched`。
禁止手搓整包 `legal_key_index` JSON 加载；用 indexed/cache 模式。

## Claim 提示

- 「某枚举值是否在声明域」→ domain  
- 「Host 是否写出该值」→ host-produced（看 packing + guards + final overwrite）  
- 「能否端到端触发」→ full reachability（常超出 UO-only）
