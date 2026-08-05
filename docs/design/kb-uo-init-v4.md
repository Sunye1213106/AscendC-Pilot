# 知识库与 uo-init 重新设计（v4）：三段式 UO、三域同构 KB

目标形态是一句话：

> **UO = 确定范围 → 静态脚本全量扫描 → 模型对静态输出做总结。**
> 静态解不开的东西**原样报出**，不让模型去补；补洞是 `tg-solve` 闭环用真实 witness 和源码引理做的事。

KB 要同时承载 **TilingKey / TilingData / Kernel** 三个域，且三域**同构**——因为后面 TilingData 和 Kernel 的测试闭合要复用 TilingKey 已经跑通的那套 `D = (R∩D) ∪ E` 账本机制（见 [TilingKey 闭环方法论](tilingkey-closure-agent.md)）。同构不是审美要求，是复用的前提。

---

## 1. 现状对比

### 1.1 现在的 uo-init 是 17 步

| # | action | 归类 | 实际做的事 |
| --- | --- | --- | --- |
| 1 | `prepare_layout` | 范围 | 建目录、`rmtree` 掉 `ir/` `indexes/` |
| 2 | `scope_scan` | 范围 | 列 host/kernel 候选、跑 libclang 探针 |
| 3 | `scope_confirm` | 范围 | 无歧义则自动确认 |
| 4 | `extract_host` | 静态 | **一次 clang 建整个 bundle**（`with_closure=True`）：HostIR、分支可控性、gap、binding、var_model |
| 5 | `extract_tiling_key` | 静态 | 只是把 `bundle.binding` 的条数写成 receipt |
| 6 | `extract_registry` | 静态 | 解析 IsCapable 竞价序 |
| 7 | `extract_kernel` | 静态 | harness 实例化 + `-ast-dump` 折叠 `if constexpr` → `KBR_*` |
| 8 | `normalize_variables` | 静态 | **纯占位**，真正变量层在 `export_kb` |
| 9 | `derive_key_fields` | 静态 | 每个 KEY 维回溯到 input 根 |
| 10 | `normalize_predicates` | 静态 | 合并谓词 gap 与派生 gap → blockers |
| 11 | `resolve_gaps` | **模型补洞** | 有派生 blocker 或 ≥20 时拉 LLM 写封闭词汇 patch |
| 12 | `apply_gap_patch` | 静态 | 校验并应用 LLM 的 patch |
| 13 | `export_kb` | 导出 | 写 28 个 YAML |
| 14 | `build_index` | 导出 | 建 sqlite |
| 15 | `export_tg_host_view` | 导出 | HostIR 写点/谓词投影 |
| 16 | `export_integrity` | 导出 | 一致性校验 |
| 17 | `kb_review` | 模型审查 | closure≥0.95 且 blockers<20 则自动跳过 |

### 1.2 三个结构性问题

**问题一：假分步。** 第 4 步已经把活全干完了。`extract_tiling_key` 是读 `bundle.binding` 数条数，`normalize_variables` 是空函数。7 个"抽取" action 里只有 4、6、7、9、10 真的在算，而 4 和 9/10 共用同一个 bundle。分成 7 步既没有独立失败语义，也没给出独立的可审计产物——只是多了 5 张 receipt。

**问题二：模型在默认路径上补洞。** `resolve_gaps` 在 blocker 数超阈值时**自动**拉 LLM 给静态解不出的 binding 写分类。问题不是"模型不能提议"，而是"流水线不该偷偷替你信任它"：模型的产出成了下游 `input_derivable` 的输入，一旦分错，错误会沿 `derive → plan → solve` 一路传下去，而没有任何真实运行来纠正它。目标形态里默认路径上的模型只做**总结**——读静态输出，写人能看的理解和结构化的未解问题清单；提议 binding 这件事退为需要人显式开启、且产出必须带等级标记（见 4.3）。

**问题三：9 个空壳文件在骗门禁。** `kb_schema.yaml` 把 `kernel/paths.yaml`、`kernel/branches.yaml` 列为 `required`，实际内容是 `not_extracted`：

