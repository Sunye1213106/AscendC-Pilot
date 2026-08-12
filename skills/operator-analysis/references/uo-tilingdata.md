# UO · TilingData

按需阅读。字段写读看 TILING_FIELD / TILING_DATA 与 WRITES / READS / value_defining_sites。

## 查什么

- 结构成员、owner、ctype  
- Host writer sites / Kernel reader sites  
- `value_defining_sites`（定值写点优先）  
- registration：packed key → TilingData 绑定

## 推荐接口

```text
acp uo-query --mode tiling_data --pattern <FieldOrStruct>
acp uo-query --mode field --pattern <FieldName>
acp uo-query --mode neighbors --pattern <entity_id> --depth 2
```

## Claim 提示

- 「谁写谁读」→ host-produced / kernel-consumed  
- 中间 wrapper 未闭合 → `PARTIAL`，不要用节点共存冒充关系
