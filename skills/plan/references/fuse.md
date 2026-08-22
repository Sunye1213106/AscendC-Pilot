# 融合测试计划

把 `tg/init.yaml` 与 Planning Context 写成一份 `plan.md` 草稿：上半散文（这次为什么测），下半 YAML 义务表。正式文件由 `plan_promote` 写入。本步是融合，不是先套全覆盖再贴标签。

Planning Context **就是** `runs/.../plan_scope/parts/purpose.md`（外加用户意图 / handoff）。没有 purpose → `PLAN_SCOPE_REQUIRED`，回 scope，不要用「默认测一遍合法 Key」顶上，也不要在 init 与 plan 之间自己再查一轮图。

## 输入 / 输出 / 停

读：`tg/init.yaml`（列、生成器、精度/性能入口）、`plan_scope/parts/purpose.md`。没有 init → 停，去 `/tg-init`。没有 purpose → 停，回 scope。

写：计划草稿。批准前可变；`approved` 写在正式 YAML 围栏里，本步不自称已批准。

完成：每条进表义务都有 `id, why, uo, control, class, hit, cover`，且能 root 到可控列。

## 步骤

1. **读 init。** 列、mapping、`generate_inputs`、`modes.precision` / `modes.perf`。缺列或缺生成器的事实带到义务闸门，不要假装能构造。
2. **拆意图。** Planning Context 就是 purpose.md。来源还可以叠加 `--intent`、对话、`ce/plan/*_plan.md`、`session_handoff.md`。禁止另写意图 YAML。有意图就拆精度考虑 / 性能考虑（可重叠）。都没有 → 默认 L0，仍要写出能 root 的精度/性能义务。
3. **每条目标查图 root 到列。** 义务必须落到 `init.yaml` 的 CSV/XLS 列，不是全部合法 Key。依赖参数（轴∈rank、`dim_*` 派生）用 recipe 复算，不单独进 cover 维。
4. **展开义务，选覆盖层。**
   - L0：每维一次
   - L1：成对
   - L2：有界笛卡尔
   - L3：异常（空 tensor / inf/nan / 对齐+1 / 非法 range）
   不要把特殊值铺进 L0/L1 的每一组 shape。
5. **精度 / 性能映射。** 领域风险见本窗装载的 knowledge。把风险写成义务时，id 只从本窗装载的场景目录取，不要自造。口径来自 init 的 harness mode，不是 Host HIT。怎么跑脚本只抄 `tg/init.yaml`。
6. **闸门。** root 不到 → `untestable` + `reason`，不进义务表（不要写成 `class: untestable`）。缺列 / 缺脚本 / 生成器造不出 → `test_harness_gap` 说明书，先 `/ce-apply` 改测试仓，禁止 start solve。

## 常驻判断

禁止默认 T=D / `tilingkey_full_coverage`。全量 tilingkey 只在 Planning Context 点名时做。

指标只有 `replay` 和 `derived`。没有第三类「上板误差/耗时」可写进义务。Host HIT 关不了 `P-*` / `F-*`。

YAML 字段：`id, why, uo{query,span}, control{columns,recipe}, class, hit, cover`。缺字段不要进表。

融合顺序是「意图 → 义务 → 列」，不是「合法 Key 矩阵 → 贴场景标签」。预算保持有限；3–8 条性能义务已经够，不要枚举全部 legal key。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 没有 init.yaml | 停，去 `/tg-init` |
| 没有 purpose.md | `PLAN_SCOPE_REQUIRED`，回 scope |
| 意图只说「测准」 | 拆精度义务，对照 scenario-catalog 选 `P-*` |
| 意图点名性能 / init 有 `modes.perf` | 对照 catalog 选 `F-*`，带 `F-SHAPE-TYPICAL` |
| 意图点名全量 tilingkey | 才做全量；否则禁止 T=D |
| 某目标 root 不到列 | `untestable` + reason，不进表 |
| 缺列或缺生成器 | `test_harness_gap`，禁止 start solve |
| 没有意图 | 默认 L0，仍要能 root 的精度/性能义务 |

## 完成勾选

- [ ] 每条进表义务有 `id, why, uo, control, class, hit, cover`
- [ ] 每条能 root 到可控列；依赖维走 recipe
- [ ] 没有默认全量 Key；L3 特殊值没有铺进 L0/L1
- [ ] 精度口径来自 harness mode，不是 Host HIT

上半散文说明这次为什么测。下半只放能执行的义务。

## 循环

1. 确认 init 在。确认 Planning Context 在。缺一则停。
2. 把意图拆成「必须证明什么」。没有意图就 L0，仍写出能跑的精度/性能义务。
3. 每条义务：查图 → root 到列 → 选 L0/L1/L2/L3 → 填 YAML 字段。
4. 领域风险对照 knowledge，再映射到 catalog 的 `P-*` / `F-*`。全量 Key 只在点名时。
5. 过闸门：root 不到进 untestable；缺列/生成器进 gap，不要进义务表。

`cover` 是有界的。L3 才放空 tensor / inf / 对齐+1 / 非法 range。依赖参数走 `control.recipe`，不要当笛卡尔维。

## 输出形状

```yaml
id: L0-dtype
why: 默认覆盖，证明主 dtype 路径可跑
uo: {query: InputDType, span: "..."}
control: {columns: [dtype], recipe: []}
class: precision
hit: derived
cover: L0
```

进不了表的另列 `untestable.reason` 或 `test_harness_gap` 说明书。不要写成 `class: untestable`。

## 指针

覆盖层、易错点、Planning Context 形状由本窗装载的专表给出，不要在本文件再链一层。