```text
tiling/data_model.yaml       57B   not_extracted   ← TilingData，用户要的
kernel/paths.yaml            53B   not_extracted
kernel/pipeline.yaml         57B   not_extracted
kernel/resources.yaml        57B   not_extracted
kernel/branches.yaml         69B   （空 branches 列表）
kernel/compile_model.yaml    53B   not_extracted
kernel/variables.yaml        66B   镜像
flow/golden_model.yaml       57B   not_extracted
flow/numerical_model.yaml    57B   not_extracted
```

一个写着 `not_extracted` 的 required 文件比没有这个文件更糟：完整性门禁看到文件存在就放行，于是"KB 完整"是假的。

### 1.3 kernel 和 TilingData 现在到哪一步

这里有个关键发现：**能力大部分已经写好了，只是没接线。**

| 能力 | 实现位置 | 状态 |
| --- | --- | --- |
| kernel `if constexpr` → KEY 维索引 | `kernel_ir.py:build_kernel_ir` | **已实现，产物不落盘**。`extract_host_bundle` 返回 `kernel_ir`，但 `assemble_kb` 不读它 |
| kernel 分支按 dtype variant 区分 | `kernel_ir.py:174` 每个 variant 解析一次 | 已实现，同上未落盘 |
| 维度→分支映射 / 哑维报告 | `KernelIR.by_dimension` / `silent_dimensions` / `unmapped_symbols` | 已实现，同上未落盘 |
| kernel 折叠后分支 KBR | `harness.collect_folded_kernel_branches` | 已落盘（`kernel/fold_receipt.yaml`） |
| TilingData 字段清单 | 无 | **缺**。`TilingDataField`(TDF) 在 schema 里定义了，代码里 `add_node(kind="TilingDataField")` 出现 0 次 |
| TilingData 头文件定位 | `op_spec._tiling_data_header` | 已实现 |
| host 写点（含字段路径） | `host_ir.build_host_ir` 的 `WriteEvent` | **已实现**，`tg_host_view.yaml` 的 `fields[].writers` 就是它 |
| `TILING_DATA_NO_WRITER` gap 语义 | `quality.yaml` reason_histogram | 已有 |

也就是说 kernel 域**只差一个导出**；TilingData 域差的是"字段清单"这一侧——写点侧早就有了，缺的是把写点 join 到结构体字段上。

而字段清单是易解析的。两种源码形态都规整：

```cpp
// arch22：op_host，宏定义
BEGIN_TILING_DATA_DEF(PreParams)
TILING_DATA_FIELD_DEF(uint64_t, maskPreBlockTotal);
TILING_DATA_FIELD_DEF(uint32_t, qPreBlockFactor);
END_TILING_DATA_DEF;
REGISTER_TILING_DATA_CLASS(PreParamsOp, PreParams)
```

```cpp
// arch35 regbase：op_kernel，普通 class + get_/set_ 访问器
class FlashAttentionScoreGradS1S2BNGS1S2BaseParamsRegbase {
public:
    int64_t coreNum;
    int64_t b;
    ...
};
```

libclang 已经在跑了，`RecordDecl` 的字段就是答案；宏形态可以直接文本解析，也可以让 clang 展开后取字段。**不需要新的基础设施。**

---

## 2. 三域同构：闭合契约

这是整个设计的地基。TilingKey 闭合已经跑通并有 `gap=0` certificate，机制是账本 `(D, R, E)`：

```text
D = 声明集合        R = 真实运行观测到的     E = 有源码证明排除的
判定完毕 ⟺ D = (R∩D) ∪ E   且   R ∩ E = ∅
```

要让 TilingData 和 Kernel 复用 `testcase_agent/closure/` 的 ledger / rule_engine / lemma，三个域必须给出**同一个形状**的三元组。定义如下：

| 域 | D（声明） | R（witness） | E（证明排除） | 缺陷信号 |
| --- | --- | --- | --- | --- |
| **tilingkey** | TPL header 展开的合法 key 全集 | replay 里 Host 真的返回过该 key | 源码引理证明无输入可达 | `undeclared`：运行时出现 D 外的 key |
| **tilingdata** | (字段, writer 写点) 对 —— 即"这个字段声明了会被这条路径写" | 该 writer 真的执行过，且字段落到某等价类 | 该写点被守卫谓词排除 | **`no_writer`：kernel 读了但无任何 writer**（未初始化读）<br>**`no_reader`：有 writer 无 kernel 读点**（dead field） |
| **kernel** | (KBR 分支, dtype variant) 对 | 存在合法 key 使该 `if constexpr` 为真且被编译进来 | 该条件与全部合法 key 矛盾 | `silent_dimension`：某 KEY 维没有任何分支引用（要么真无用，要么内层模板改了名——工具缺陷） |

