# AscendC-Pilot 重构方案 v2：UO / TG / CE 三侧收敛

这份方案的依据是 [TilingKey 全覆盖闭环方法论](../workflows/tilingkey-closure-agent.md) 跑完一遍之后拿到的实测数据。闭环已经在 FlashAttentionScoreGrad arch35 上把 8705 个声明 Key 全部判定完毕（R=4227、E=4536、gap=0），本方案的目标是把那次成功里**真正起作用的部分**变成产品结构，把**没起作用的部分**删掉。

**一句话结论**：当前静态分析产物 90% 的体积从未被使用，而闭环真正依赖的三类查询里有两类 codemap 答不出来；同时闭环的全部实现都躺在 gitignore 的 `.probe_cache/` 里。重构的主线是**把 codemap 从"调用图投影"改成"字段级语义索引"，把 `.probe_cache/vg_*.py` 沉淀成 TG 正式模块**，其余是清理。

---

## 1. 现状诊断（全部有实测数字）

### 1.1 三侧厚度极不对称

| 侧 | 引擎路径 | 状态 |
| --- | --- | --- |
| UO | `engines/understand-operator/src/uo_init/` | 完整：libclang、KB、update、query |
| TG | `engines/testcase-generation/testcase_agent/` | 完整但**缺闭环能力**：有 Z3，无 sklearn，无 replay 主链 |
| CE | `engines/code-engineering/` | **只有一个 README.md**，无 Python 包 |

CE 侧等于不存在。而用户愿景里 CE 是最终价值出口（PR → impact → 自动生成回归用例）。

### 1.2 codemap v1 答不出闭环需要的查询

`host_codemap/v1` 的全部内容是三个键：`writes`(393) / `calls`(4109) / `functions`(388)。拿闭环实际用到的三类查询去检验：

| 查询 | 闭环里的用途 | codemap v1 能答吗 |
| --- | --- | --- |
| Q1 谁写字段 X、在什么 guard 下 | 阶段 6 找引理证明点 | **能**（393 条 writes，82% 带 guard） |
| Q2 Key 维度 X 依赖哪些输入 | 阶段 2 建依赖骨架、算影响锥 | **不能**——没有 `reads` 关系，也没有 `var_roots` |
| Q3 源码实际比较了哪些量 | 阶段 3 构造 sklearn 特征 | **不能**——guard 是原始 C++ 文本，未结构化 |

Q3 的代价是具体的。闭环文档明确写了"这些量应当从源码的比较式里提取，而不是让模型无限猜"，但实测四个关键特征在 codemap 文本里的可见性是：

```text
bn1s1s2     正则可见: True
qkv_bytes   正则可见: False
s1_mod128   正则可见: False
band        正则可见: False
```

659 条含比较运算符的 guard 字符串全部以原始文本形式存放，没有拆成 `(lhs, op, rhs)`。所以特征工程只能靠人读源码手写，这正是当前流程里最难自动化的一环。

### 1.3 codemap 体积用错了地方

| 内容 | 条数 | 评价 |
| --- | --- | --- |
| `calls` | 4109 | 体积主体，但 CBM 的 `CALLS` 边更全更快 |
| `functions` | 388 | 其中 **328 个（84%）没有任何 writes**，纯来自 calls 的噪声 |
| `writes` | 393 | 真正有价值的部分 |

1.0 MB YAML + 1.3 MB SQLite，价值集中在 393 条 writes 上。调用图这件事已经有专门的工具做得更好，不该在这里重复造。

### 1.4 跨函数边界是同一个根因、两处独立证据

审计 13 条引理的 14 个证明点在 `def_sites` 里的命中情况：**精确 3 个、±40 行内 9 个、完全缺失 2 个**。两个缺失点是 `SetSparseParams:1534` 和 `GetDeterSparseTilingKey:790`。

去 codemap 里查同样两个函数：

```text
SetSparseParams            调用点: 1   函数体内记录的 writes: 0
GetDeterSparseTilingKey    调用点: 1   函数体内记录的 writes: 0
```

**静态分析停在调用点，没有进入被调函数体。** 两条完全独立的审计路径（引理证明点覆盖率、codemap writes 分布）指向同一个缺陷。

同一个缺陷还有第三处证据：sklearn 特征重要性显示 `DeterType` 的静态父节点只有 1 个，但树上 `sparse_mode`(0.278)、`band`(0.151)、`atten_mask`(0.030) 都是真实分支变量——这些变量正是在 `SetSparseParams` / `GetDeterSparseTilingKey` 函数体内被读取的。

