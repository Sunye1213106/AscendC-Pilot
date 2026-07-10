# Factor Space Build

对齐 ST「测试因子提取」，输入是 `kb_snapshot`。

## 必须提取

1. **tiling_key fields**：domain / bits / constant / derived
2. **family factors**：guard / reachability / struct_signature / route_action
3. **tilingdata factors**：structs / present_when / numeric_overlay / varlen
4. **operator_io factors**：required/optional/outputs/attrs + dtype/shape/layout hints
5. **solver**：anchors（无依赖 key fields）+ derivation_order

## 输出

`generate/factor_space.yaml`，schema 见 `references/factor-extraction.md`。

## 求解锚点（简化拓扑）

```text
anchors = tiling_key fields that are not derived and not constant
level_0 = anchors + required io existence
level_1 = derived key fields + family_id（由 guard 推导）
level_2 = tilingdata present / numeric overlays
```

MVP 不实现完整 CSP solver；用 anchors 指导 candidate 生成顺序与 pairwise 字段选择。

## 检查清单

- [ ] 每个 key field 有 domain 或标 unknown
- [ ] unreachable family 不进正向采样域
- [ ] numeric_overlay 未伪造成 tiling_key bit
- [ ] input_realization 索引到 key field 值
