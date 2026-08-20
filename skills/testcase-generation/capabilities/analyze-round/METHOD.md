# TG analyze-round

按 case 写 `worklog.md` 四段。正式文件由 `analyze_promote` 写入。

本步 refs：`references/oracle.md`、`references/closure-gotchas.md`。

## 文首

```text
open: [未闭合义务 id]
```

空表写成 `open: []`。

## 每个 case 四段

1. **场景与命中依据**：可同时 replay+derived；key/TD 对照谓词；公式代入对照结果。
2. **构造过程**
3. **怎么优化/收窄**
4. **引理**：span 来自 uo-query。`Replay reject ≠ E`。

需要改构造时保持义务在 `open` 中，不要假装闭合。
