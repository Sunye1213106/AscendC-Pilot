# 搜索、轮次分析与定向构造

**何时加载**：Replay 一轮后决定继续构造还是写 worklog。

```text
cases 表 → Host Replay → worklog 四段 → open 非空则改构造
```

不要等搜完再分析。`Replay reject ≠ E`。

## 增长符合预期

新行命中义务谓词 → 在 worklog 记录证据，从 `open` 拿掉该义务。

## 增长不符合预期

目标未命中、rewrite 到别的 key、reject 与假设矛盾：

```text
已构造行
  → 对照 replay_round.yaml
  → uo-query 差异维 / packing / guard
  → 改控制列再构造
  → 再 Replay
```

优先用真实 witness 当锚点，不要重复同一套盲 mutation。

## 纪律

- 构造优先 CodeMap：目标维 → packing → writers → knobs → 列取值
- 构造失败 ≠ 不可达
- 证据写在 `worklog.md` 与 `runs/` 收据，不要另建 `tg/closure/**`
