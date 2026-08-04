# TilingKey 全覆盖：核查、方案与执行

面向的问题：把 [tiling-key-coverage.md](tiling-key-coverage.md) 描述的流程，从「把不知道压缩成一张有限清单」推进到「这张清单为空」，并且把走通的路径固化成一个弱模型也能复现的 agent。

本文以 FlashAttentionScoreGrad（arch35，19 维 key）为样本，方法本身与算子无关。

写作时间 2026-08-03。所有「已核实」「实测」字样的结论都在本机跑过，命令与输出记在正文里；没跑过的一律标注为推断。

---

## 0. 完成口径

100% 不是让 8705 个声明实例全部被运行时命中——可能存在真死模板。正确的完成条件是双轨的：

```text
∀k ∈ D:  有可复现的 runtime witness  ∨  有 sound 的不可达证书
即       U_sound − R = ∅
```

贯穿全程的第一原则：

> **允许 `U_sound` 太大，不允许它漏掉真实可达的 key。**

这条原则决定了后面每一处取舍。任何让数字变好看但可能缩小真实可行域的改动，都要按「假闭合」处理（见第 9 节）。

---

## 1. 本机环境实况（已核实）

静态侧路径解析成功：

```powershell
python -c "import sys; sys.path.insert(0,'engines/understand-operator/src'); from uo_init import paths; print(paths.explain())"
```

```text
cann_root: D:\TEST\_cann\pkg
ops_root: D:\TEST\ops-transformer
  skipped trimmed tree D:\TEST\_cann\slim: built from a different build_context.yaml
```

slim 树因 `build_context.yaml` 变更而失效，会回退到 `pkg`，clang 解析会慢一些但不影响正确性。

WSL 侧已就绪的部分：

| 依赖 | 状态 | 位置 |
|---|---|---|
| WSL 发行版 | 就绪，注意名字 | `Ubuntu-2204`（**不是** `Ubuntu-22.04`） |
| CANN | 就绪 | `/usr/local/Ascend/cann` |
| host UT so | 已构建 | `/work/ops-transformer/build/tests/ut/framework_normal/op_host/libophost_transformer_ut.so` |
| replay driver | 已构建 | `/work/replay/build/fag_replay` |
| entry 脚本 | **缺失** | `/work/wsl/setup/run_replay.sh` 不存在 |

两个阻塞点：

1. [operator.yaml](../../operators/flash_attention_score_grad/arch35/operator.yaml) 写的 `distro: Ubuntu-22.04` 与实际的 `Ubuntu-2204` 不符。该文件注释本身就预见了这个问题（「a distribution registered by `wsl --install` carries a dot in its name, an imported tarball carries whatever it was imported as」），并留了 `UO_REPLAY_DISTRO` 覆盖。
2. entry 脚本缺失。[runner.py](../../scripts/replay/runner.py) 按固定位置参数调它：

```python
subprocess.run(
    ["wsl", "-d", self.manifest.distro, "-e", "bash", self.manifest.entry,
     _wsl(in_csv), _wsl(out_csv), _wsl(log_txt), "1" if with_log else "0"],
    ...
)
```

所以 wrapper 的契约是 `$1=in_csv $2=out_csv $3=log_txt $4=with_log`，负责 source CANN `set_env.sh`、设 `LD_LIBRARY_PATH` / `LD_PRELOAD` 指向 host UT so、调 `fag_replay`、确保输出里有 `BATCH_DONE`。

---

## 2. 现状核查

### 2.1 成立的判断

**`U` 不是形式健全的上界。** [rule_engine.py](../../scripts/replay/rule_engine.py) 的 `default_book()` 把 human/llm 规则和 solver 规则 merge 成同一本账：

```python
proof = load_proof(package / "proof_rules.yaml")
derived = load_derived(cache / "derived_rules.yaml")
_BOOK = merge(proof, derived)
```

`RuleBook.excluded_by()` 遍历规则时完全不看 `rule.grade`。`Rule` 上的 `grade` 字段目前只是元数据，不影响任何判定。代码里不存在 `U_sound`。

**gate 只是反例门，不是 soundness 证明。** 文件名已经从 `closure_gate` 改成 [replay_runtime_counterexample_gate.py](../../scripts/replay_runtime_counterexample_gate.py)，检查的是 `R ∩ excluded = ∅`。它能拦住误杀已有 witness 的规则（历史上真的拦下过一条会误杀 512 个 key、其中 80 个有真实 witness 的规则），但对「没搜到、实际可达、却被错误排除」的 key 无能为力。

