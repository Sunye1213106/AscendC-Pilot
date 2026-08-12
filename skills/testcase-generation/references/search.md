# 搜索、轮次分析与定向构造

**何时加载**：Replay 一轮后决定继续 search、定向 construct，还是轮内引理时。

## 每轮立刻分析

```text
Candidate → Host Replay → Round Analysis → 更新 R/E/Open → 下一轮
```

不要等搜索饱和后再统一证明引理。

对照本轮构造意图比较：

```text
expected growth  = ΔR 模式符合计划（邻近维命中 / 计划子空间扩大）
actual growth    = new_declared_R + rewrite/refuse 分布
```

## 分支

### 增长符合预期

1. 新 accepted witness 并入 R
2. **立刻**对本轮 `refuse` / exclusive open pattern 做源码引理；能证则进 E
3. 剩余 open 沿已验证有效方向继续构造 / search

### 增长不符合预期

例如目标未命中却大量 rewrite、`ΔR≈0`、增长落在无关维、reject 模式与假设矛盾：

```text
已发现 key ∈ R
  → 解码差异维 / rewrite 维
  → CodeMap packing / Host producer / guard
  → 定向改相关 knobs
  → 下一轮 Replay → 再分析
```

优先用真实 witness 当锚点，不要重复同一套盲 mutation。

## 构造纪律

- 构造优先 CodeMap 定向：目标维 → packing 符号 → writers/predicates → upstream reads → knobs
- `construction_hints.yaml` 只作拼法缓存/兜底；空 hints 不得单独写成不可达
- 构造必须给出 best-effort case；构造器诊断假设不得导致空返回并据此写 E
- `construct failure ≠ unreachable`；结果进入当轮 Round Analysis
- 近似模型只排序候选；排除必须源码或求解器证明
- 构造证据写入 `tg/closure/construct/trace.yaml`（entity id / packing / knob cone）
- 路由产物：`tg/closure/route.yaml`、`tg/closure/round_analysis.yaml`（含 `growth_match`）