三点值得强调：

1. **kernel 域的 D 可以从 tilingkey 域推导**。`kernel_ir` 给出 `branch.dimensions`（条件里点名的 KEY 维），declared_keys 给出这些维的取值组合，所以"哪些分支可达"是 key 可达性的下游结论——不需要另起一套求解器，直接复用 Z3 与已证引理。这是把 kernel 闭合做成 tilingkey 闭合的**投影**而非新问题。
2. **TilingData 域的缺陷比覆盖更值钱**。`no_writer` 直接是真实 bug（kernel 读未初始化字段），`no_reader` 是死代码。这两个静态就能判，不需要跑；跑起来只是为了给"字段值域覆盖"补 witness。
3. **三域共享同一个 `undeclared` 语义**：运行时出现声明集合之外的东西，说明**声明集合本身抽错了**，这是 UO 的 bug 而不是覆盖率问题，必须单独计数、绝不能算进 R。这条在 TilingKey 侧已经有测试守着（`test_counters_split_undeclared_from_declared_r`）。

---

## 3. 新知识库设计

### 3.1 三层结构

```text
uo/
├── manifest.yaml                  op / arch / scope 指纹 / graph_fingerprint / schema 版本
│
├── ir/                            【权威层】唯一真源，只有静态脚本能写
│   ├── operator_graph.yaml        nodes + edges + evidence，authority: yaml
│   └── scan_report.yaml           这次扫描的自述：读了哪些文件、每域抽出多少、哪里没解开
│
├── views/                         【投影层】可丢弃派生，每个文件头带 graph_fingerprint
│   ├── interface.yaml             Input / OptionalInput / Output / Attribute
│   ├── tilingkey.yaml             D 全集 + 每维 roots/exactness + 谓词 + 写点
│   ├── tilingdata.yaml            字段 → writers → kernel readers → 类型/默认值/值域
│   └── kernel.yaml                KBR 分支 → dimensions/derived/variants/源码位置
│
├── indexes/kb_graph.sqlite        【投影层】唯一 SQLite，meta 表存 graph_fingerprint
│
├── digest/                        【总结层】模型写，永不进权威层
│   ├── operator.md                人读的算子理解
│   ├── open_questions.yaml        静态没解开的洞，结构化、封闭词汇
│   └── review.yaml                裁判裁决
│
└── checks/integrity.yaml          指纹一致 / 声明集合一致 / 引用可解析
```

**权威 / 投影 / 总结**三层各有一条铁律：

- **权威层只由确定性脚本写。** 输入是源码，输出可复现。同一份源码跑两次，`graph_fingerprint` 必须一样。
- **投影层必须能被删掉重建。** 每个 view 文件头写 `graph_fingerprint`，与 `manifest.yaml` 不符就是脏的，`integrity` 直接拒。这条解决了 v3 里 P0-1 那个"codemap 与 KB 两套平行权威"的问题——codemap 不再是 authority，它就是 `views/tilingkey.yaml`。
- **总结层进不去权威层。** 没有任何代码路径把 `digest/` 读回 `ir/`。模型说错了话，最坏后果是人读到一段不准的描述，不会污染求解。

### 3.2 相对当前 KB 的增删

