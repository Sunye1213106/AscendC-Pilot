# 构造用例

为 OPEN 义务交回 `schema: tg-solve-fill/v1`。引擎按 Plan 谓词 + 你的 probe seed 展开行。禁止 Write，禁止手写 `rows`。

尺子是 `plan.md` 的 Target / Dimension / Guard。引擎用 Replay 观察包分类；LLM 不得宣布 HIT。

## 输入 / 输出 / 停

读：已批准 `plan.md`、`init.yaml`、引擎写出的 `tg/solve_index.yaml`。计划未批准 → 停。

交回：fill YAML（`baseline` / `hits` / 可选 `guard_hits` / 可选 `unreachable`）。禁止 Write `parts/`、`staging`、`tg/cases.*`。

完成：每个 `needs_hit` 臂有 seed；`auto: false` 的 Guard 有 miss 见证。不要枚举 leftover 格子。

## 步骤

1. **读 index。** `auto` 已有 case seed。只反解 `needs_hit`（probe/replay）。
2. **baseline。** HIT 路径恒成立的入口列。不要写 Guard 杀整值。
3. **hits。** 每个 needs_hit 臂改哪些 case 列能让 `cuts` 上的 probe/replay 成立。两臂取值必须能分开。禁止 `seed: {}`。
4. **guard_hits。** 仅 `auto: false`。
5. **unreachable。** 只有能证明列值冲突的臂组合。其余留给引擎合并。

## 列值类型

int 列交数字不加引号；enum-string 交字符串。

## 常驻判断

```text
HIT / REWRITE / REFUSE 是 Host tiling 裁决
Target HIT 由引擎 coverage_eval 判定
不要手写义务条数，不要交 columns+rows
```

## 输出形状

```yaml
schema: tg-solve-fill/v1
baseline: {is_deter: 1}
hits:
  - {dim: D-align, arm: p-even, seed: {B: 4}}
  - {dim: D-align, arm: p-odd, seed: {B: 3}}
guard_hits: []
unreachable: []
```

## 反模式

- 交 `columns` + `rows` 或枚举 leftover 笛卡尔
- 为凑数盲铺
- 用 Host `HIT` 当作 Target 已覆盖
- Write `construct_cases/parts` 或覆盖 `tg/cases.*`
