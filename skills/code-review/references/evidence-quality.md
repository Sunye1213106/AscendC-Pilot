# 证据质量

**何时加载**：需要判断「搜索未命中 / 索引 partial / 模型预测」能否支撑结论时。

## 硬规则

```text
查询未命中 ≠ 源码不存在
搜索失败 ≠ 状态不可达
模型分数 ≠ 源码事实
```

## 可用作正面支持

- 带 `file:line` / `path:line`（或 `path:start-end`）的源码切片
- 完整（或对本命题足够）的 writers/callers 闭包
- 可 replay 的运行观测（绑定具体 case）

## 用户可见回答

- 问答 / 查询类最终回答：每个事实结论须写出上述 `path:line`（或区间）；仅 KB 节点名不足以支撑「已定位」叙述
- 高置信结构化字段（`confidence: high` / `source_verified`）仍遵守 policy `evidence`，本文件不另开例外

## 不得单独支撑排除 / 不可达

- 有限搜索耗尽
- 样本未出现
- 近似模型预测
- 静态分析 `unknown` / `partial`
- 构造器先验拒采
- 仅有 derived 表达式但非 EXACT（`derived ≠ exact`）
