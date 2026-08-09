---
name: uo-codemap-query
description: >
  基于单一 AscendC `.uo` CodeMap 回答 API、Host、TilingKey、TilingData、Kernel、
  模板、宏、编译期变量、架构与数据流问题。查询、解释、定位或检查 CodeMap
  完整性时使用；只读，不修改 UO。
---

# UO CodeMap 查询

权威入口是 `.ascendc-pilot/uo/<op>.<arch>.uo`。优先使用 `uo_init.uo_query.open_query(...)` / `CodeMapQuery`，不要依赖底层存储实现。

## 查询原则

1. **结构化查询优先**：先用最窄接口查实体、邻接、路径或字段影响，再决定是否读取源码。
2. **证据关系优先**：跨层结论必须沿真实 relation；节点同时存在不构成关系。
3. **BuildVariant 隔离**：宏、模板实例、compile var 和 architecture 必须属于当前构建变体。
4. **源码只做验证**：CodeMap 不足时读取最小源码窗口，不能用整文件扫描替代查询。
5. **缺口显式保留**：unresolved 影响结论时返回 `PARTIAL` 或 `UNKNOWN`，不要猜测补边。

## 常用查询面

- API：`operator_api`、`input_roots`、`output_roots`
- TilingKey：`tiling_keys`、`selected_kernel`
- TilingData：`tiling_data`、`tiling_fields`、`tiling_registrations`、`field_impact`
- 图关系：`search`、`neighbors`、`callers`、`callees`、`find_path`、`upstream`、`downstream`
- 编译期：macro、compile var、template arg / instance、BuildVariant、available arch
- 质量：`audit`、`unresolved`、`summary`

## 结果状态

- `ANSWERED`：结构化证据足以回答。
- `PARTIAL`：主结论可回答，但存在明确缺口。
- `UNKNOWN`：当前证据不足，不能可靠推断。
