---
name: key-relation-miner
description: >-
  Mine TilingKey dimension relations from Clang derivation plus source, then
  emit Case hit recipes and seed skeletons that replay search can run. Use when
  closing overapproximated dims, replacing handwritten proof rules, or when the
  user needs generation-ready artifacts (not just exclusion relations).
---

# key-relation-miner

Agent 读源码 + Clang 派生查漏，产出两层结果：

1. **关系层**（过滤 / 证明候选）— `relations.yaml`
2. **生成层**（命中配方 + 种子骨架）— `hit_recipe.yaml` + `seed_cases.yaml`

**验收以生成层为准。** 只有关系、没有「Case 怎么设才会命中目标叶值」→ 本 skill **失败**。

## 何时用

- 某维 `exactness=overapproximated` / 需要定向造该维某取值
- 用户要支撑 `nudge` / `cone` / `search` 的可执行产物
- 要把 `proof_rules` / 源码条件落成 Case 约束

## 硬规则

1. **先读派生，再读源码。** 禁止跳过 `fag_derive.json`。
2. **关系方向必须可生成。** 每条「when Dim=v ⇒ …」之外，必须有至少一条：
   `Case 字段设定 ⇒ 追求 Dim=v`（写在 `hit_recipe.yaml`）。
3. **分档**
   - `solver_derived`：参与维全 exact 且 UNSAT
   - `reviewed_code_rule`：有行号，维仍 overapprox
   - 生成配方不进 U_sound；只服务搜索
4. **不许**用「语料没见过」当 unreachable；**不许**对无 init 成员填 `Const(0)`。
5. **一次只打一个目标维 + 一个目标叶值**（默认追求稀有/难命中的叶，如 `1`）。
6. **单次探测脚本 < 2min**；全量 derive 除外。
7. **禁止只交 relations。** 缺 `hit_recipe.yaml` 或 `seed_cases.yaml` → verdict 必须是 `blocked`。

## 输入资产

| 资产 | 路径 |
|------|------|
| 派生 | `.probe_cache/fag_derive.json` |
| 桥 | `operators/<op>/<arch>/bridge_spec.yaml` |
| Case 语义 | `operators/<op>/<arch>/input_semantics.py` / `scripts/replay/inputs.py` |
| 搜索提示 | `operators/<op>/<arch>/search_hints.yaml` |
| 手写规则 | `operators/<op>/<arch>/proof_rules.yaml` |
| 语料 | `.probe_cache/replay/*key_cases*.csv` |
| 已有种子（对照，勿照抄交差） | `scripts/replay/search.py` 里 targeted_seeds |

## 工作流

### 0. 清理本维输出

```text
.probe_cache/replay/relation_miner/<Dim>/   # 整目录删掉重建
```

保留 `fag_derive.json`。

### 1. 审计 → `audit.md`

同前：exactness、free_vars、undecided_guards、implicit_defaults、note、blocker 分类。

### 2. Clang 切片 → `clang_slice.yaml`

必须含：

- `def_sites`（赋值 rhs + guards）
- `direct_cone`：bridge 可设的 `VAR_*`
- `soft_vars`：INIT/LOOPELEM/SCHED/UNDECIDED（证明 havoc / 搜索需启发式）
- **`sufficient_ Cond_tree`**（新增）：从源码整理的布尔树，叶节点标成
  - `case_field`：可直接映射到 Case（如 `layout`, `deterministic`, `b`）
  - `host_intermediate`：需启发式逼近（如 `CheckExceedL2Cache`, `blockOuter==aicNum`）
  - `literal_false` / `literal_true`：源码常量

### 3. 关系 → `relations.yaml`

保留 implication / pair_exclusive / value_unreachable，用语料做 runtime gate。  
这些是 **过滤器**，不是交付终点。

### 4. 命中配方 → `hit_recipe.yaml`（必须）

对目标 `(Dim, want_value)` 写充分条件的可执行分解：

```yaml
target:
  dim: IsTndSwizzle
  want: "1"

# 硬约束：生成器必须满足（否则 host 侧几乎必失败 / 维必反）
must:
  case:
    layout: TND                 # Case 字段名，与 inputs.Case / adapter 一致
    deterministic: 0
    # b: {op: lt, value: 129}  # 支持标量或约束对象
  assert_dims_if_hit:           # 命中后应用 relations 的期望
    IsTnd: "1"
    SplitAxis: "5"
    DeterType: "0"
  forbid_dims:
    - {dim: IsNzOut, value: "1"}

# 软目标：不能直接写 Case 的 host 中间量 → 启发式
pursue:
  - id: l2_or_invalid_blk
    host_expr: "(CheckExceedL2Cache() || isLargeInvalidBlk)"
    why: enableSwizzle 左端
    heuristics:
      - knobs: [s1, s2, n2, dtype]
        strategy: grow_volume_not_batch
        note: "靠堆 b 破 L2 会撞 b<129；优先加长序列/头数"
      - knobs: [seq_q, seq_kv]
        strategy: ragged_nonzero
        note: "禁止零长 seq；保持 tailZeroCount==0"
  - id: block_outer_eq_aic
    host_expr: "blockOuter == aicNum"
    why: enableSwizzle 右端
    heuristics:
      - knobs: [s1, s2, n2, b]
        strategy: bn2s2_partition_grid
        note: "对照 DoBn2s2Sparse / 核数分配；无闭式则网格扫"

# bridge：配方里用到的 Case 字段 ↔ VAR_*（便于自动 mutation）
bindings_used:
  layout: VAR_ATTR_INPUT_LAYOUT
  deterministic: VAR_SESSION_DETERMINISTIC
  # ...

# 明确做不到闭式的缺口（仍必须给启发式，不能空着）
unclosed_host:
  - CheckExceedL2Cache
  - blockOuter
```

