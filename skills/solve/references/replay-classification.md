# Replay 分类

构造 + Replay + `coverage_eval` 刚结束。引擎已经把义务标成 CLOSED / MISS / UNKNOWN / REDUNDANT / GUARD_LEAK。本步只处理 MISS / UNKNOWN：选下一动作，不证明、不记账、不写 exclusion。

MISS / UNKNOWN 是观测。`refine` / `proof_request` / `stop` 是动作。不要混在一起。禁止宣布 HIT。`GUARD_LEAK` 不是构造失败：停止 refine，留给 CE。

```text
accuracy PASS 但 Target MISS ≠ 已覆盖
空 open: [] 散文不是签发条件
REFUSE ≠ 不可达
搜索没找到 ≠ 不可达
```

## 输入 / 输出 / 停

读：本轮 Replay 收据、`tg/worklog.md` 围栏、`plan.md`。写：无。交回 `actions` YAML。

完成：每个 MISS / UNKNOWN 落到 `refine`、`proof_requests` 或 `stop` 之一。GUARD_LEAK 已点名停 refine。

缺 Replay 收据 → 保持 UNKNOWN，不猜命中。硬命题不要本步证明：发 `proof_request`。

## 步骤

1. **只看 MISS / UNKNOWN。** CLOSED / REDUNDANT 不再分析。GUARD_LEAK 停止。引擎若标了 `HARNESS_CONTROL_GAP` / `HARNESS_OBSERVATION_GAP` / `PLAN_INVALID`，不要回 construct。
2. **映射动作。** 只有 `CASE_REFINABLE` 才 `refine`。反复 `REWRITE` / `REFUSE` 且不像填错列 → `proof_request`（层 + P⇒Q）。缺口/计划无效 → `stop`。
3. **refine 只写列。** 「改哪几列、仍打哪条义务」。不要写 lemma，不要更新 worklog E。

## 现象 → 动作

| 现象 | 动作 |
| --- | --- |
| 引擎 CLOSED | 不再分析 |
| MISS 且 `CASE_REFINABLE` | `refine`：改 control 列再打同一义务 |
| Host 接受但 key ≠ 目标（REWRITE） | 先 `refine`；同族反复出现再 `proof_request` |
| Host 拒绝（REFUSE） | 不是 exclusion。可 `refine` 或 `proof_request` |
| 列填错 / recipe 错 / shape 不合法 | `refine` 回构造 |
| 跑了但对不上字段 / 探针 | `refine` 或 `stop`（`HARNESS_OBSERVATION_GAP`） |
| 想用 Host `HIT` 关精度/性能 | `stop`（缺 harness / 错阶段） |
| CRASH / NOT_RUN | `stop`（环境） |
| 无关维系统性增长 | `stop` 盲搜，改已有观测上的控制列 |
| UNKNOWN 且 `HARNESS_OBSERVATION_GAP` | `stop`，不要假装换 case 能修好 |
| GUARD_LEAK | `stop`，留给 CE |
| HARNESS_CONTROL_GAP / PLAN_INVALID | `stop`，回 plan |
| 「搜索没找到」 | 不是不可达；不够则 `proof_request` 或保持 OPEN |

## 完成勾选

- [ ] 没有宣布 HIT
- [ ] 没有写 exclusion / lemma / `PROVED_UNREACHABLE`
- [ ] 每个 MISS / UNKNOWN 有且仅有一类动作
- [ ] GUARD_LEAK 已停

## 输出形状

```yaml
actions:
  refine:
    - obligation: O3
      seed_changes: {S2: "tile*k+1"}
      note: "aligned 没打到 remainder"
  proof_requests:
    - obligation: O7
      claim:
        layer: host
        premise: "..."
        conclusion: "target path unreachable"
      motivation:
        kind: repeated_rewrite
        observations: ["..."]
  stop:
    - obligation: O9
      reason: HARNESS_OBSERVATION_GAP
```
