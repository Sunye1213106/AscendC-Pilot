# 弄清要测什么

**何时加载**：立 Target、判缺口、把合取/析取分到 Dimension / Guard 时。

Target 立不住，后面的 partition 全是猜。四道必答门缺一，**这个 Target 不得进 Solve**；缺口写入 `untestable[]`，plan YAML 仍要交，不要猜 partition。

观测词表只认 packet：`controls.case_allowed`、`observation_catalog.replay_allowed`、`probe_candidates` / `branch_locals.probeable`。观测字段与 HIT/MISS 只认命中观测文，本页不重复。字段不在这些名单里：标 gap，不要再查 UO。

## 必答门

| 门 | 问的是 | 缺了写 |
| --- | --- | --- |
| Ownership | 为什么是这次 PR 的行为 | `unverified` |
| Construct | 用什么输入 / 上下文构造 | `control_gap` 或 `harness_gap` |
| Reachability | 满足什么真实路径条件 | `opaque` / `harness_gap` / exclusion |
| Observation | 用什么证明 HIT | `opaque` / `harness_gap` |

可选注释，**不是门**：Seed（现成行数，`0` 合法）、Oracle（命中之后如何判对错）。不要因为 corpus 0 行或「如需要才写 Oracle」而拦 Solve。

### Ownership

不要按「新符号 / 旧符号」判断。

- **PR-owned：** 新增或修改的 predicate、`&&` / `||` arm、assignment / value、control / data 依赖、删除行为。`pr_regression` Target 只能引用 packet `pr_eligible` 且 evidence 含 ownership 关系的符号。declaration-only 与无方向 neighbor 不得当 Target。
- **Pre-existing support：** 只为 PR-owned 提供入口、输入或上下文的既有逻辑，不单开 Target，也不把其前置整包抄进本写点。
- 无法由 packet 闭合 ownership → `untestable.kind: unverified`。

### Construct

读 `init.yaml`。

- `active + confirmed` = 当前 harness **可确定构造**。只证明 constructable，**不自动等于 classifier**。
- classifier 只选能独立改变 Target 行为的列。`derived` / 运行上下文可参与约束，不要和其源列重复切维。
- `case.*` / `controls` / `construct_hint.columns` 只来自 `controls.case_allowed`。
- `shadowed` / `metadata` / `result` 不提级。
- **construct 未闭合**（`unresolved` / `partial` + `active`，且无 harness 证据）→ `kind: control_gap`，填 `needs_binding`。理论上可能构造，不是本质不可测。
- **身份缺口**（空 `uo.id` + `candidate`）只要 `confirmed` 就仍可构造，不进 `untestable`。
- 当前 harness / 环境确实无法控制 → `kind: harness_gap` 或 `opaque`。激活列不在 `case_allowed` → 只写 `untestable` 并停，禁止用 replay / probe 绕过 construct 缺口。

### Reachability

用 packet `behavior_candidates.*.writers` 找目标写点，回溯对该 write path 有控制依赖的条件。

```text
path    = cond1 ∧ cond2 ∧ ¬early_exit ...
Target  = path1 ∨ path2 ∨ ...
```

- 只记录会改变能否到达**本写点**的条件。early return 只有成立会阻断当前 path 时，才贡献否定项。
- 不按源码顺序把其它 legacy / sibling 分支塞进 Guard。
- 每条条件分类：`direct`（confirmed 输入）/ `derived`（由输入计算）/ `environment`（设备 / 核数）/ `host_local` / `opaque`。
- `environment` / `derived` 不等于不可测；另判断是否可控。
- `host_local` 只有 packet 标明 `probeable: true`（或列入 `probe_candidates`）才可写成 `probe.*`。源码有 `{name} =` 不构成 probe 证据。

漏否定没有任何校验会报错：只交正向合取，建出来的 partition 常常正好走进早退，Target 永久 MISS。

### Observation

每个正式 Target 必须有 HIT 观测。字段、kind、载体分工见命中观测文。没有观测不得进 Solve。

## 合取 / 析取

**新增 `A && B`，且 Target 是「该 write 被执行」：**

- `A∧B` → 该 Target HIT
- `A∧¬B` → 该 Target MISS，通常是 Guard 否定 / L3，不是同一 Target 的另一格
- 若 PR-owned 行为本身包含「新 B 条件造成的抑制」，另建 suppression Target
- 两侧都保持为 candidate obligations。只有 packet 里已经接受的静态证明才能在规划期压掉某一侧；否则 Solve 判定 SAT / UNSAT。不得因「看起来 UNSAT」静默省略

不要写「两侧 SAT 就都建 Target / partition」——那会把 HIT 与 MISS 混成同一面的两格。

**析取 `A || B`：** 整体仍是 Guard。各 arm 是需要隔离的 Dimension。验证某一 arm 时，关掉其它可替代 arm，避免掩盖。`negate_hint` 只是证伪赋值，不是正向 HIT 证据。

## Seed

只报告满足当前 Target 前置条件的现有 case 数量。`0` 合法：没有现成 seed，不代表 Target 不可达，也不代表一定可构造。新行能否生成只看 Construct + `domains` / `constraints`。
