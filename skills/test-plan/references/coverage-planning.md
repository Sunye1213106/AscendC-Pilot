# 覆盖模型

把 Target model 写成 `plan.md`：Dimension partitions / classifier、L0–L3。正式文件由 `plan_promote` 写入。子代理禁止 Write；最终消息交回完整 `plan.md` 正文。

Planning Context 是上一窗捕获的 YAML（Host 注入）。没有 targets → `PLAN_SCOPE_REQUIRED`，回 scope。

`construct_hint` 只提示第一步往哪搜。正式语义是 predicate / partition / guard。

## 输入 / 输出 / 停

读：`tg/init.yaml`、注入的 Target model。没有 init → 停，去 `/tg-init`。没有 targets → 停，回 scope。

交回：完整 `plan.md`（散文三节 + YAML 围栏）。禁止 Write staging / parts。

完成：每个 Dimension 有 controls、≥2 partitions、结构化 classifier；coverage 含 L0–L3；谓词都是 mapping `op=`。

## 步骤

1. **Dimension root 到 controls。** 列必须在 init 列或 `added_columns`。
2. **划 semantic partitions。** 不是枚举原始 B/N/S/D。
3. **为每个 Dimension 定义 deterministic classifier。** `requires` 必须是 Replay 能给的 `case.*` / `replay.*` / `probe.*`。
4. **删除** unobservable / uncontrollable / semantically redundant / 与 Target 无关 的轴。
5. **L0：** 每 partition 一个 witness obligation。无 Dimension 时 L0 可空（单 Target witness）。
6. **L1：** 只选 UO 有交互关系的 pair，并写 `reason`。不是 C(n,2)。
7. **L2：** 只选有明确高阶实现关系的 tuple。
8. **L3：** 每个 Guard 生成最小 negation obligation。
9. **用户点名全量 TilingKey：** `coverage.enumerate: legal_keys`。禁止 `mode: T=D`。引擎展开，LLM 不枚举行。

## 常驻判断

```text
accuracy PASS 但 Evidence 没打到 ≠ 已覆盖
Host TilingKey HIT ≠ Target HIT（除非 evidence 就是那条 field）
自由文本谓词不得进 plan
```

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 没有 init.yaml | 停，去 `/tg-init` |
| 没有 Target model | `PLAN_SCOPE_REQUIRED`，回 scope |
| 未指定方向 | TilingKey 维作 Dimension；L2/L3 空；L1 无交互证据可空 |
| 意图点名全量 tilingkey | `enumerate: legal_keys` |
| 某维控不到列 | `untestable` + reason |
| 缺列或缺生成器 | `test_harness_gap`，禁止 start solve |
| 用户没点精度/性能 | `oracle: []` |

## 完成勾选

- [ ] 散文三节：测什么 / 覆盖什么 / 怎么判定
- [ ] 每个 Dimension 有 controls、≥2 partitions、结构化 predicate
- [ ] coverage 含 L0–L3；L1 pair 有 reason
- [ ] 没有自称已批准；没有 Write 磁盘

## 输出形状

散文标题固定：`## 测什么`、`## 覆盖什么`、`## 怎么判定`。然后 YAML 围栏，`schema: tg-plan/v3`。形状见本窗任务提示。

## 反模式

- 自由字符串当 predicate
- 默认全量 Key / `mode: T=D`
- 缺 evidence 进表
- Write staging 文件

## 指针

观测种类见本窗装载的观测表。硬命题：`skills/source-proof/SKILL.md`。