| 动作 | 文件 | 理由 |
| --- | --- | --- |
| 删 | `flow/golden_model.yaml`、`flow/numerical_model.yaml` | `not_extracted` 空壳。真要抽的时候再加 |
| 删 | `kernel/pipeline.yaml`、`kernel/resources.yaml`、`kernel/paths.yaml` | 同上。`KernelPath` 概念保留在 schema，等真的做路径遍历再落盘 |
| 删 | `cross_layer/impact_graph.yaml` | 112KB，内容就是图里全部边的转储。图本身有边，sqlite 索引它 |
| 删 | `cross_layer/tiling_to_kernel.yaml`、`variable_lineage.yaml` | 同为边的子集视图，合并进 `views/kernel.yaml` 与 sqlite |
| 合并 | `operator.yaml` → `views/interface.yaml` | 归位到投影层 |
| 合并 | `ir/tg_host_view.yaml` + `tiling/key_space.yaml` + `key_derivations.yaml` + `input_derivable.yaml` + `constraints.yaml` + `coverage_model.yaml` + `key_reachability.yaml` → `views/tilingkey.yaml` | 七个文件描述同一个域的同一件事：D 是什么、每维怎么来、什么谓词管着它。拆七份的唯一后果是七份可能不一致 |
| 合并 | `exhaustive_key_space.yaml` + `legal_key_index.jsonl` → `views/tilingkey.yaml` + 保留 jsonl | 大表继续走 jsonl 分片（8705 行不该塞 YAML），但索引指针归一 |
| **新建** | `views/tilingdata.yaml` | 用户要的 TilingData 域 |
| **新建** | `views/kernel.yaml` | 用户要的 kernel 域；数据源 `kernel_ir` 已存在 |
| 新建 | `ir/scan_report.yaml` | 一次静态扫描的完整自述，替代 5 张分散 receipt |
| 改名 | `ir/unresolved.yaml` → `digest/open_questions.yaml` | 洞的清单本来就是"静态没解开的问题"，交给模型总结、交给 tg-solve 闭合 |
| 保留 | `quality.yaml` → 并入 `ir/scan_report.yaml` | closure / blocker 计数是扫描自述的一部分 |

28 个文件 → 11 个（含 sqlite 与 jsonl），且**没有一个是空壳**。

### 3.3 `views/tilingdata.yaml` 形态

```yaml
schema: uo-view-tilingdata/v1
graph_fingerprint: "a1b2c3..."           # 与 manifest 不符即为脏
structs:
  - name: FlashAttentionScoreGradS1S2BNGS1S2BaseParamsRegbase
    form: regbase_class                  # regbase_class | macro_def
    source: {file: "op_kernel/arch35/..._tiling_data_regbase.h", line: 86}
    fields:
      - name: s1
        type: int64_t
        default: null                    # 声明处有初始化则记下（如 isRope = 0）
        # ——— 写点侧：来自 HostIR WriteEvent，今天已有 ———
        writers:
          - {id: "HBR_7f3a...", file: "op_host/arch35/..._tiling.cpp", line: 412,
             guard: "PID_9c1e...", expr: "shapeInfo.s1"}
        # ——— 读点侧：kernel 侧 get_s1() / tilingData->s1 引用 ———
        readers:
          - {file: "op_kernel/arch35/..._kernel.h", line: 233, form: "accessor"}
        # ——— 闭合三元组所需 ———
        closure:
          declared: 1                    # |D| = writer 数
          status: open                    # open | covered | excluded
          defect: null                    # no_writer | no_reader | null
defects:
  no_writer: []                          # kernel 读了但 host 没写 —— 真 bug
  no_reader: ["reserved", "rsv1"]        # 死字段
```

`writers[].guard` 指向 `Predicate` 节点，这一条让 TilingData 域直接接上 tilingkey 域的谓词求解：**"这个字段在什么 key 下会被写"是已经能解的问题。**

### 3.4 `views/kernel.yaml` 形态

直接是 `KernelIR.to_dict()` 的落盘，加上闭合三元组：

```yaml
schema: uo-view-kernel/v1
graph_fingerprint: "a1b2c3..."
variants: [FLOAT16, BFLOAT16, FLOAT]     # dtype 宏是预处理值，每个 variant 编译不同代码
branches:
  - id: KBR_4d2f...
    condition: "IsSameType<T, float>::value && SplitAxis == 2"
    source: {file: "op_kernel/arch35/..._s1s2_bn2.h", line: 1204, function: "Process"}
    dimensions: [SplitAxis]              # 条件里点名的 KEY 维
    derived: [OutDType]                  # 由某维算出的 constexpr bool
    symbols: [T]                         # 没落到任何维的标识符
    variants: [FLOAT]                    # 哪些 dtype variant 会编译这段
    closure:
      status: open                       # open | covered | excluded
      witness_keys: []                   # 覆盖它的合法 key（R）
      excluded_by: null                  # 排除引理（E）
silent_dimensions: [DeterType]           # 无任何分支引用 —— 报出，不猜
unmapped_symbols:                        # 改过名的维在这里现形
  - {symbol: DETER_SPARSE_TYPE, count: 7}
```