**三条证据同源，所以这是本次重构的第一优先级修复项。**

### 1.5 符号表达式产物 90% 未被使用

`fag_derive.json` 4.3 MB 的字段占比：

| 字段 | 占比 | 闭环用到了吗 |
| --- | --- | --- |
| `value_expr` | 66.1% | 否 |
| `expanded` | 24.1% | 否 |
| `def_sites` | 3.7% | **是** |
| `var_roots` | 1.9% | **是** |
| `variables` | 1.3% | **是** |
| 其余轻量元数据 | ~3% | 大部分是 |

真正被消费的是 35 KB，占 8.1%。

值得说明的是 `value_expr` 本身的工程质量不差：它已经是带 `$ref`/`defs` 的 DAG，SplitAxis 从 29.2 亿树节点压到 3348 个节点、51 字节一节点。跨 19 个域再做一次全局 CSE 只能多省 16%（972 → 815 个子表达式），不值得动。

**问题不在编码效率，在于这个产物解决的不是闭环遇到的问题。** 闭环找 Key 靠真实 Host oracle + CEGAR，证不可达靠 `def_sites` 指到源码后人工推导——两条路都不消费闭式表达式。`expanded` 更是纯负担：它是 `value_expr` 的文本渲染，可再生，而且 5 个硬域全部被截断在 20000 字符，截断后既不能当公式用也不能当证据引用。

### 1.6 闭环的全部智力在 gitignore 目录里

```text
.probe_cache/    890 文件    643.1 MB    （gitignore，未跟踪）
```

里面包含 `vg_ledger.py`（账本重算）、`vg_direct.py`（模型定向生成，11 倍效率的来源）、`vg_mine.py`/`vg_mine3.py`（引理挖掘）、`vg_why.py`（反例定位）、`vg_verify_rules.py`（反例检验）、`vg_exclude.py`（E_sound 门禁）、`vg_closure.py`（逐 Key 判定）等二十多个脚本。

**这是当前最大的风险敞口。** 100% 覆盖这件事目前不可复现——换一台机器、换一个算子，能力就没了。任何清理动作必须排在沉淀之后。

### 1.7 其余冗余（量化）

| 目标 | 文件数 | 体积 | 处置 |
| --- | ---: | ---: | --- |
| `generated/`（三宿主各 234 文件） | 702 | 1.9 MB | 可由 `compose_runtime` 再生，从 git 移除 |
| `scripts/_probe_*.py` | 84 | 0.5 MB | 探针脚本洪泛，删 |
| `scripts/replay_*.py` | 20 | 0.1 MB | 薄包装，合入 `scripts/replay/` 包 |
| `.ascendc-pilot/` | 10 | 2.3 MB | 运行时产物入库，**含 HMAC key，安全问题** |
| `docs/fag/data/*.csv` | 2 | 2.8 MB | 交付物，移出仓库或走 LFS |
| `docs/fag.zip` | 1 | 0.2 MB | 删 |
| `engines/code-engineering/` | 1 | — | 只有 README，待建真引擎 |
| `templates/` | 1 | — | 空目录，删 |
| 重复文档 | 1 对 | — | `docs/fag/tilingkey-closure-agent.md` 与 `docs/workflows/` 下同名文件 SHA256 相同 |

测试：116 文件 23607 行，其中 **18 个不到 60 行**（`test_scaffold.py` 32 行、`test_ir_summary.py` 27 行、`test_cbm_lookup_cli.py` 29 行、`test_preflight_shadow.py` 22 行等）。

---

## 2. 目标架构

### 2.1 分层与分工边界

```text
┌─────────────────────────────────────────────────────────────┐
│  宿主层   opencode / cursor / codex                          │
│           generated/<host>/  （compose 产出，不入库）         │
└───────────────────────────┬─────────────────────────────────┘
                            │ acp start / next / run-action
┌───────────────────────────▼─────────────────────────────────┐
│  控制面   pilot/ascendc_pilot                                │
│           状态机 · 门禁 · 收据 · 单边原则硬校验                │
└───────────────────────────┬─────────────────────────────────┘
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
     ┌────────────┐  ┌────────────┐  ┌────────────┐
     │     UO     │  │     TG     │  │     CE     │
     │  clang →   │→ │ codemap →  │  │ diff →     │
     │ codemap v2 │  │ 变量 → 回放│  │ impact →   │
     │            │  │ → sklearn  │← │ 调 TG      │
     └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
           └───────── codemap v2 ──────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  导航层   CBM（已注册）/ codegraph                            │
│           符号定位 · 调用图 · 取窗 · token 预算                │
└─────────────────────────────────────────────────────────────┘
```