**Clang 没有驱动搜索。** [search.py](../../scripts/replay/search.py) 手写的阶梯：

```python
S_STEPS = [64, 128, 256, 512, 1024, 2048, 4096]
D_STEPS = [64, 72, 96, 128, 192, 256]
D1_STEPS = [16, 32, 48, 64, 72, 96, 128, 192, 256, 320]
```

而 `.probe_cache/mint_detertype.txt` 显示 clang 早已从 `GetDTemplateType` 提取出完整分支链 `d <= NUM64 / NUM128 / NUM192 / NUM256 / NUM768`。手写阶梯就是这串已提取阈值的人肉抄写，**还抄漏了 768**。

**搜索饱和不能当完成条件。** 仓库自己的记录里出现过生成器 shape 修正后 key 从 1883 跳到 3409。饱和曲线只说明当前生成器流形被穷尽了，不说明覆盖完成。

### 2.2 需要修正的判断

**关于 `key-relation-miner` skill 不存在。** 它存在，在 [skills/workflows/key-relation-miner/SKILL.md](../../skills/workflows/key-relation-miner/SKILL.md)，内容完整，`hit_recipe` + `seed_cases` 的强制约束、四档 verdict、反例清单都在。

**关于「剩余四维需要新增四类通用静态摘要」。这条不成立，而且偏差最大。** [loop_summary.py](../../engines/understand-operator/src/uo_init/loop_summary.py) 里已经实现并接线的能力：

| 能力 | 函数 | 已接线处 |
|---|---|---|
| 计数循环 trip count | `loop_bound` | `cardinality_bound` 内部 |
| 跨函数容器身份追踪 | `resolve_param_container` / `_trace_container` | 追不动就拒绝，不少报 |
| 事件互斥判定（Z3） | `guards_exclusive` | `cardinality_bound` |
| **must-def before read** | `guards_cover` | `derive_key_fields.py:1585` |
| **集合基数上界** | `cardinality_bound` | `guard_truth` |
| guard 恒真恒假判定 | `guard_truth` | `derive_key_fields.py:1610` |

`guards_cover` 的 docstring 明确写了它是为消 `fBaseParams.bandIdx` 而生的，而那个变量「minted 出来的自由变量曾阻塞五个维度」。也就是说 must-def 分析不但存在，还成功用过。

真正缺的只有两类：**区间覆盖**（`invalidS1Array`）和 **next-fit 有序装箱**（`coreIdx`）。四类缩成两类，而且 `cardinality_bound` 的「追不动就拒绝」骨架可直接复用于 L2 footprint 的集合基数。

**关于 `domain_violations`。** `docs/debug/current-status.md` 里有一行 `domain_violations: 1`，此前的分析没有提及。有一个维度能算出模板没声明的值，这是 host 与 TPL 的口径冲突。谈 100% 之前 `D` 本身必须可信，这一条要先解释掉。

---

## 3. DeterType 是怎么闭合的

三处修复叠加，[derive_key_fields.py](../../engines/understand-operator/src/uo_init/derive_key_fields.py) 的注释直接点了名：

```python
# Same survival rule as aux_targets: an implicit default whose
# VAR_INIT_ was folded out of value_expr (e.g. a later unguarded
# write under Const(True) reachability replaced the arm) is no
# longer an assumption the solver sees. Keeping the record would
# grade the field overapproximated with empty free_vars — the
# DeterType case — which blocks proofs without describing the
# expression. Dead-arm underapprox is tracked separately.
out.implicit_defaults = [
    d
    for d in out.implicit_defaults
    if str(d.get("variable") or "") in survived
]
```

配合 `_guard` 里的 `and`/`or`/`not` 常量折叠，和 ITE 常量条件直接选臂。

**关键结论：这三处没有引入任何新的语义摘要能力，全是正规化缺陷修复。**

所以「DeterType 还能不能更 exact」是个错问题。该问的是：**还有多少维度是被同一类工具缺陷卡住的？** 第 4 节给出实测答案。

### 3.0 但这次闭合是假的（已实测推翻）

跑 `python scripts/replay_derivation_check.py 4000`，对 exact 维用静态表达式预测再与 runtime 解码值比对：

```text
DeterType  exact  2745 agree / 392 differ  ->  accuracy 87.5%   <-- MISMATCH
```

392 个不一致的模式完全一致：

```text
predicted 全部是 2
actual    1x160, 3x118, 4x78, 0x36
样本      全部 deterministic=1，actual 随 sparse_mode 变化
```