`silent_dimensions` 和 `unmapped_symbols` 这两项是 `kernel_ir.py` 已经写好的诊断，落盘之后就是 kernel 闭合的"工具缺陷"通道：一个维明明在 header 里声明了却在 kernel 里找不到分支，要么它真的不选代码，要么内层模板把 `DeterType` 改名成了 `DETER_SPARSE_TYPE`。**报出来，不做名字相似度匹配**——把分支挂到错的维上比缺一条更糟。

---

## 4. 新 uo-init 流程：9 步、三段

```text
phase scope   ── 确定范围（2 步，1 次人确认）
phase scan    ── 静态脚本全量扫描（5 步，全确定性）
phase digest  ── 模型总结（2 步，producer + referee）
```

| # | action | phase | mode | 产出 | 说明 |
| --- | --- | --- | --- | --- | --- |
| 1 | `scope_scan` | scope | `deterministic` | `runs/{id}/scope/candidates.yaml` | 建骨架 + 列 host/kernel/tilingdata 候选 + libclang 探针。吸收原 `prepare_layout` |
| 2 | `scope_confirm` | scope | `primary_interactive` | `manifest.yaml`（scope 指纹） | 无歧义且探针干净则自动确认；否则人拍。**这是全流程唯一需要人的地方** |
| 3 | `static_scan` | scan | `deterministic` | `ir/scan_report.yaml` + bundle 缓存 | **一次 clang 出全部四域**：HostIR 写点/谓词、TilingKey binding、TilingData 结构体字段、Kernel `if constexpr`（`kernel_ir`）、registry 竞价。吸收原 4/5/6/7/8 五步 |
| 4 | `derive_fields` | scan | `deterministic` | 追加进 bundle | 每个 KEY 维回溯到 input 根 + 谓词归一 + 字段写点 join 到 TDF。吸收原 9/10 |
| 5 | `build_graph` | scan | `deterministic` | `ir/operator_graph.yaml` + `indexes/kb_graph.sqlite` | 组装权威图并建索引，同一步保证两者指纹一致。吸收原 13/14 |
| 6 | `build_views` | scan | `deterministic` | `views/*.yaml` + `legal_key_index.jsonl` | 四个投影**全部从 `operator_graph.yaml` 读**，不从 bundle 读——这是投影层可重建的唯一保证 |
| 7 | `scan_integrity` | scan | `deterministic` | `checks/integrity.yaml` | 指纹一致 / 三域声明集合非空且自洽 / 全部 evidence 引用可解析 |
| 8 | `operator_digest` | digest | `subagent(producer)` | `digest/operator.md` + `digest/open_questions.yaml` | 模型读 `scan_report` + 四个 view，写人读的理解和结构化未解问题。**只许引用 view 里存在的 id** |
| 9 | `digest_review` | digest | `subagent(referee)` | `digest/review.yaml` | 裁判查总结有没有夹带未经证明的结论、有没有编造 id |
| — | `resolve_gaps` | digest | `subagent(producer)`，**默认关闭** | `ir/gap_bindings.yaml` | 见 4.3。不在默认路径上，只在人显式开启时执行 |

### 4.1 相对现状被删掉的东西

| 删除 | 原因 |
| --- | --- |
| `prepare_layout` | 合入 `scope_scan`。顺带修掉 v3 记录的那个坑：它 `rmtree` 掉 `ir/` 导致 codemap 导出偷偷复用旧 probe 产物 |
| `extract_tiling_key`、`extract_registry`、`extract_kernel`、`normalize_variables` | 合入 `static_scan`。本来就是同一次 clang 的产物；`normalize_variables` 是空函数 |
| `export_tg_host_view` | 合入 `build_views`，成为 `views/tilingkey.yaml` 的一部分 |
| `kb_review` | 改为 `digest_review`：审的不再是"KB 产物质量"（那是 `scan_integrity` 的确定性工作），而是"模型的总结有没有越界" |

`resolve_gaps` / `apply_gap_patch` **不删，但从默认路径上摘下来**，见 4.3。

### 4.2 模型只做两件事

`operator_digest` 的产出契约（写进 prompt，由 `digest_review` 执法）：