**边界原则**：语言无关的结构信息（符号、调用、继承、文件树）交给导航层，**codemap 只存 CANN tiling 领域语义**。这是删掉 4109 条 `calls` 的依据。

导航层选型：CBM 已经在 Cursor 注册、已有 6 个索引（fag-arch35-narrow 8349 节点 / 33853 边），继续用它。`codegraph` 的 `codegraph_explore` 单工具 + 输出预算设计（&lt;150 文件时 13k chars / 大仓 24k chars）值得借鉴到 UO 的查询接口上，但不必替换 CBM。

两者都**不能**替代 codemap：它们没有路径条件、没有字段级 dataflow、不理解 TilingKey 语义。分工是「导航层定位取窗 → codemap 给语义 → agent 只消费瘦结果」。

### 2.2 codemap v2 schema

设计原则：**只保留闭环实测消费过的东西，加上实测缺失的东西。**

```yaml
schema: codemap/v2
target:
  operator: flash_attention_score_grad
  arch: arch35
  soc: [DAV_3510]                 # CANN：平台门控分支的枚举
  content_hash: <sha256>          # uo-update 增量基线

# —— 新增：CANN 声明键集，D 的唯一来源 ——
declared_keys:
  header: op_kernel/arch35/..._template_tiling_key.h
  pack:                           # 19 维 → uint64 的打包规格
    - {dim: IsEmptyTensor, bits: 1, shift: 54}
    - {dim: SplitAxis,     bits: 3, shift: 51}
  count: 8705

# —— 核心：按输出字段汇总（原 fag_derive.json 的有用 8.1%）——
fields:
  - name: SplitAxis
    kind: key_dim                 # key_dim | host_state | intermediate
    exactness: overapproximated   # exact | observed | overapproximated
    note: FREE_VARS: invalidS1Array[j], bandIdx
    grade: empirical              # exact_static|observed_exact|empirical|set_valued
    domain: [0, 1, 5]
    writers:                      # 原 def_sites，含一层 callee 展开
      - {file: ..._normal_regbase.cpp, line: 1443, function: GetTilingKey,
         rhs: "fBaseParams.splitAxis", guards: [], via: direct}
      - {file: ..._common_regbase.cpp, line: 1592, function: SetSplitAxis,
         rhs: "...", guards: [...], via: callee_of:DoSplit}
    reads:                        # 新增，支撑 var_roots / 影响锥
      - {var: VAR_ATTR_INPUT_LAYOUT, root: ATTRIBUTE}
      - {var: VAR_TDF_FBASEPARAMS_LAYOUTTYPE, root: TILING_DATA}
    state_deps: [layoutType, deterSparseType]   # 只能靠日志观测的中间状态

# —— 新增：结构化谓词表，TG 特征工程的直接输入 ——
predicates:
  - id: P0412
    file: ..._common_regbase.cpp
    line: 812
    function: GetS1S2TemplateType
    lhs: {expr: "queryType", vars: [VAR_DTYPE_QUERY]}
    op: "=="
    rhs: {expr: "ge::DT_FLOAT", const: true}
    guards_fields: [S1TemplateNum, S2TemplateNum]
    feature_hint: dtype_is_fp32          # → TG 直接生成特征
  - id: P0731
    lhs: {expr: "b * n1 * s1 * s2 * dtypeBytes", vars: [...]}
    op: ">"
    rhs: {expr: "l2Size", platform_gated: true}
    feature_hint: bn1s1s2_bytes          # 这就是 sklearn 里的 bn1s1s2

# —— 新增：平台门控分支，防"漏填导致整条分支不可达" ——
platform_gates:
  - {file: ..., line: ..., condition: "npuArch == NpuArch::DAV_3510",
     gated_fields: [IsEmptyTensor], note: "driver 漏填会屏蔽整条 regbase 路径"}
```

**明确不进 codemap v2 的东西**：`value_expr`、`expanded`（实测 90.2% 未使用）、`calls`（导航层负责）、无 writes 的 function 名单（84% 噪声）。

`rhs` 的 200 字符截断要放宽——实测已有 5 条打满。