`current-status.md` 说 DeterType 的根只剩 `SESSION_OPTION`。这正是病灶：**表达式丢掉了对 `sparseMode` 的依赖**，于是 `deterministic=1` 时塌缩成常量 2；而真实值由 `CalcleCausalDeterParam` 与 `GetDeterSparseTilingKey` 按 sparseMode 在 0..4 之间选。

病根是 `VAR_INIT_2288AFE53928`（`fBaseParams.deterSparseType`，minted in `CalcleCausalDeterParam`）被折叠掉之后，`implicit_defaults` 的记录又被存活过滤删掉了。折叠只意味着「我们采用了那个默认值」，**不意味着这个假设消失了**。删掉记录让 `exactness` 从 overapproximated 升到 exact，把一个未经验证的默认值包装成了事实。

这是第一原则明令禁止的方向：静态模型缩小了真实可行域，却仍被当成过近似。而且它比一般的假闭合更危险——DeterType 被标为 exact，一旦求解器拿它做 UNSAT，就会排除真实可达的 key，而 runtime gate 只在那个 key 恰好已有 witness 时才拦得住。

**三条推论：**

1. `free_vars = 0` 加 `exact` 不等于正确。`CLOSED` 是必要条件，不是充分条件。
2. `implicit_defaults` 的存活过滤逻辑本身是错的。一个 `VAR_INIT` 从表达式里消失，可能是因为它被真实的无条件写覆盖了（此时删记录正确），也可能是因为它被当成默认值折进了常量（此时删记录就是掩盖）。这两种情况现在无法区分，必须靠 `lit` 出处标记（第 8 节 B 步）分开。
3. **任何维度宣布 exact 之前必须过塌缩检查。** 这条要写进 `coverage_gate`，而不是留给人自觉。

### 3.2 塌缩可以纯静态抓到，不必等 runtime

`value_leaves` 是两个读数的并集：`value_leaves(expanded)`（归一化**前**能到的常量）和 `smt_value_leaves(value_expr)`（归一化**后**能到的常量）。只存并集把最有用的情形藏了起来——**后者严格小于前者，就说明归一化折掉了源码能走的臂**。

[scripts/_probe_leaf_collapse.py](../../scripts/_probe_leaf_collapse.py) 把这个差集算出来。对全部 19 维的结果：

```text
dimension       exactness         free  SMT can return   lost vs expansion  lost vs domain
DeterType       exact                0  [0, 2]           [1, 3, 4]          [1, 3, 4]  <-- COLLAPSED
S1TemplateNum   exact                0  [64, 128, 512]   []                 [0]  (review)
S2TemplateNum   exact                0  [128, 256, 512]  []                 [0]  (review)
IsRegbase       constant             0  [1]              []                 [0]  (review)
```

两类信号强度不同，混在一起这个检查就没用了：

- **`lost vs expansion`（硬）**：同一个派生早一轮还说这个字段能返回这些值，没有任何算子层面的解释能开脱——归一化丢了活臂。而且已经没有自由变量替被丢掉的东西站着了。
- **`lost vs domain`（软）**：可能是真死值（arch35 上 `IsRegbase=0` 不存在），也可能是别的维度短路了它（`S1/S2TemplateNum` 在 `IsEmptyTensor=1` 时读 0，根本不问这个字段的表达式）。这类要 witness 或人来判，不能直接判失败。

**唯一的硬信号是 DeterType，丢的正好是 `[1,3,4]`，与 runtime 实测的 actual 值完全吻合。** 也就是说这个假闭合不需要跑 host、不需要语料，一次毫秒级的纯静态比较就能抓到。

这个检查便宜、通用、不含任何算子知识，正适合做成确定性 gate：`exact` 与 `constant` 的准入条件里加一条「`lost vs expansion` 必须为空」，`lost vs domain` 非空则要求一条 witness 或一份签字的死值说明。

现有的 `domain_violations` 只查叶值**超出** domain（`OutDType` 那种），查不到**塌缩**。两个方向都要有。

### 3.1 这次闭合带来的一个风险

`has_constant_dead_arm` 的作用是标记「表达式里还有 guard 位置的常量」，而 [key_reachability.py](../../engines/understand-operator/src/uo_init/key_reachability.py) 用它决定允不允许求解器对该维做 UNSAT：

```python
# Constant-dead arms make an UNSAT on this dimension unsafe:
# the solver can prove a value impossible that the host
# actually produces. See derive_key_fields.
"underapprox": has_constant_dead_arm(tree),
```

常量折叠会让这个检测不再 fire，从而放开 UNSAT。这在常量确实来自源码（真的写了 `&& false`）时是对的；在常量是派生器自己 assume 出来的时候就是 unsound 的。**这两种 `lit` 在树里目前长得一模一样**，必须加出处标记（见第 8 节 B 步）。

