# 对照本轮

构造 + Replay + `coverage_eval` 刚结束。引擎已经把义务标成 CLOSED / MISS / UNKNOWN / REDUNDANT / GUARD_LEAK。本步**只处理 MISS / UNKNOWN**：哪个 Control 该改、UO 有无额外约束、是否该走 source-proof。

禁止宣布 HIT。CLOSED 由引擎写入 worklog 围栏。`GUARD_LEAK` 不是构造失败：停止 refine，留给 CE。

```text
accuracy PASS 但 Target MISS ≠ 已覆盖
空 open: [] 散文不是签发条件
```

## 输入 / 输出 / 停

读：本轮 Replay 收据、`tg/worklog.md` 围栏、`plan.md`。写：无。交回 refinement YAML。

完成：每个 MISS / UNKNOWN 有下轮改哪些列；GUARD_LEAK 已点名停 refine。

缺 Replay 收据 → 保持 UNKNOWN，不猜命中。

## 步骤

1. **只看 MISS / UNKNOWN。** CLOSED / REDUNDANT 不再分析。GUARD_LEAK 停止。
2. **分类。** 桶见本窗失败模式表。先认：`REWRITE`、`REFUSE`、`CRASH`/`NOT_RUN`、构造错、谓词没打到、未声明态。
3. **指导下轮。** 写「改哪几列、仍打哪条义务」。
4. **不可达。** 只有 `source_proof` 才能标 `PROVED_UNREACHABLE`。`REFUSE` ≠ 不可达。

## 常驻判断

`HIT / REWRITE / REFUSE` 仍是 Host tiling 原始裁决，与 Target HIT 分开记账。

完整性用语（全部 / 唯一 / 从不）依赖经审查引理。本步最多提出线索。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 引擎 CLOSED | 不再分析 |
| MISS | 改 control 列再打同一义务 |
| UNKNOWN | 缺收据 / 探针；不要假装 HIT |
| GUARD_LEAK | 停 refine，留给 CE |
| Host `HIT` 但 Target 是别的字段 | 仍可能 MISS |
| 「搜索没找到」 | 不是不可达 |

## 完成勾选

- [ ] 没有宣布 HIT
- [ ] MISS / UNKNOWN 有下轮改列
- [ ] GUARD_LEAK 已停
- [ ] 没有 Write 磁盘、没有改 cases

## 输出形状

```yaml
refinement:
  miss:
    - obligation: O3
      change: {S2: "tile*k+1"}
      note: "aligned 没打到 remainder"
  unknown:
    - obligation: O9
      need: "replay.s2Inner"
  stop: []
```

## 指针

预期外分类见本窗失败模式表。硬命题：`skills/source-proof/SKILL.md`。
