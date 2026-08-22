# 求解方向与观测

把 `tg/init.yaml` 与 `targets.yaml` 写成 `plan.md` 草稿：上半散文，下半 YAML。正式文件由 `plan_promote` 写入。本步回答两件事：每个独立条件第一轮怎么命中，以及 Host 跑完用哪条观测证明打到了。

Planning Context **就是** `runs/.../plan_scope/parts/targets.yaml`（外加用户意图 / handoff）。没有 targets → `PLAN_SCOPE_REQUIRED`，回 scope。

`direction` 是第一轮提示，不准也可以。`evidence` 是尺子，solve 靠它迭代。

## 输入 / 输出 / 停

读：`tg/init.yaml`、`plan_scope/parts/targets.yaml`。没有 init → 停，去 `/tg-init`。没有 targets → 停，回 scope。

写：计划草稿。批准前可变；`approved` 写在正式 YAML 围栏里，本步不自称已批准。

完成：每个变量有 `direction` 与 `evidence`；`ladder` 含 L0–L3；未指定时 L0、L1 非空（变量少于 2 个时 L1 可空）。

## 步骤

1. **读 init 与变量表。** 列、encoding、生成器。direction 点名的列要落在 init 列上；encoding 坑写进方向说明，不要当字面长度。
2. **每个变量写大致方向。** 什么影响它、第一轮往哪边填。不准也可以：`v` 空走 merge；确定性跟 isDeterministic / 形状有关；tail 跟余数有关、tile 看 Replay。不要把闭式反解当完成条件。Host 派生字段写明「先造候选，跑 Replay 再看」。
3. **每个变量写死 evidence。** Host 编译跑完看哪条观测。口径见本窗装载的观测表。缺观测字段不要进表。
4. **填 ladder。** L0 每变量一次；L1 成对；L2 有界笛卡尔；L3 异常。未指定方向：L0、L1 填满（默认 TilingKey 维成对），L2/L3 为空。禁止默认 T=D。L3 特殊值不铺进 L0/L1 的每一组。
5. **可选 oracle。** 用户点了精度/性能才写 `oracle`。未指定不要自动挂。Host 命中 TilingKey 不是精度口径。
6. **闸门。** 大概也控不到列 → `untestable` + `reason`。缺列 / 缺生成器 → `test_harness_gap`，禁止 start solve。
7. **先写散文三节，再写 YAML。** 人读散文；solve 读围栏。

## 常驻判断

未指定时 ladder 只填满 L0+L1，L2/L3 留空。全量 tilingkey 只在意图点名时做。

`direction` 是第一轮提示，solve 用 evidence 迭代。`evidence` 含糊则变量还没进表。

```text
accuracy PASS 但 Evidence 没打到 ≠ 变量已覆盖
Host TilingKey HIT ≠ TARGET_HIT（除非 evidence 就是那条 field）
```

依赖参数（轴∈rank、`dim_*`）写进 direction note。未指定时 solve 默认生成 L0+L1。L2/L3 写在计划里，用户点名才造。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 没有 init.yaml | 停，去 `/tg-init` |
| 没有 targets.yaml | `PLAN_SCOPE_REQUIRED`，回 scope |
| 未指定方向 | TilingKey 维；ladder L0+L1 非空；L2/L3 空 |
| 意图点名全量 tilingkey | 才做全量；否则禁止 T=D |
| 想一次算对 s2Inner | 方向里写「Replay 后再看」，不要装精确公式 |
| 某变量控不到列 | `untestable` + reason |
| 缺列或缺生成器 | `test_harness_gap`，禁止 start solve |
| 用户没点精度/性能 | `oracle: []` |
| 想用 Host HIT 当精度 | 禁止；oracle 命中之后才跑 |

## 完成勾选

- [ ] 散文三节：测什么 / 第一轮怎么造 / 怎么知道打到了
- [ ] 每个变量有 direction（列或 Replay 后再看）和 evidence
- [ ] ladder 含 L0–L3；未指定时 L0、L1 非空，L2/L3 空
- [ ] 没有默认全量 Key；L3 没铺进 L0/L1
- [ ] 没有自称已批准

## 循环

1. 确认 init 与 targets.yaml。缺一则停。
2. 逐个变量：方向 → 观测。观测不准就还没完成。
3. 填 L0–L3。未指定只填 L0+L1。
4. 过闸门。写散文，再写围栏。

## 输出形状

散文标题固定：`## 测什么`、`## 第一轮怎么造`、`## 怎么知道打到了`。然后：

```yaml
schema: tg-plan/v2
intent: default_tilingkey
variables:
  - id: V-dtype
    symbol: InputDType
    direction: {columns: [dtype], note: "改 dtype 列"}
    evidence: {kind: replay_field, field: tiling_key}
ladder:
  L0: [V-dtype]
  L1: []
  L2: []
  L3: []
oracle: []
```

变量 ≥2 时 L1 写配对。进不了表的另列 `untestable.reason` 或 `test_harness_gap`。

## 反模式

- 精确反向切片当完成条件
- 默认全量 Key
- 缺 evidence 进表
- 用 Host HIT 关精度/性能

## 指针

观测种类与优先级见本窗装载的观测表。硬命题：`skills/source-proof/SKILL.md`。