- **允许**：用自然语言解释这个算子在做什么、哪几个 KEY 维是主要分水岭、哪些字段/分支看起来是同一族；把 `open_questions` 按"缺什么证据才能解开"分类。
- **禁止**：断言任何一条"某 key 不可达 / 某分支不可能进 / 某字段不需要写"。这类结论只能来自 Z3 求解或源码引理，走 `tg-solve` 的 E 通道，需要 referee 单独验。
- **可校验性**：`digest` 里出现的每个 `KBR_*` / `TDF_*` / `KEY` 名字必须在 view 里能查到，否则 review 直接判 fail。这让"模型有没有编"变成一个确定性检查，而不是又一次语义判断。

这正是运动员/裁判分离在 UO 侧的落点：**producer 写总结、referee 查越界，两边都不碰权威图。**

### 4.3 `resolve_gaps` 降级为默认关闭的可选步骤

`resolve_gaps` / `apply_gap_patch` 保留，但**不在默认路径上**。原因是它有一个真实用途：有些洞纯粹是命名问题（内层模板把 `DeterType` 改名成 `DETER_SPARSE_TYPE`），静态匹配不敢猜，人也懒得一个个填，此时让模型在封闭词汇里提议映射确实省事。但它的产出会喂给下游 `input_derivable`，分错就会沿 derive → plan → solve 一路传下去而无人纠正——所以它必须是**人明确要求才发生的事**，不能是流水线偷偷替你做的决定。

降级规则：

| 项 | 现在 | v4 |
| --- | --- | --- |
| 触发条件 | `derivation_blocker_count>0` 或 `blocker_count≥20`，**自动触发** | 只在 `UO_RESOLVE_GAPS=1`（或 `acp run-action resolve_gaps` 显式调用）时执行 |
| 默认行为 | 拉 LLM 写 patch | 跳过；洞照常进 `digest/open_questions.yaml` |
| 产出定位 | 写 `ir/gap_bindings.yaml`，被视为权威 | 仍写 `ir/gap_bindings.yaml`，但**每条带 `grade: llm_proposed`** |
| 下游信任 | 无区分 | 消费侧必须能区分 `llm_proposed` 与 `static_derived`；`tg-solve` 的 E 通道**不接受** `llm_proposed`（对齐 `rule_engine.SOUND_GRADES` 只认 `solver_derived` / `source_lemma`） |
| 门禁 | `gate_gap_patch_evidence` 要求 patch 齐备 | 改为：**若开启过就必须有 referee 裁决**；未开启则该门禁 N/A，不得因此判红 |

`grade` 这一列是关键。今天 `closure/lemma.py:103` 用的是 `excluded_by(inst)` 而不是 `excluded_by_sound(inst)`，导致 human/llm 等级的规则可以直接进 E——`SOUND_GRADES` 在整个 closure 包里调用次数是 0。既然要保留 LLM 提议这条路，就必须同时把这个洞补上，否则"可选"等于"默认信任"。

---

## 5. 下游闭合怎么接上

三个域同构之后，`testcase_agent/closure/` 的机制按域参数化复用：

| closure 模块 | tilingkey | tilingdata | kernel |
| --- | --- | --- | --- |
| `ledger.py`（D/R/E 账本） | 已用 | 换 D 的来源为 `views/tilingdata.yaml` | 换为 `views/kernel.yaml` |
| `rule_engine.py`（引理 + `SOUND_GRADES`） | 已用 | 排除规则 = 守卫谓词不可满足 | 排除规则 = constexpr 条件与全部合法 key 矛盾 |
| `generate.py`（定向生成） | 已用 | 目标：让某写点执行 | 目标：让某分支编译进来 |
| `explain.py`（反例解释） | 已用 | Host 为什么没写这个字段 | 为什么这个 key 没进这个分支 |

其中 **kernel 域几乎不需要新求解器**：分支可达性 = 其 `dimensions` 上的取值组合是否落在已判定可达的 key 集合里，是一次集合运算加已有引理。**TilingData 域的两个缺陷通道（`no_writer` / `no_reader`）静态就闭**，不需要跑硬件。真正需要 witness 的只有"字段值域覆盖"。