规则：

- `must.case` 里的键必须是 **真实 Case 字段**（读 `input_semantics` / `Case`），禁止编造 `enableSwizzle=`。
- 每个 `host_intermediate` 必须有 ≥1 条 `heuristics`（knobs + strategy）。
- 对照 `search.py` 已有种子：可以 **改进或参数化**，但要在 `hit_recipe.yaml` 写 `diff_from_legacy:` 说明新在何处；禁止整段复制当唯一产物。

### 5. 种子骨架 → `seed_cases.yaml`（必须）

给出 **可被 Python 直接打成 `inputs.Case(...)` 的字典列表**（至少 4 个，覆盖不同启发式）：

```yaml
# 每条 seed 必须能 import Case 后构造；字段名与 Case 一致
seeds:
  - id: swz_tnd_long_s_n2
    intent: "L2 pressure via long S + heads, b kept <129"
    case:
      layout: TND
      dtype: FLOAT16
      n2: 8
      g: 1
      d: 128
      deterministic: 0
      sparse_mode: 0
      seq_q: [4096, 4096, 3968, 4096]   # 或用说明性写法见下
      seq_kv: [4096, 4096, 3968, 4096]
    expect_if_ok:
      dim_IsTndSwizzle: "1"
      dim_IsTnd: "1"
      dim_DeterType: "0"
    notes: "b=len(seq)=4 <129"

  - id: ...
```

若序列太长不便写死：允许

```yaml
seq_q: {prefix_of: [4096, 3968], batches: 32}
```

并在同目录写一小段 `build_seeds.py`（**可选但推荐**）把 YAML 编成 Case 且 `print` 条数；该脚本必须能在 30s 内跑完 import/构造（**不必**真跑 host）。

### 6. 可选冒烟（强烈推荐）

若环境有 replay runner：对 `seed_cases` 抽 ≤8 条跑 host（总墙钟 <2min）。  
结果写入 `smoke.md`：`ok` / `dim_IsTndSwizzle` / 是否命中。  
未跑 host 时 verdict 只能是 `recipe_ready_unverified`。

### 7. 验收 → `verdict.md`

四选一（比旧版更严）：

| verdict | 含义 |
|---------|------|
| `closed_exact` | 维已 exact，且配方+关系都有 |
| `recipe_ready` | 维可仍 overapprox，但 hit_recipe+seed_cases 齐全，冒烟有命中或未跑冒烟但配方自洽 |
| `recipe_ready_unverified` | 有配方+种子，未跑 host |
| `blocked` | 缺配方/种子，或只有 relations |

**失败条件（必须写 blocked）：**

- 只有 `when Dim=1 ⇒ other` 没有 `must.case`
- `must.case` 字段名在 Case 上不存在
- soft host 条件没有 heuristics
- 种子无法映射到 Case

## 输出目录（齐全才算过）

```text
.probe_cache/replay/relation_miner/<Dim>/
  audit.md
  clang_slice.yaml          # 含 sufficient_cond_tree
  relations.yaml            # 过滤器
  hit_recipe.yaml           # 必须
  seed_cases.yaml           # 必须
  build_seeds.py            # 推荐
  smoke.md                  # 可选
  verdict.md
```

## 与搜索管线的衔接（写进 verdict）

说明下游应如何消费（无需本 skill 改引擎，但要写清）：

1. `must.case` + `forbid_dims` → preflight / 变异边界  
2. `pursue.heuristics` → cone/nudge 的网格轴  
3. `seed_cases` → 直接并入 cover/search 种子池  
4. `relations` → 结果过滤与义务聚类  

## 已知难维期望

| 维 | 最低可接受 verdict |
|----|-------------------|
| IsTndSwizzle | `recipe_ready` / `_unverified`（含 L2/blockOuter 启发式 + ≥4 TND 种子） |
| SplitAxis / IsNzOut / IsBn2MultiBlk | 同上，配方围绕 size/grid + 旁效补偿 |

## 反例

- 只交 8 条 implication 声称完成  
- `must` 里写 `enableSwizzle=true`（非 Case 字段）  
- 整份复制 `search.py` targeted_seeds 无 `diff_from_legacy`  
- 在 overapprox 维上硬写 derived_rules