---

## 4. 实测发现：一行提前返回挡住了两个 VAR_INIT

### 4.1 现象

`.probe_cache/mint_detertype.txt` 记录了每个 `VAR_INIT_*` 为什么没被消掉。失败原因不是求解器说不行：

| 变量 | 阻塞维度 | 记录的原因 |
|---|---|---|
| `VAR_INIT_51689D821E98` | 经 DeterSparse 链 | `read site has zero path conditions` |
| `VAR_INIT_2288AFE53928` | `fBaseParams.deterSparseType` | `no read site recorded` |
| `VAR_INIT_36CDA3758519` | `fBaseParams.bandIdx` | `guards_cover -> holds=False reason='not_proven:sat'` |

只有第三个是求解器真的判不出来。前两个是**根本没问求解器**。

### 4.2 原因

[derive_key_fields.py:1579](../../engines/understand-operator/src/uo_init/derive_key_fields.py) 的 `_read_forces_a_write`：

```python
read = self._read_at
if read is None or not read.conds or not pool:
    return False
```

读点没有路径条件就直接放弃。`guards_cover` 里有对称的一处：

```python
if not premise:
    return Implication(False, reason="no_readable_read_guards")
```

**方向是反的。** 这个查询是 `read ∧ ¬(∨writes)` 是否 unsat。读点无守卫意味着前提是 `True`，这是**最弱的前提**；如果 `True ∧ ¬(∨writes)` 都 unsat，那么在任何真实读条件下也 unsat。放弃这个查询，等于把最容易证、结论最强的那个情况扔掉了。

### 4.3 实测验证

写了 [scripts/_probe_empty_premise.py](../../scripts/_probe_empty_premise.py)，用 `GetDeterSparseTilingKey`（normal_regbase.cpp:793..813）真实的五段 if/else-if 写守卫结构：

```text
write@793:  [if] A
write@799: ![if] A ∧  [if] B
write@806: ![if] A ∧ ![if] B ∧  [if] C
write@811: ![if] A ∧ ![if] B ∧ ![if] C ∧ [if] D
write@813: ![if] A ∧ ![guard_clause] B
```

跑 `python scripts/_probe_empty_premise.py`：

```text
read_conds = ()          -> holds=False reason='no_readable_read_guards'
read_conds = (True,)     -> holds=True  reason=''  checked=5
without the closing arm  -> holds=False reason='not_proven:sat'

CONFIRMED: the early return, not the solver, is what leaves VAR_INIT standing
```

第三行是对照组：去掉链尾那段，覆盖立刻证不出来。说明这个查询有判别力，不是恒真的废话。

### 4.4 soundness 论证

把空前提当 `True` 是安全的，逐条检查方向：

- 前提越弱越难 unsat，`True` 是最弱前提，所以由它得出的 unsat 对任何真实读条件都成立。
- 漏收一个写点会让析取变小、更难 unsat，是保守方向。
- `guards_cover` 已有的「读不懂的守卫就丢掉这个写」也是保守方向。

唯一的危险是**多算**一个不存在的写点，而写点来自 AST 收集，多算的风险很低。

`read is None` 同理：不知道读点在哪时，问「写守卫的析取是否恒真」得到的结论对任何读点位置都成立。

**这意味着 `IsBn2MultiBlk` 和 `SplitAxis` 的 INIT blocker 大概率一个修复就掉，不需要新写 `MUST_DEF_BEFORE_READ` 规则族。**

---

## 5. Clang 在系统中的位置

Clang 不是求解器，也不是正确性保证器。它的定位是**带编译上下文、类型、作用域和源码位置的事实提取前端**，外加一件更重要的事：**它是唯一有资格说「这里我不知道」的组件**。

[bridge.py](../../scripts/replay/bridge.py) 的注释把这个纪律写得比任何设计文档都清楚：

```python
# Host tiling state is deliberately absent. `fBaseParams.layoutType` reads
# like it should be `attr input_layout`, and it is not: `SupportTrans2BS2N2GD`
# rewrites TND to BSND when every sequence is the same length, and a later
# `bn2S2RouteLimit` branch rewrites it back. A dimension reading that field
# is not predictable from the inputs, which is exactly what the derivation
# says by marking it `input_derivable: false`. Supplying a guess here would
# turn an honest "unknown" into a confident wrong answer.
```

### 分工

