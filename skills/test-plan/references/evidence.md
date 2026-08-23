# 命中观测

**何时加载**：为 Target 写 `evidence`，为 Dimension 写 classifier `requires`。

每个正式白盒状态必须能回答：跑完 Replay（必要时探针）看哪条观测。这是 solve 迭代的尺子。引擎计算 HIT/MISS；LLM 不得宣布 HIT。

## 种类（优先从上往下）

| kind | 何时用 | 例子 |
| --- | --- | --- |
| `replay_field` | Replay 已经输出 | TilingKey、TilingData 字段、blockDim、workspace |
| `derived` | case + Replay 字段能算死 | 结构化 `mod_eq` / 比较 |
| `dispatch_map` | Replay 字段 + UO 静态映射 | TilingKey → 模板 specialization |
| `probe` | 上面都看不到的 Host 内部状态 | `TG_PROBE kvMerge=1` |
| `source_proof` | 不可达 / 静态 invariant | 某组合不可能出现 |

`source_proof` 不证明某条 case 的 runtime 命中。不可达走 `skills/source-proof/SKILL.md`。

精度 / 性能收据不是 evidence。它们是命中之后的可选 `oracle`。

字段必须是 `case.*` / `replay.*` / `probe.*` 或可解析的裸 symbol。禁止「看起来应该算 tail」。

## 探针

只允许 **replay-local**：引擎在 TG sandbox 拷贝里插 `TG_PROBE key=value` 并重编。禁止改算子源码仓。已有 dump（如 `###TD`）够用就不要点 probe。

## 判定

```text
HIT       evidence 对上期望
MISS      跑了但对不上
UNKNOWN   缺收据 / 探针没打出来
```

Replay 原始 `HIT / REWRITE / REFUSE` 仍是 tiling 裁决，与 Target HIT 分开记账。

```text
accuracy PASS 但 Target MISS ≠ 已覆盖
```

## 必填

```yaml
evidence:
  kind: replay_field   # 或 derived | dispatch_map | probe | source_proof
  field: kvMerge
  expected: true
```

缺 `kind` 或期望含糊 → 不得进正式 plan。