### 2.3 三个字段的取舍对照

| 原字段 | v2 归宿 | 依据 |
| --- | --- | --- |
| `var_roots` | → `fields[].reads` | 1.9%，闭环阶段 2 依赖 |
| `def_sites` | → `fields[].writers`（+callee 展开） | 3.7%，14 个证明点命中 12 个 |
| `variables` | → `fields[].reads` 去重 | 1.3% |
| `state_targets` | → `fields[].state_deps` | 0.3%，标出"必须靠日志观测" |
| `status`/`exactness`/`note` | → `fields[].{exactness,note,grade}` | 节点分级的依据 |
| `value_expr` | **删** | 66.1%，零消费 |
| `expanded` | **删** | 24.1%，可再生且被截断 |
| （新）guard 结构化 | → `predicates[]` | 补 Q3 缺口 |
| （新）kernel 声明键 | → `declared_keys` | D 的来源，CANN 特有 |
| （新）平台门控 | → `platform_gates` | 防 npuArch 类事故 |

---

## 3. CANN 特性必须显式建模的六处

这是通用代码图工具无法覆盖、必须由 UO 领域分析承担的部分。每一条都来自闭环踩过的坑。

| CANN 特性 | 为什么通用图做不到 | codemap v2 承载 |
| --- | --- | --- |
| **声明键集来自 kernel 侧模板实例化** | `D` 由 `*_template_tiling_key.h` 的 `if constexpr` 组合决定，host 只决定实际产出。必须双侧解析 | `declared_keys` |
| **TilingKey 是多维打包 uint64** | 19 维按位打包，不解包就无法做维度级归因 | `declared_keys.pack` |
| **npuArch / SocVersion 门控** | 闭环实测：`compileInfo.npuArch` 漏填让整条 regbase 空张量分支不可达，表现为"某取值永不出现"，极易误判为不可达 | `platform_gates` |
| **平台参数进入 tiling 比较式** | L2 大小、核数来自平台 ini，是比较式的右侧常量，随芯片变 | `predicates[].rhs.platform_gated` |
| **中间状态只能靠 OP_LOGD 观测** | `fBaseParams` 是 host 内部状态，不是输入的直接函数；`SplitAxis` 的 `input_closure` 是 `host_state` | `fields[].state_deps` + `log_protocol.yaml` 一等公民 |
| **host so 直调 + CompileInfo 结构体** | driver 形态决定了 oracle 可信度，字段顺序错一位就静默走错分支 | 算子 manifest 的 `replay` 块 |

---

## 4. 三侧改造

### 4.1 UO：收敛为 codemap v2 生产者

**保留**：`clang_walk.py`(1583 行)、`clang_tu.py`、`host_ir.py`、`kernel_ir.py`、`build_context.py`、`branch_inventory.py`。libclang 前端是资产。

**四项改造**：

1. **一层 callee 展开**（第一优先级）。当 `X = f(...)` 且 `f` 在分析范围内时，把 `f` 体内对返回值/出参的赋值点也登记为 `X` 的 writer，标 `via: callee_of:f`。验收标准是 13 条引理的 14 个证明点从 12/14 提到 **14/14**。

2. **产出 `reads` 关系**。walk 时同时收集读取点，按 `var_roots` 的根类别（ATTRIBUTE / INPUT_SHAPE / INPUT_DTYPE / TILING_DATA / SESSION_OPTION / PLATFORM_ARCH / OPTIONAL_INPUT_PRESENCE / INPUT_VALUE）分类。

3. **结构化谓词抽取**。guard 从字符串改成 `(lhs, op, rhs)` 三元组，`lhs` 记录参与的变量集合，识别乘积/取模/位运算模式并给 `feature_hint`。这一步直接决定 TG 能不能自动做特征工程。

4. **符号执行降级为可选**。`value_expr` 那条链改成 `uo-deep-solve` 单独 workflow，默认不跑、不产出。需要 SMT 求解时再开。`expanded` 直接删除。

**uo-update 增量**：现有 `update/{changes,plan,apply,diff,artifacts}.py` 骨架保留，改成按 `content_hash` 做**函数级失效**——只有 diff 命中的函数需要重新 walk，其余 writers/reads/predicates 原样保留。CBM 的 `file_hashes` 表和 codegraph 的 `files.content_hash` 都是这个做法，可直接对齐。

### 4.2 TG：沉淀闭环能力，接上 codemap v2

