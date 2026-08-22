# 命中观测

**何时加载**：为每个独立变量写 `evidence`，供 Host 编译运行后判定是否打到。

每个变量必须能回答：跑完 Replay（必要时探针）看哪条观测、期望是什么。这是 solve 迭代的尺子。

## 种类（优先从上往下）

| kind | 何时用 | 例子 |
| --- | --- | --- |
| `replay_field` | Replay 已经输出 | TilingKey、TilingData 字段、blockDim、workspace |
| `derived` | case + Replay 字段能算死 | `s2 % s2Inner != 0`、buffer bytes、tile count |
| `dispatch_map` | Replay 字段 + UO 静态映射 | TilingKey → 模板 specialization |
| `probe` | 上面都看不到的 Host 内部状态 | `TG_PROBE kvMerge=1` |
| `source_proof` | 不可达 / 静态 invariant | 某组合不可能出现 |

`source_proof` 不证明某条 case 的 runtime 命中。不可达走 `skills/source-proof/SKILL.md`。

精度 / 性能收据不是 evidence。它们是命中之后的可选 `oracle`。

## 探针

只允许 **replay-local**：编译 Host Replay 驱动时插 `TG_PROBE key=value`。禁止改算子源码仓。已有 dump（如 `###TD`）够用就不要点 probe。

## 判定

```text
TARGET_HIT   evidence 对上期望
TARGET_MISS  跑了但对不上
UNKNOWN      缺收据 / 探针没打出来
```

Replay 原始 `HIT / REWRITE / REFUSE` 仍是 tiling 裁决，与 `TARGET_HIT` 分开记账，除非 evidence 就是那条 TilingKey / 字段。

```text
accuracy PASS 但 TARGET_MISS ≠ 变量已覆盖
```

## 必填

```yaml
evidence:
  kind: replay_field   # 或 derived | dispatch_map | probe | source_proof
  field: kvMerge       # 或 expr / predicate
  expected: true       # derived 可写谓词
```

缺 `kind` 或期望含糊 → 变量不得进正式 plan。