| 组件 | 负责 | 不负责 |
|---|---|---|
| Clang | 事实与溯源：写点、守卫、调用绑定、身份、声明初值、行号、宏展开后的真实路径 | 循环出口性质、数组量词、调度结果、helper 闭式、可达性 |
| 摘要器 | 循环与 helper 语义（区间覆盖、装箱、集合基数） | 判断哪个 key 真能产出 |
| Solver | 组合一致性与 UNSAT | 建模是否忠实 |
| Agent | 提出候选关系与构造策略 | 宣布不可达 |
| Host replay | 最终行为 oracle | 证明不可达 |

遇到建不了模的量，Clang 静态链必须 havoc 出一个自由变量，而不能猜默认值、合并两个不同变量、假定 helper 必经、或用位置不敏感的最后写入覆盖所有路径。仓库历史上这四种错误都犯过。

**Clang 当前的产物已经够用，缺的是消费。** 每个维度都带 `def_sites`（含 guards）、`var_roots`、`premises`、`free_vars`、`exactness`、`implicit_defaults`，而 `search.py` 还在手写它已经算出来的阈值。

---

## 6. 怎么保证 Agent 分析结果正确

先把目标定对：**不可能保证 LLM 分析永远正确，能保证的是「agent 就算错了也不能错误缩小 `U_sound`」**。这比给置信度分数可靠得多。

### 6.1 已有的资产：三道机械闸

[patch_gates.py](../../engines/understand-operator/src/uo_init/patch_gates.py) 是全仓库最有价值的资产，它是**通用的**（不含任何算子知识），三道检查都带反例 witness：

| 检查 | 挡住什么 |
|---|---|
| `check_reads_what_the_code_reads` | 幻觉：条件只能引用那段代码实际读到的变量，「naming one it never sees is invention with the right spelling」 |
| `check_condition_decides_something` | 平凡化：条件必须在合法输入上既能真又能假，恒真恒假等于把分支换成了常量 |
| `check_values_stay_declared` | 自相矛盾：代入后该维取值必须落在模板声明域内，且非空 |

这是正确的范式：**不要求 agent 说真话，只要求它的谎能被机械证伪。**

### 6.2 已有的资产：harness 的权限隔离

`acp` harness 本身就是「权限隔离 + 机械 gate」的现成实现：

- `_act(...)` 里 `output_mode="staged"` 的 producer 只能写 `runs/{run_id}/actions/{id}/parts/**`，canonical IR 路径被自动加进 `forbidden_write_paths`
- [ownership.py](../../pilot/ascendc_pilot/ownership.py) 把 producer 与 finalizer 的写路径分开
- 运行期由 action lease 加 `acp authorize` 强制
- 动作完成判定用 HMAC 签名 receipt，不是文件存在
- `OUTPUT_CONTRACT_PATHS` 做存在性、非空、artifact identity 校验，未知契约 id 直接拒绝 finalize

### 6.3 缺口

1. 三道闸只管 `gap_patch`，**没管 relation miner 的产物**。
2. **通过闸不等于正确。** 一个读合法变量、既能真又能假、值域正确的条件，仍可能是另一个条件。而 `gap_patch.py` 会把 agent 的答案写回 `fld.value_expr` 并重新 `classify_exactness`——**agent 的答案能直接改变 exactness 评级**。这条路必须打出处标记：agent 参与推出来的 exact 和纯静态推出来的 exact，不能在同一张表里叫同一个名字。
3. `uo-gap-resolve` 的隔离纪律没有复制到 relation miner。

### 6.4 输出必须带类型，类型决定权限

| 类型 | 可以 | 不可以 |
|---|---|---|
| `hit_recipe` | 生成用例、扩大 `R` | 排除任何 key |
| `necessary_condition` | 诊断、约束搜索 | 默认缩小 `U` |
| `sufficient_condition` | 构造 witness | 证明条件外不可达 |
| `unreachable_claim` | 进待证队列 | 直接进 `U_sound` |
| `runtime_correlation` | 搜索排序 | 作为逻辑证明 |
| `source_lemma` | 交 AST checker | 未检查前直接排除 |

只有两类能进 `U_sound`：sound 过近似上的 UNSAT，和机器可查的源码引理。

### 6.5 全面性

办法不是让 agent「想得更全」，而是让**遗漏可被枚举**。`free_vars` 与 `unrecorded free_vars = 0` 已经是这个机制：现在不是面对一团未知，而是面对六个具名的量。agent 的任务清单应该由这个清单机械生成，而不是由 agent 自己决定看什么。

---

## 7. 泛化的真正断点

### 7.1 `_from_bindings` 是空壳