**第一优先级是沉淀 `.probe_cache/vg_*.py`**，因为那是唯一能跑到 100% 的实现。目标模块划分：

| 新模块 | 来源 | 职责 |
| --- | --- | --- |
| `testcase_agent/oracle/runner.py` | `scripts/replay/runner.py` | Host 回放，含崩溃恢复与 `verdict` 三态 |
| `testcase_agent/ledger.py` | `vg_ledger.py` | 从原始产物重算 R，多来源取并集 |
| `testcase_agent/features.py` | `vg_feat.py` + **codemap `predicates`** | 特征工程，改为由谓词表驱动而非手写 |
| `testcase_agent/models.py` | `vg_fit.py` / `vg_direct.fit_models` | sklearn 决策树，三数报告（基线/静态父节点/全旋钮） |
| `testcase_agent/generate.py` | `vg_direct.pool` | witness 变异 65% + 随机 35% |
| `testcase_agent/residual.py` | `vg_residual.py` | 距离分布 + 阻塞维度 |
| `testcase_agent/mine.py` | `vg_mine.py` / `vg_mine3.py` | 二元/三元引理候选挖掘 |
| `testcase_agent/explain.py` | `vg_why.py` | 反例定位（Host 坚持替换哪一维） |
| `testcase_agent/lemma.py` | `vg_verify_rules.py` / `vg_exclude.py` | 引理检验 + E_sound 硬门禁 |
| `testcase_agent/closure.py` | `vg_closure.py` | 逐 Key 判定报告 |

**新增正式依赖 `scikit-learn`**。当前 `pyproject.toml` 里根本没有它，闭环用的是临时安装。

**接上 codemap v2 的两处**：

- `features.py` 读 `predicates[].feature_hint` 自动生成特征列，替代现在手写的 `f["bn1s1s2"] = f["b"]*f["n1"]*f["s1"]*f["s2"]`。这是把「人读源码找比较式」变成「静态分析导出比较式」。
- `generate.py` 读 `fields[].reads` 算影响锥，只扰动目标维度的祖先输入，减少其他 18 维漂移。

**单边原则做成控制面硬门禁**（`pilot/` 侧）：

```text
I1  R ∩ E = ∅
I2  R 只因真实 witness 增长（driver 的 ###DONE ok=1）
I3  E 只因带 file:line 引用的引理增长
I4  每条引理入库前过全量 witness 反例检验
```

违反任一条，`acp complete` 拒绝通过。这是防"假 100%"的机制化。

### 4.3 CE：从零建引擎

CE 是唯一需要新建的引擎包 `engines/code-engineering/code_engineering/`。三个能力：

**1. PR → impact**。给定 diff，用 codemap v2 反查：

```text
diff 命中的 (file, line) 区间
  → 落在这些行内的 writers / predicates
  → 反查它们的 fields[]
  → 受影响的 Key 维度集合
  → 受影响的声明 Key 子集（按 declared_keys.pack 展开）
```

输出是「这个 PR 可能改变哪些 TilingKey 的产出条件」。

**2. impact → 回归用例**。把受影响维度交给 TG：从 `reachable_cases.csv` 里筛出命中这些维度的既有 witness 作为回归基线，再调 `generate.py` 针对变更后的谓词生成新用例。改前改后各跑一遍，比对 Key 集合差异。

这条链是整个项目的最终价值出口：**PR 进来，自动知道影响面，自动生成对应测试**。

**3. code taste / 修改原则**。从 codemap 提取本仓既有模式（分支写法、guard 风格、命名、平台门控的写法），配合 `skills/policies/` 下已有的 6 份 POLICY.md，给出「本仓库会怎么写这段」的约束。这一项优先级最低，因为它是建议性的，前两项是可验证的。

---

## 5. 清理清单（按依赖顺序）

**顺序是硬约束**：沉淀先于删除。

### 阶段 A：沉淀（不删任何东西）

把 `.probe_cache/vg_*.py` 按 4.2 的表迁进 `testcase_agent/`，每个模块配行为测试。验收：不依赖 `.probe_cache` 就能在 FAG arch35 上重跑出 R=4227 / E=4536 / gap=0。

**这一步没做完，后面一步都不能做。**

### 阶段 B：删除

