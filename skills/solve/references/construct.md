# 构造用例

为 worklog 围栏里仍 OPEN 的义务交回能跑的行或引擎配方。正式 `tg/cases.*` 只在 certify 写出。本步禁止 Write。

尺子是 `plan.md` 的 Target / Dimension / Guard 谓词。引擎用 Replay 观察包分类；LLM 不得宣布 HIT。

列是控制面。显式 `rows` 必须填满 `init.yaml` 列，runner 才能用 `--case` 直接吃。

## 输入 / 输出 / 停

读：已批准 `plan.md`、`init.yaml`、`tg/worklog.md` 围栏（OPEN 义务）。计划未批准 → 停。

交回：YAML（`columns`+`rows` 和/或 `recipe`）。禁止 Write `parts/`、`staging`、`tg/cases.*`。

完成：本轮只打 OPEN 义务；条件简单可一次交多行；全量 TilingKey 只交 recipe，禁止枚举行。

## 步骤

1. **读 OPEN 义务。** 自己决定本轮交多少：dtype / layout / 显式 Guard 翻转可以一批多行。禁止为凑数盲铺笛卡尔。
2. **按 construct_hint 与 predicate 填控制列。** hint 只提示第一步往哪搜，不算对不算错。
3. **填满其余列。** defaults 或 recipe。空格会让 `--case` 崩。
4. **上轮 MISS / UNKNOWN。** 读 worklog refinement，对照**同一条**义务再填。
5. **全量 legal keys。** plan 写了 `coverage.enumerate: legal_keys` 时只交 recipe，禁止列出 8000 行。
6. **不可达。** `evidence.kind=source_proof` 时读 `skills/source-proof/SKILL.md`。`REFUSE` 不够当不可达。

## 列值类型

行值的类型必须和 `plan.md` 谓词字面量一致，两边都以 `init.yaml` 的
`domains.<col>.profile.inferred_type` 为准：

- `int` / 数值型 → 交数字，**不加引号**：`sparse_mode: 4`
- `enum-string` / 字符串型 → 交字符串：`Input_Layout: BNSD`

引擎的 `eq` / `in` 是**严格比较**，`'4' == 4` 为假。从现有 case 表挑行当基底时，
CSV / xls 读出来的都是字符串，**必须按上面的类型转换后再交**。类型不对不会报错，
但对应义务会静默 MISS，worklog 永远闭合不了。

## 常驻判断

```text
HIT / REWRITE / REFUSE 是 Host tiling 裁决
Target HIT 由引擎 coverage_eval 判定
accuracy PASS 但 Target MISS ≠ 已覆盖
```

`uo_digest` 对不上 init → 停，去 `/tg-init`。缺列或缺生成器 → 写 `test_harness_gap`。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 计划未批准 | 停 |
| OPEN 义务少且条件简单 | 一次交多行 |
| `enumerate: legal_keys` | 只交 recipe |
| 上轮 MISS | 按 refinement 改列 |
| 行缺 init 列 | defaults / recipe 补齐 |
| 缺列 / 缺生成器 | 停并写缺口 |

## 完成勾选

- [ ] 只打 OPEN 义务，没有盲铺笛卡尔
- [ ] 显式行填满 init 列
- [ ] 每列值的类型对齐 `init.yaml` 的 `domains.<col>.profile.inferred_type`（`int` 列不加引号）
- [ ] 逐条 OPEN 义务核对过：本轮交的行里，至少有一行能让它的 partition 谓词为真
- [ ] 全量 key 未枚举行
- [ ] 没有 Write 磁盘

## 输出形状

```yaml
columns: [B, N, S, dtype]
rows:
  - {B: 1, N: 8, S: 128, dtype: fp16}
recipe:
  kind: enumerate_legal_keys
  batch_size: 256
  fillers: {dtype: fp16}
```

可以只有 `rows`、只有 `recipe`，或两者都有。

## 反模式

- Write `construct_cases/parts` 或覆盖 `tg/cases.*`
- 丢掉谓词盲搜合法 Key
- 未点名就造全量 TilingKey
- 用 Host `HIT` 当作 Target 已覆盖
