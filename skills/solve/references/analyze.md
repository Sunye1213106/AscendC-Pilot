# 对照本轮

构造 + Replay 刚结束。先按 **evidence 是否对上** 切开，再只对 `TARGET_MISS` 做分析。本步写 worklog 草稿：记下命中、分类、引理、下轮改哪几列。

尺子是 `plan.md` 里该变量的 `evidence`。Host tiling `HIT` 只有在 evidence 就是那条 TilingKey / 字段时才等于 `TARGET_HIT`。Replay 原始裁决回答「Host 接不接受、改没改 key」；evidence 回答「这次要测的那个状态打到了没有」。两个问题叠在一起，MISS 会被解释成「其实也算命中」。

```text
accuracy PASS 但 TARGET_MISS ≠ 变量已覆盖
```

文首 `open:` 列出仍未 `TARGET_HIT` 的变量 id。open 非空不得假装本轮已闭合。

## 输入 / 输出 / 停

读：本轮行、Replay 收据、计划 `variables[].evidence`（及可选 `oracle`）、init 列、已有引理。写：本轮 worklog 草稿。

完成：每个本轮变量标成 `TARGET_HIT` 或仍 open + 原因；MISS 已分类；下轮改哪些列已写清。

缺 Replay 收据 → 该变量保持 open（`UNKNOWN`），不猜命中。

## 步骤

1. **先切两堆。** 拿该变量的 evidence（字段 / 谓词 / `TG_PROBE` / 源码引理）对照本轮收据。
   - 对上 → `TARGET_HIT`，进 R。不再分析。
   - 对不上 → `TARGET_MISS`，进入分类。
   - 缺收据 / 探针没打出来 → `UNKNOWN`，open。
2. **oracle 后置。** 仅对已 `TARGET_HIT` 且 `oracle` 非空的行看 harness 收据。缺收据 → `harness_missing`，open。精度 PASS 不回写为变量已覆盖。
3. **MISS 先分类。** 按类归堆，不按 case 写散文。桶见本窗装载的失败模式表。先认：`REWRITE`、`REFUSE`、`CRASH`/`NOT_RUN`、构造错（列 / recipe）、evidence 没打到、未声明态。
4. **分类 + 源码证明。** 每一类写成可反驳的 P⇒Q，读 `skills/source-proof/SKILL.md`。结果记进 worklog 引理段。`REFUSE` ≠ 不可达，也不是 E。
5. **指导下轮。** 用引理写「改哪几列、仍用哪条 evidence」。更新 `open:`：能关的写证据窗口，不能关的写还缺什么观测。

## 常驻判断

闭合账本：`T = (R ∩ T) ∪ E` 且 `R ∩ E = ∅`。R 来自 `TARGET_HIT`（加已点名的 oracle 通过）。E 只来自经审查的源码引理。`Replay reject ≠ E`。

`HIT / REWRITE / REFUSE` 仍是 Host tiling 原始裁决，与 `TARGET_HIT` 分开记账。worklog 的 `open:` 写变量 id，下一轮 construct 才能对上 direction。

完整性用语（全部 / 唯一 / 从不）依赖经审查引理。本步最多提出或更新线索。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| evidence 对上 | `TARGET_HIT`；这条不必再推引理 |
| Host `HIT` 但 evidence 是别的字段 | 仍可能 `TARGET_MISS` |
| `REWRITE` / `REFUSE` | 分类后推引理，不是 E |
| `CRASH` / `NOT_RUN` | 环境；open |
| 精度 PASS、evidence 没打到 | 变量仍 open |
| 列填错 / recipe 错 | open，回构造 |
| 「搜索没找到」 | 不是不可达 |

## 完成勾选

- [ ] 先按 evidence 切堆
- [ ] `TARGET_HIT` 已进 R；MISS 已分类并有下轮改列
- [ ] `open:` 是变量 id，与正文一致
- [ ] 没有签发、没有改 cases

## 循环

1. 取出本轮每条行的变量 id、evidence、Replay / 探针收据。
2. 对上 → `TARGET_HIT`。对不上 → 归类。
3. 每类写成 P⇒Q；能证 / 能驳都写进引理段。
4. 写下轮构造。更新 `open:`。空了才能谈闭合。

worklog 是给下一轮构造看的。只记现象、不写「改哪几列」，下一轮就会重复盲搜。

## 输出形状

```text
open: [V-dtype — TARGET_MISS: tiling_key 未到预期维]
```

然后三块：`TARGET_HIT`（变量 + 证据窗口）；`TARGET_MISS`（类 → 观测 → 引理 → 下轮改哪列）；引理清单。

## 指针

预期外分类见本窗装载的失败模式表。硬命题：`skills/source-proof/SKILL.md`。已有引理先读其 `INDEX.md`，再最多打开 3 份正文。