| 目标 | 体积 | 前置条件 |
| --- | ---: | --- |
| `.probe_cache/` | 643.1 MB | 阶段 A 完成 |
| `generated/` 从 git 移除 | 1.9 MB | 确认 `install.ps1` 会先跑 `compose_runtime` |
| `scripts/_probe_*.py`（84 个） | 0.5 MB | 确认无 workflow 引用 |
| `scripts/replay_*.py`（20 个） | 0.1 MB | 合入 `scripts/replay/` 包后 |
| `.ascendc-pilot/` 从 git 移除 | 2.3 MB | **含 HMAC key，需同时轮换密钥** |
| `docs/fag.zip` | 0.2 MB | — |
| `docs/fag/data/*.csv` 移出 | 2.8 MB | 交付物归档到别处 |
| `templates/` 空目录 | — | — |
| `docs/fag/tilingkey-closure-agent.md` | — | 与 `docs/workflows/` 下同名文件内容相同，留一份 |
| `engines/understand-operator/` 内 `_probe.py`/`_smoke.py`/`_kdiag.py`/`_p2.py` | — | — |
| 各包 `*.egg-info/`、`.pytest_cache/`、`.pytmp/` | — | 加 gitignore |

### 阶段 C：测试瘦身

116 文件 23607 行里，先处理 18 个不到 60 行的：`test_scaffold.py`(32)、`test_ir_summary.py`(27)、`test_cbm_lookup_cli.py`(29)、`test_actions_fast_engine_router.py`(21)、`test_preflight_shadow.py`(22)、`test_obligations.py`(35)、`test_loop_summaries.py`(34)、`test_bridges.py`(39) 等。

判据不是行数，是**这个测试失败时能不能定位到一个真实缺陷**。删掉纯 import / 纯 schema 存在性断言，保留 clang 解析、KB 一致性、key exactness(1606 行)、TG phase1/2、控制面 receipt 这些真行为测试。

同时**补**闭环相关的测试——现在这块覆盖率是 0，因为实现在 `.probe_cache` 里。

### 阶段 D：多平台安装

`generated/` 不入库之后，安装流程改成：

```powershell
pip install -e ./pilot ./engines/understand-operator ./engines/testcase-generation[solver,ml] ./engines/code-engineering
python scripts/compose_runtime.py --repo . --host opencode
./install.ps1 opencode
acp doctor
```

`skills/hosts/{codex,cursor,opencode}.yaml` 三宿主配置已在，`opencode-plugin/ascendc-pilot.ts` 授权钩子已在。要补的是 `acp doctor` 检查导航层 MCP（CBM）是否可用，以及 compose 产物与 skills 源的漂移检测（`.github/` 下已有 compose-drift CI，接上即可）。

---

## 6. 执行顺序与验收

| 阶段 | 内容 | 验收标准 |
| --- | --- | --- |
| **P0** | 沉淀 `vg_*.py` → `testcase_agent/` | 脱离 `.probe_cache` 重跑出 gap=0 |
| **P1** | UO callee 一层展开 | 14 个引理证明点 **14/14** 命中（当前 12/14） |
| **P2** | codemap v2：加 `reads` + `predicates` + `declared_keys` + `platform_gates`，删 `calls`/`functions` | Q1/Q2/Q3 三类查询全部可答；YAML 体积下降 |
| **P3** | TG 特征工程改由 `predicates` 驱动 | 自动生成的特征集覆盖 `bn1s1s2`/`qkv_bytes`/`s1_mod128`/`band` 四个已知关键特征 |
| **P4** | 符号执行降级为 `uo-deep-solve`，删 `expanded` | 默认路径产物体积下降约 90% |
| **P5** | CE 引擎：diff → impact → 调 TG | 给一个真实 PR，输出受影响 Key 维度与回归用例 |
| **P6** | 清理阶段 B + 测试瘦身阶段 C | 仓库瘦身；测试全绿 |
| **P7** | 多平台安装与 doctor | opencode / cursor / codex 三宿主 `acp doctor` 通过 |

P1 和 P2 可以并行。P3 依赖 P2。P5 依赖 P2。P6 依赖 P0。

---

## 7. 两个必须守住的原则

**单边原则**。近似模型（sklearn、统计、拟合）只能用于生成和排序候选，**永远不能用于排除 Key**。排除只能由带 `file:line` 的源码证明给出。这条写进控制面门禁，不靠人记。

**沉淀先于删除**。当前 100% 覆盖能力不可复现，全部实现在 gitignore 目录里。在 P0 完成之前，`.probe_cache/` 一个字节都不能删。