[obligations.py](../../scripts/replay/obligations.py) 的设计意图是：维度不再靠 if-ladder，而是通过 `bridge_spec` 的 Binding 反查出可写旋钮。实际实现：

```python
def _from_bindings(case: I.Case, dim: str, want: str) -> list[I.Case]:
    ...
    vars_ = list(field.get("variables") or [])
    if vars_ and all(v not in by_var for v in vars_):
        return []
    return []
```

**两条路径都返回空列表。** 读了 fields、读了 spec、算了 `by_var`，然后无论如何返回空。

而 [search_hints.yaml](../../operators/flash_attention_score_grad/arch35/search_hints.yaml) 里 12 个 `special_generators` 全部指向 `obligations.py` 里手写的 Python 函数。**if-ladder 没有被消除，只是从引擎搬进了 YAML 加注册表。** 换第二个算子要重写 12 个生成器，这就是 P8 走不通的原因。

### 7.2 词汇表已经存在

[bridge_spec.yaml](../../operators/flash_attention_score_grad/arch35/bridge_spec.yaml) 的每条 binding 都带 `kind`：`optional_presence`、`tensor_axis`、`tensor_rank`、`tensor_dtype`、`tensor_numel`、`tensor_values`、`attr`、`context`。这八个 kind 就是通用旋钮的全部词汇。

现在 `materialize` 是**读侧**（Case → env），缺的是**写侧对偶**（`(binding, 目标值)` → Case 变更）。

有了写侧对偶，12 个手写生成器里至少 8 个可以退休：

| 现有生成器 | 可替换为 |
|---|---|
| `pse` / `atten_mask` | `optional_presence` 置位 |
| `input_dtype` / `out_dtype` | `tensor_dtype` |
| `d_ladder` / `s1_ladder` / `s2_ladder` | `tensor_axis` + 自动阈值 |
| `keep_prob` | `attr` |
| `rope` / `d1_pair` | `optional_presence` + `tensor_axis` |

真正需要算子知识的只剩 `tnd_layout`（layout 改写联动整组 shape）和 `deter_sparse`（跨字段自洽）。

**这才是通用 agent 的正确形态：** agent 不是每换一个算子就重读一遍源码堆规则，而是消费一份算子无关的接口——静态派生给出可控旋钮、影响锥、阈值和合法性前提，agent 只在静态说不出话的地方出手，产物受机械 gate 约束，由 host replay 裁决。

---

## 8. 执行方案

分两段：**先由强 agent 亲手做到全覆盖，再把走通的路径固化给弱模型。** 第二段只固化第一段验证过的流程，不设计没跑过的东西。

### 第一段：亲手做到全覆盖

#### A. 打通实跑

补 WSL entry 脚本，distro 用 `UO_REPLAY_DISTRO=Ubuntu-2204` 覆盖。按顺序实跑：

```powershell
python scripts/_probe_derive.py --refresh
python scripts/replay_smoke.py
python scripts/replay_cover.py --rounds 2 --per-round 200
python scripts/replay_runtime_counterexample_gate.py
python scripts/replay_verdict.py
```

拿到当前分支真实的 `declared / R / U / excluded / U-R`，取代旧机器产物的数字。

**全程把卡点记进 `docs/debug/bringup-log.md`。** 这不是文档任务：它是第二段划分 action 边界的唯一依据，边界必须落在人真的介入过的地方，而不是拍脑袋。

#### B. 修静态缺陷，把自由量降下来

1. 修第 4 节的空前提短路（两处），验收 `unique free_vars 6 → 4`。
2. 给 `lit` 加出处标记（第 3.1 节的兜底），只有源码常量能喂给 UNSAT。
3. 解释掉 `domain_violations: 1`。
4. 剩下的 `invalidS1Array` 区间覆盖（Normal 走整数、Varlen 必须保持 C++ `float32` 语义，不能当实数）与 `coreIdx` next-fit 有序装箱（它是 host 里一个确定的局部计数器，不是调度不确定性），按同样方式逐个处理。

每一步改完都必须跑 runtime gate，任何已有 witness 被新模型排除立即回滚。

#### C. 让静态驱动搜索

实现第 7.2 节的写侧对偶；阈值从 `def_sites[].guards` 配合 `ValueTree.cuts()` 自动提取；删掉 `search.py` 的手写阶梯。验收：`_from_bindings` 对至少 8 个维度返回非空，自动阈值与手写阶梯的 diff 每处都能解释，`R` 不下降。

#### D. 拆 U 分档并逼近零