优先级建议：`kernel` 域先做（数据已在内存里，只差导出 + 一次集合运算），`tilingdata` 域的缺陷检测紧随（静态可闭，且直接产出真 bug），字段值域覆盖最后做（要 replay 时 dump tiling data）。

---

## 6. 迁移成本（诚实清单）

这个改动不小，破坏面必须先说清楚：

| 破坏点 | 规模 | 处理 |
| --- | --- | --- |
| `ir/input_derivable.yaml` 被 TG 侧读取 | **19 个模块**（`contract.py`、`planner.py`、`solve.py`、`semantic_bind.py`、`shape_derivation.py`、`realization_map.py`、`field_provenance.py` 等） | 分两步：先让 `build_views` 同时输出 `views/tilingkey.yaml` **和**兼容的 `ir/input_derivable.yaml`；TG 模块逐个迁到 view 后再撤兼容层。不要一次切 |
| 依赖 `resolve_gaps` / `gap_patch` 的门禁 | `gate_input_derivable_closed`、`gate_gap_patch_evidence`、`gates/__init__.py` 里 `input_derivable_patch` 相关约 8 处 | `gate_gap_patch_evidence` 改为条件门禁（未开启 `resolve_gaps` 时 N/A）；`gate_input_derivable_closed` 改判据——不再要求"洞已闭"，改为要求"洞已被结构化登记进 `open_questions.yaml`" |
| `closure` 包信任 `llm_proposed` | `lemma.py:103` 与 `report.py:42` 用 `excluded_by` 而非 `excluded_by_sound`；`SOUND_GRADES` 调用次数为 0 | 切到 `excluded_by_sound`，并给 `gap_bindings` 打 `grade`。这是保留 LLM 提议路径的前提条件 |
| `kb_schema.yaml` 的 required 清单 | 9 个空壳文件从 required 移除 | 同步改 schema，否则完整性门禁会因文件缺失而红 |
| `ownership.py` 的 `ACTION_WRITE_PATHS["uo-init"]` | 17 项 → 9 项 | 随 action 表一起改 |
| `uo-init` SKILL / prompts / compose | 三宿主（opencode / cursor / codex）需重新 compose 并验证 | `scripts/compose_runtime.py` + `acp doctor` 已能验，跟着跑一遍 |
| 已落地的旧 KB | `TEST/.../flash_attention_score/.ascendc-pilot/uo/` 是旧布局 | 不做原地迁移。重跑 `uo-init` 即可，扫描是确定性的 |

---

## 7. 建议的落地顺序

1. **`views/kernel.yaml` 先落盘。** 改动最小（`kernel_ir` 结果接进 `assemble_kb` + 导出），立刻验证"三域同构"这个设计是否成立，且不动任何现有 consumer。
2. **TilingData 字段解析 + TDF 节点 + `writes` 边。** 写点侧已有，只补字段清单侧，产出 `no_writer` / `no_reader` 缺陷报告。这一步就能抓真 bug，是最好的价值证明。
3. **删 9 个空壳 + 改 `kb_schema.yaml`。** 让"KB 完整"不再是假的。
4. **合并 action：17 → 9。** 此时才动流程，前三步已经证明了新布局能产出东西。
5. **`resolve_gaps` 降级为默认关闭 + `grade` 分级 + `excluded_by_sound` 切换 + 改门禁判据。**
6. **`views/tilingkey.yaml` 归一 + TG 侧 19 个模块分批迁移。** 最后做，因为破坏面最大。
7. **重写 uo-init SKILL 叙事为三段式，三宿主 compose 验证。**

---

## 附：一句话对照

| | 现在 | v4 |
| --- | --- | --- |
| action 数 | 17 | 9（+1 个默认关闭的可选步） |
| 需要人的地方 | 1（scope_confirm） | 1（scope_confirm） |
| 模型介入 | 2 处，其中 1 处**自动补洞** | 默认 2 处、**都只做总结/审查**；补洞退为需人显式开启且产出打 `llm_proposed` |
| KB 文件数 | 28，其中 9 个空壳 | 11，**无空壳** |
| 覆盖的域 | tilingkey（tilingdata / kernel 是 `not_extracted`） | tilingkey + tilingdata + kernel，**三域同构** |
| 权威边界 | KB 图与 codemap 两套平行 authority | 单一权威图，投影带指纹可重建，总结层隔离 |
