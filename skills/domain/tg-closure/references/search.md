# 搜索与构造

**何时加载**：决定继续 construct/search 还是转入引理时。

- 构造优先 CodeMap 定向：目标维 → packing 符号 → writers/predicates → upstream reads → knobs
- `construction_hints.yaml` 只作拼法缓存/兜底；空 hints 不得单独写成不可达
- 构造必须给出 best-effort case；构造器诊断假设不得导致空返回并据此写 E
- 饱和：连续多轮对剩余 open 已构造且回放仍无新 R，残差不再改善 → 才转入引理
- 近似模型只排序候选；排除必须源码或求解器证明
- 构造证据写入 `tg/closure/construct/trace.yaml`（entity id / packing / knob cone）