拆 `U_sound` / `U_reviewed` / `U_empirical`，`excluded_by` 按 grade 过滤，最终只看 `U_sound − R`。gap 会先变大再收敛，那是把虚假的「已证明不可达」恢复成诚实未知。

然后按 obligation 簇逐个啃：能生成的出 witness，能证的出证书，都做不到的诚实留 `candidate_open`，目标压到零。

**每个簇用了什么证据、试了什么、为何成败都要记录**，这是第二段 METHOD.md 的原料。

### 第二段：固化给弱模型

挂在现有 `acp` harness 上，单一权威是 [specs.py](../../pilot/ascendc_pilot/workflows/specs.py) 的 `WORKFLOWS`。

核心取向：**全流程只留一个 subagent 动作，其余全部确定性 CLI**。弱模型只做一件它擅长的事——看着 bundle 给的证据写一份 recipe YAML，由确定性动作机械裁决。这样模型强弱只影响尝试次数，不影响结论正确性；猜错的代价只是浪费一次 replay。

动作序列：

```text
env_probe → derive_fields → export_codemap → blocker_triage
          → compile_knobs → seed_and_search → gap_cluster
          → mine_recipe (SUBAGENT) → apply_recipe
                ├─ gap 仍下降 → 回到 gap_cluster
                └─ gap 收敛   → coverage_gate
```

几个动作的要点：

- `env_probe` 的第一批检查项就是 A 阶段踩到的 distro 名和 entry 脚本缺失，要能自查并给出精确修复指令。
- `blocker_triage` 沿用 `_probe_mint` 那套诊断，按 `guards_cover` 的 reason 把每个 free_var 分成「工具缺陷候选」和「真语义缺口」，**前者不该派给 agent**。
- `mine_recipe` 的输入 bundle 由确定性动作组装：目标簇、最近 witness、差异维、codemap 证据、可控旋钮、合法性 premises、上次失败分类。agent 不自己决定看什么。
- `apply_recipe` 复用 patch_gates 三道闸，加 recipe 专属检查：`must.case` 字段在 `Case` 上真实存在、seed 能 materialize、不违反 gated premise、冒烟至少一条命中、失败样本必须分类。任何一条不过，staging 不 promote。

注册点按序：`WORKFLOWS` 加 `tk-cover`；`ENGINE_REGISTRY` 与 `uo_init.pilot_engines.ENGINES` 加确定性引擎；`OUTPUT_CONTRACT_PATHS` 加契约；`ownership.py` 加 producer/finalizer 拆分；建 `skills/workflows/tk-cover/SKILL.md` 与各 `skills/actions/tk-cover/*/METHOD.md`；`agents/tk-recipe-miner.yaml`；最后：

```powershell
python scripts/compose_runtime.py --repo d:\TEST\AscendC-Pilot
```

验收：用 composer 2.5 从 `acp start tk-cover` 走到 `coverage_gate`，全程不许人工改 canonical 产物。它卡在哪一步，就把那步补 METHOD.md 或降级为确定性。

---

## 9. 给后续留的接口

`export_codemap` 不是为覆盖临时加的，是给终极目标（分析理解修改代码、根据 PR 生成测试）留的地基。

**现状**：完整 `HostIR`（所有写点 + 守卫 + SSA 版本 + 调用点 + 控制节点 + 声明）只活在 `.probe_cache/fag_bundle.pkl` 这个 dev pickle 里，没有持久化查询层。生产 KB 的 `ir/host_ir.yaml` 是**误名**，只含 `HostBranch` 节点。

`HostIR` 已有的在内存查询：`writes_to`、`writes_by_tail`、`calls_to`、`local_writes_in`、`container_events`、`container_writers`、`loop_at`、`legality_premises`、`param_bindings`、`derivation_chain`。

**要做的**：把 HostIR 导出成与现有 KB 同构的持久产物（YAML 权威 + SQLite 索引，复用 [kb_export.py](../../engines/understand-operator/src/uo_init/kb_export.py) 与 [kb_index.py](../../engines/understand-operator/src/uo_init/kb_index.py) 的模式），补上三个查询：

```text
writers_of(symbol)     谁写了这个符号，在什么守卫下
guards_at(file, line)  这一行被什么条件守着
callers_of(function)   谁调了它，参数怎么绑
```

与已有的 [source_window.py](../../engines/understand-operator/src/uo_init/source_window.py) `evidence_window()`（括号匹配、优先整函数）拼成完整证据包。每个节点带 `source_hash` 绑定 C++ 源码版本，过期即失效。

