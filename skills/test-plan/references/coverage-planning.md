# 覆盖模型（fuse）

把 Primary 转述的测试意图写成 **YAML 覆盖模型**：Dimension partitions / classifier、L0–L3。正式 `plan.md` 由 Primary 散文 + 本窗 YAML 经 `plan_promote` 拼成。

子代理禁止 Write；最终消息只交 YAML。不要写三节散文。

## 输入 / 输出 / 停

读：`tg/init.yaml`、注入的 scope 回答。没有 init → 停，去 `/tg-init`。scope 没说清要测什么 → 停，让 Primary 再问 scope，不要自己改成全量 TilingKey。

交回：`schema: tg-plan/v3` YAML。禁止 Write。

完成：每个 Dimension 有 controls、≥2 partitions、结构化 classifier；coverage 含 L0–L3；谓词都是 mapping `op=`。

## 步骤

1. Dimension root 到 controls。列必须在 init 列或 `added_columns`。
2. 划 semantic partitions。不是枚举原始 B/N/S/D。
3. 为每个 Dimension 定义 deterministic classifier。`requires` 必须是 Replay 能给的 `case.*` / `replay.*` / `probe.*`。
4. 删除 unobservable / uncontrollable / 与意图无关的轴。
5. L0：每 partition 一个 witness。无 Dimension 时 L0 可空。
6. L1：只选 UO 有交互的 pair，并写 `reason`。
7. L2：只选有明确高阶实现关系的 tuple。
8. L3：每个 Guard 生成最小 negation obligation。
9. 用户**点名**全量 TilingKey 才 `coverage.enumerate: legal_keys`。禁止自行 `mode: T=D`。

## 常驻判断

```text
accuracy PASS 但 Evidence 没打到 ≠ 已覆盖
Host TilingKey HIT ≠ Target HIT（除非 evidence 就是那条 field）
自由文本谓词不得进 YAML
只有 confirmed 控制关系才能写成确定 classifier
```

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 没有 init.yaml | 停，去 `/tg-init` |
| scope 没说清测什么 | 停，回 Primary / scope；不要编全量 key |
| 用户点名全量 tilingkey | `enumerate: legal_keys` |
| 某维控不到列 | `untestable` + reason |
| 缺列或缺生成器 | `test_harness_gap` |
| 用户没点精度/性能 | `oracle: []` |

## 反模式

- 写 plan.md 散文三节（那是 Primary 的）
- 默认全量 Key
- 把 unresolved / partial 绑定写成确定 classifier
- Write 磁盘