**PR 场景**：[uo_query.py](../../engines/understand-operator/src/uo_init/uo_query.py) 的 `impact_of(file, line_range)` 已经存在。codemap 补齐后，「PR diff → 受影响的 key 维度 → 该跑哪些定向用例」这条链就通了。本次只保证接口存在并被覆盖流程自己消费（dogfood），不实现 PR 侧。

---

## 10. 可行性与风险

### 可行的依据

- `D` 只有 8705，不是 19 维完整笛卡尔积。
- 单个 replay 用例成本微秒级，实测每秒约 1500 个。
- manifest / Case / bridge / gate / derivation / Z3 / patch_gates / harness 全部就位。
- 难点已收敛到 4 个维度、6 个具名自由量，其中至少 2 个已实测确认是工具缺陷。
- 历史上一个 obligation 提取出的 premises 曾把 `R` 从 3477 抬到 4211、gap 从 1692 压到 958，说明杠杆真实存在。

### 不能承诺的

纯动态全命中。搜不到不等于不可达，必须 witness 与证书共同完成。

### 最大风险：假闭合

不是做不到，是**静态模型在某处偷偷缩小了真实路径却仍被当成过近似**。仓库历史上已经出现过：

- ternary 多常量被折成一个常量
- 两个作用域中的同名变量被合并（两个函数各自的 `coreIdx`）
- 不同 tensor accessor 坍缩为同一变量
- 秩与元素数共用一个变量（`GetDimNum() != 4` 和 `GetShapeSize() == 0` 说的是同一个未知量）
- 序列化往返丢 root / guard
- stale implicit default 让 exactness 与表达式不一致

下列做法会让数字变成 19/19 但不可接受：

```text
把 CheckExceedL2Cache() 直接标成一个无约束 bool
agent 说 invalidS1Array 是输入派生就删掉 blocker
把两个 scope 的 invalidS1Array 合并成同一变量
把 float 区间当成无限精度实数
把 coreIdx 当成可以任意选择的输入旋钮
只看 free_vars=0 不跑 runtime differential
```

**每个摘要必须同时给出两级判定**：`exact_concrete`（对具体输入能精确计算）和 `sound_symbolic`（SMT 过近似绝不误杀真实路径）。`CLOSED` 至少要求前者；进入 `U_sound` 排除 key 必须要求后者。

### 次要风险：经验没传下去

第一段我亲手做时可能用了只有强模型能做的判断却没记下来，导致固化后弱模型跑不通。对策是 A 到 D 全程写 bringup-log，凡凭经验做的决定都要显式记成规则或降级成确定性检查。

---

## 11. 执行清单

| # | 任务 | 验收 | 状态（2026-08-03） |
|---|---|---|---|
| 1 | 补 WSL `run_replay.sh`、修正 distro，跑通全链 | 拿到真实 `declared/R/U/excluded/U-R` | **完成** |
| 2 | 修空前提短路 + `lit` 出处标记 + 解释 `domain_violations` | `free_vars 6 → 4`，gate 仍 PASS | **部分**：空前提安全版 + lit 出处 + LEAF_COLLAPSE 降级；`free_vars` 现 6；OutDType 契约裂缝已解释 |
| 3 | 区间覆盖 + next-fit 两类摘要 | `CLOSED` 逼近 19/19 | **部分**：原语已进；next-fit bailout 已接入（7→6）；interval 未接入（HostIR 0 writers for `invalidS1Array`）；CLOSED 14/19 |
| 4 | Binding 写侧对偶 + 自动阈值 | `_from_bindings` ≥8 维，`R` 不下降 | **完成**（named ≥9；generic 拒非布尔 want；gate PASS） |
| 5 | 导出 codemap，补三个查询 | 覆盖流程消费 | **完成**（393 writes / 4160 calls） |
| 6 | 拆 U 分档，按簇啃 gap | `candidate_open = 0` | **部分**：U 分档已拆；rope pair→`excluded_sound=512`，`U_sound−R=4077`；bandIdx 同守卫证伪勿强关；interval/L2 仍缺模型 |
| 7 | 固化 `tk-cover` workflow | 只有一个 subagent 动作 | **完成**（`mine_recipe`；`scripts/run_tk_cover.py --reset` 入口；reset_policy 清 `uo/tk`） |
| 8 | composer 2.5 验收 | 无人工干预走到 `coverage_gate` | **完成（harness）**：reset→passed、gate PASS；**未完成（全量）**：`open_gap_sound=4077`，见 `uo/tk/residual.yaml` |

第二算子验收只迁移 derive + codemap + bridge + recipe schema + runner，**不迁移 FAG 的 `proof_rules.yaml`**。
