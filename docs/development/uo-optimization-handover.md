# UO 提取与查询优化 —— 交接（2026-08-26）

对象是 `flash_attention_score_grad` / **arch35**，目标算子目录：

```text
TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10546/attention/flash_attention_score_grad
```

这轮工作的前提是**不兼容旧产物**：遇到冲突直接改 schema、直接删字段，不留 shim。唯一的硬约束是**答案等价** —— 图的形状可以变，但 `uo-query` 对同一个问题给出的答案必须一字不差。所有改动都由 `tools/uo_answer_gate.py` 的 59 例把关。

已完成 Phase 0~3。Phase 4 热点仍在，但 2026-08-27 把交接里列出的 12 个失败测试修完了，并补了几处不改语义的热路径。下面按「怎么复现 → 做了什么 → 还剩什么 → 坑在哪」组织。

---

## 0. 产物孤立度（2026-08-26 续）

`flash_attention_score_grad` / arch35：完全孤立 **1,920 → 73（0.4%）**，锚点可达 **76.1% → 97.4%**。答案门 **59 例 PASS**（`Q19_get_tpl_key` 主命中从错误的 tiling-key 头 `:1460` 改到 host `tiling_normal_regbase.cpp:1460`，已 `--freeze`）。

连边只用 clang 记下的事实，**不用正则扫源码硬连**：

| 问题 | 做法 |
| --- | --- |
| REGISTER 脱图 | 调用点 `args` + 作用域名字查找 → `REFERENCES`；`memory_space=REG` |
| arch22 FUNCTION 污染 | `host_ir_keeps_file` 丢掉 other-arch / `op_kernel/`；dataflow 不再 mint 无 reads 的 getter |
| host BRANCH | `CtrlNode.function` / AST `reads` 接到 FUNCTION 与操作数；对不上的 regex 站点不再单独 mint |
| enum COMPILE_VAR | 声明上的 `attrs['enum']` → TYPE `CONTAINS` |
| platform OPERATION | clang `caller` → `CALLS` |
| PREDICATE / TPL BW / attr INPUT | SELECTS / BINDS / FILE CONTAINS |
| 99 孤立 MACRO | 同文件 `source_define` 去重；空 object-macro（include guard）不进图；`TplSchema` 构造名 `BINDS`；clang `MACRO_INSTANTIATION` `EXPANDS_TO` 已有 MACRO 或 FILE |

剩余 73 个是编译器没使用点的库存（9 个 `GEN_*` MACRO、28 catalog TYPE、21 无调用 FUNCTION…），保持孤立。

增量已接到 `/uo-update`：mtime+size 快筛后再 sha256；`skip_reextract` 只报真正变了的 confirmed source；`detect_kb_changes` 用同一套 stamp delta（git 行在指纹未变时变成 noop）；源码指纹未变时 analyze 复用 compile cache。源码有变时 analyze 仍全量（pass 级依赖未做）。

审计：`python tools/uo_product_audit.py --isolated`。Golden：`tests/baselines/flash_attention_score_grad.arch35.answers.json`。

---

## 1. 先复现当前状态

三条命令。第一条建产物，第二条验答案没变，第三条看每个 pass 花了多久。

```bash
cd engines/understand-operator

# 冷构建（必须抹掉 cache，否则 extract 走缓存，测不到真实耗时）
export UO_OP_DIR=<op>            # 上面那个算子目录的绝对路径
export UO_OPS_ROOT=<pr-10546>    # 算子仓根
export UO_ARCH=arch35
rm -f  "$UO_OP_DIR/.ascendc-pilot/arch35/uo/FlashAttentionScoreGrad.arch35.uo"
rm -rf "$UO_OP_DIR/.ascendc-pilot/arch35/cache"
python tools/run_full_init.py

# 答案等价门槛（59 例）
python tools/uo_answer_gate.py --op "$UO_OP_DIR" --arch arch35

# 逐 pass 真实耗时（不是 profiler 数字）
grep "uo-timing.*compile\." <构建输出>
```

当前基线：

| 指标 | 优化前 | 当前 |
| --- | ---: | ---: |
| `.uo` 产物 | 69.11 MB | **49.92 MB**（-27.8%） |
| `compile.total`（analyze） | 41.54s（**仅 1 次采样**） | 37.51 / 41.52 / 40.75s |
| `compile.host_defuse` | 6.47s | **0.95 / 0.92 / 1.06s** |
| span 可 join 到 source_line | 60% | **100%** |
| `trust=legacy_unknown` 占比 | 33.6% | **0%** |
| around-by-file 查询 | 13.33ms | **0.20ms** |
| 死索引（计划从不选中） | 5 个 | **0 个** |

答案门槛 **PASS，零差异**。单测 **787 passed**（另有 12 个既有失败，见 §5）。

> **`compile.total` 那一行请不要引用为「优化成果」。** 优化前只有一次采样，而这台机器同一份代码三次冷构建能跑出 37.5 / 41.5 / 40.7 —— 4s 的波动。详见 §4.1。

---

## 2. 已完成的工作

### Phase 0 —— 先把尺子造出来

没有可信的度量，后面每一步都是在猜。

- **阶段计时接线**：`record_stage` 接进 prepare/extract/analyze/commit/verify 五个阶段函数（`src/uo_init/codemap_engines.py`、`src/uo_init/perf.py`）。之前有 102s 落在「未归因」里，现在是 1.9s。
- **答案等价门槛**：`tools/uo_answer_gate.py`。golden 落在 `engines/understand-operator/tests/baselines/flash_attention_score_grad.arch35.answers.json`，用 `--freeze` 重新冻结。运行时 dump（current/diff/perf）只写 `artifacts/uo-answer-gate/`（gitignore）。CI 不跑完整 FAG 59 问。
  - 自检过：同一产物连跑 3 次零差异，确定性成立。
  - **这是整轮工作的安全网。任何改动先跑它。**

### Phase 1 —— 接线与显式失败

`source_line` 加速表真正接进构建、`VACUUM` 生效、吞掉的异常改成显式失败、entity span 越界钳制。

### Phase 2 —— 语义正确性

- **信任归因**：`legacy_unknown` 从 33.6% 降到 **0%**，58,765 行全部有分类；「无 provenance」从 875 行降到 0。
  - 顺手修了 `passes/symbol_roles.py` 一个错误分类：`symbol_role_kernel_callee` 标的是 `SOURCE_CLANG_AST`，但它是从「被调用」关系投影出来的派生事实，应该是 `SOURCE_DSL`。
- **BRANCH 命名与索引**：原来 1,308 个 BRANCH 实体不可名、查不到。
- **REGISTER 接进 query**：1,222 个去重后的 VREG/RegTensor 声明（arch35 寄存器压力相关）原本是「信息有用但零消费者」，现在查得到。

### Phase 3 —— 瘦身 69.11 → 49.92 MB

按贡献排序：

| 手段 | 省下 | 位置 |
| --- | ---: | --- |
| 信任四元组写盘剔离 / 读入还原 | 7.5 MB | `ir/evidence.py`、`store/writer.py`、`store/reader.py` |
| 三个大 view blob 改按需投影 | 4.2 MB | `store/view_projection.py`（新） |
| 路径统一口径 | 4.5 MB | `store/writer.py`、`paths.py`、`store/accel.py` |
| 索引裁剪 | 3.4 MB | `store/schema.py`、`store/accel.py` |

四件事各自的关键点：

**信任四元组**（`shrink_evidence_attrs` / `grow_evidence_attrs`）。`build_context_id` 是一个值重复存了 58,765 遍；`trust` 和 `evidence_source` 大多能从 `provenance` 推出来；`semantic_state` 绝大多数是 `resolved`。写盘时剔掉可推导的，读入时还原。**存储层的取舍，不改语义** —— 存的 trust 和 provenance 冲突时保留存的那个，所以人工覆盖仍然活得下来。

**view 投影**。`views/kernel.yaml`、`ir/tg_host_view.yaml`、`views/tilingdata.yaml` 只有 TG 引擎和 `uo-dump` 读，`uo-query` 不读。现在不再内嵌，改成 blob 缺失时从图切片现场投影。TG 走 `view_projection` 这个接口，投影出来的视图带完整的指纹/摘要/计数元数据，和全图一致。

**路径口径**。这是这一阶段最有价值的发现，因为它同时是个**正确性 bug**。原来同一个文件有四种拼法同时存在：算子相对（`op_kernel/x.h`）、ops-root 相对（`<op>/op_kernel/x.h`）、共享目录（`common/x.h`）、绝对路径。`entity.file` 有 41% 是绝对路径。而查询要靠路径把 span join 到 `source_line` —— 两种拼法就是两个文件，只有一个能被引用到，**2,004 个 span 静默匹配不上源码**，`clamp_spans_to_file_length` 里的 basename 兜底把这个问题盖住了。

  现在统一成：以**算子目录**为原点的相对路径；共享代码保留 `../` 前缀（它确实不在算子目录下，不该被硬塞进去）；CANN 工具链头文件用 `<cann>/` 标记（它在任何 checkout 之外，只有读者自己的安装能说它在哪）。实现在 `store/writer.py` 的 `_PathBase`，规则按前缀长度降序匹配 —— 最具体的规则赢，所以 vendored 的 CANN 树不会被当成普通祖先目录。

  同时把散在 7 个 pass 里的重复实现收敛成 `paths.resolve_operator_file`。那 7 份拷贝共享两个缺陷：`lstrip('./')` 是**字符集**而不是前缀，会把 `../common/x.h` 的父目录吃掉、变成解析到另一棵树的路径；而且只试一层父目录。

**索引裁剪**。用 `EXPLAIN QUERY PLAN` 回放整个查询面，找出计划从没选中过的索引，删掉 5 个（`idx_uo_entity_name`、`idx_span_file_line`、`idx_name_leaf_entity`、`idx_legal_key_dim_key`，以及被复合索引包含的 `idx_uo_entity_kind`）。

  过程中发现 `idx_entity_file_line` 也没被用 —— 但它不该被删。根因是 around/impact 查询写成 `IFNULL(e.file,'') = ? OR IFNULL(e.file,'') LIKE '%' || ?`：**对列套 `IFNULL` 等于调了个函数，索引直接失效**。改成两级探测（先 `e.file = ?` 等值，无果再 LIKE 兜底），**13.33ms → 0.20ms，67 倍**。`store/schema.py` 里留了注释说明每个索引对应哪条计划，加回索引前请先确认有计划点名它。

**另外修了一个数据完整性 bug**：`_attrs_json` 漏传 `key` 参数，导致顶层谓词字符串被静默截断到 400 字符。

### Phase 4 —— 提取与分析热点（做了一半）

用 cProfile 打 analyze（工具见 §3），四个热点：

**（一）`normalize_symbol` 被调 2,453,461 次**

它是纯字符串函数，加了 `lru_cache`。但真正的病根在 `passes/host_defuse.py` 的 `_input_by_name`：这个函数**每次调用**都把全部 API 输入的拼写集合重建一遍 —— 6,988 次调用 × N 个输入 × 4 次 normalize，而输入集在一次 trace 期间根本不变。改成在 `_api_maps` 里建一次 `_InputSpellings` 索引（那里本来就是「这次 trace 的 API 表面」包），查找 O(1)。桶按 API 顺序保序，所以解析结果和原来线性扫描找到的第一个是同一个。

- 调用次数 **2,453,461 → 94,663**（-96%）
- `compile.host_defuse` **6.47s → 0.98s**（三次重跑 0.92~1.06，**这个结论可靠**）

**（二）`Path.resolve()` 打了 113,585 次系统调用**

Windows 上每次 `_getfinalpathname` 约 0.04ms，合计 5.05s。一个 stage 运行期间文件不会移动，答案是常量。在 `paths.py` 加共享的记忆化 `resolved()`，替换 6 处热点（`passes/kernel_scan.py`、`source_layout.py` ×4、`passes/source_text_cache.py`、`source_index/builder.py`）。

- 系统调用 **113,585 → 14,012**
- 缓存实测只有 **189 条**，命中率 **99.6%** —— 这 11 万次调用其实只在问 189 个不同路径

**（三）最热的扫描器里 13 处内联正则**

`source_index/builder.py` 里 `re.search(r"...", line)` 这种写法每次都走 `re._compile` 的缓存查表（全局 3M 次、3.2s），而其中几个是**对每个文件的每一行**都跑。全部提到模块级预编译。

另外给 `_strip_line_noise` 加了快速路径：没有引号也没有 `//` 的行，逐字符扫描就是恒等变换。注意 **Copyright 检查必须留在快速路径之前** —— license 行不一定被注释，`tests/unit/test_kernel_lexical_denoise.py` 明确规定裸 `Copyright (c) ...` 行要被清空，我第一版把它放在后面，测试直接抓出来了。

**（四）两处重复计算**

- `diagnostics/audit.py` 的 `_path_exists` 每次调用都从全部关系重建流图邻接表，而它被调 4 次 → 改成 `_flow_adjacency` 建一次传进去。
- `tg_views.py` 的 `_host_symbols_for_key` 为每个 TILING_KEY 扫一遍全部 6.7 万实体，只为挑出 FIELD 和 VARIABLE 两种，而且在循环体里反复重建 `{EntityKind.FIELD.value, ...}` 这个集合 → 改走 `by_kind` 索引，消掉 **768,930 次**枚举属性读。

---

## 3. 工具清单

**仓内**（已提交或待提交）：

| 路径 | 用途 |
| --- | --- |
| `engines/understand-operator/tools/uo_answer_gate.py` | 答案等价门槛，59 例。`--freeze` 重冻 golden。golden 在 `tests/baselines/`。 |
| `engines/understand-operator/tools/run_full_init.py` | 五阶段构建 |
| `engines/understand-operator/tools/uo_init_perf_gate.py` | action 级性能 harness |

**仓外**，在 `d:\PR-review\_tools\`（下一位接手请先搬进 `engines/understand-operator/tools/` 或 `scripts/dev/`，否则换机器就没了）：

| 文件 | 用途 |
| --- | --- |
| `uo_profile_analyze.py` | cProfile 打 analyze 阶段，按 cumtime/tottime 出表，过滤到 uo 自己的栈帧 |
| `uo_index_usage.py` | 回放整个查询面 + `EXPLAIN QUERY PLAN`，报告哪个索引被计划选中、哪个是死的 |
| `uo_index_value.py` | 逐个丢索引跑门槛，量化每个索引的实际价值 |
| `uo_cache_stats.py` | 读新加的三个 memo 缓存的占用/命中率，以及 GC 跟踪对象数 |
| `_timing_table.py` | 多份构建日志的逐 pass 耗时对比表（噪声以列间差异形式可见） |
| `_pcallers.py` | 查某个函数的调用者排名 |
| `uo_span_audit.py` / `uo_trust_audit.py` / `uo_phase2_audit.py` | Phase 2/3 用的产物审计 |

两个用工具时的坑：

- **PowerShell 的 `>` 重定向写的是 UTF-16LE 带 BOM**。用 `encoding="utf-8"` 读构建日志会得到一堆交错的 null，正则**静默匹配不到任何东西**（我在这上面浪费了一轮）。`_timing_table.py` 里有正确的 BOM 嗅探。
- `uo_index_usage.py` 最初漏了 around 用例，于是把 `idx_entity_file_line` 报成死索引。**判定索引死活之前，先确认回放覆盖了会用到它的查询。**

---

## 4. 还没做的（按优先级）

### 4.1 【已关闭】旧的 ~3s 回退不再可比

那张逐 pass 表是对**另一份源码**（golden digest `ddca6b3d` / 48 文件）的单次 before。当前 PR-10546 HEAD 源码指纹是 `3e45163c` / 47 文件，BRANCH 从 ~1.3k 涨到 ~6.7k，analyze 墙钟也从 ~40s 涨到 ~56s（未插 profiler）。旧数字不能当基线。

全量 analyze 必须删掉

```text
$UO_OP_DIR/.ascendc-pilot/$UO_ARCH/uo/ir/_codemap_compile_cache.pkl
```

否则 `analyze` 在指纹未变时 2.7s 就返回，测到的是 compile cache 命中。`tools/uo_perf_bench.py --wipe-compile-cache` 每轮都会删这个文件。

### 4.2 `kernel_root_trace` —— 当前仍是最大头（~27s / analyze）

2026-08-27 两次全量 analyze（`--wipe-compile-cache`，未插 profiler）：`stage:analyze` **51.0 / 45.2s**（均值 48.1，spread 5.8s）。逐 pass 均值：

| pass | s |
| --- | ---: |
| `kernel_root_trace` | 18.1 |
| `source_gaps` | 7.0 |
| `kernel_tiling_closure` | 3.9 |
| `kernel_call_refine` | 3.7 |
| `host_defuse` | 1.1 |

cProfile（会放大）里叶子最大的是 `strip_cpp_comments`（15 次、tottime ~3.7s，已改成按切片拼接，待 `--wipe-compile-cache` 复核）和 `_advance_members`（pending 累积已加 2048 字符上限）。`get_or_build` / `map_files` 仍贵。

### 4.3 `map_files` 进程池 —— 已接线，默认仍是线程

`UO_MAP_BACKEND=process` 走 `ProcessPoolExecutor`；回调不能 pickle 时自动退回线程。`source_index.builder._scan_missing_item` 已提到模块级，是能真正进进程池的那一处。

一次 process 全量（n=1）：`kernel_root_trace` **11.2s**，线程两次是 19.3 / 17.0（spread 2.2）。差值大于线程噪声带，但 process 还没有第二次采样，**先别改默认**。再跑 3 次 process 若仍在 ~11s，再把默认换成 process。

### 4.4 其余已做 / 仍未动

已做：

- `strip_cpp_comments` 按块拷贝，无 `//`/`/*` 直接返回
- `_conditional_field` 不再对整段 pending 做 `.lower()`
- `_advance_members` pending 超 2048 字符放弃（避免二次方正则）
- SQL `template_match` 对已命中块 **钉住过滤维**（`IsRope=1` 的 `dim_coverage.IsRope` 是 `["1"]` 而不是 `["0","1"]`）。golden 已按此重冻（E1 / E7）

未动的大头：`source_gaps`、`kernel_call_refine`、`enrich_kernel_field_branches`、`kernel_root_trace` 本体。

### 4.5 已取消

**Phase 3.4「id 内部化为整数 rowid」**。量化后发现真臃肿是信任四元组（7.36 MB）而不是 id 字符串；改 id 要动 schema、收益不足，不划算。

---

## 5. 单元测试（2026-08-27 已清零）

`python -m pytest tests/unit -q`：**838 passed, 89 skipped, 0 failed**。原先 12 个失败的处理：

| 文件 | 处理 |
| --- | --- |
| `test_closure_roots.py` | 无写点的 params 叶保持 `partial`（与 `test_source_resolver` 一致）；需要闭合的用例补上两条不同常量写 |
| `test_framework_scope.py` | 框架头放到 `op_root` 外面。头和算子同目录时 `_in_scope` 会把它当成算子自己的文件 |
| `test_clang_walk_single_pass.py` | host 也走单次 AST walk，测试跟上代码 |
| `test_tpl_schema_portable_path.py` | 只有 DECL、没有 SEL 时不再生成 TPL view |
| `test_uo_query_aggregate_modes.py` | SQL 路径补上过滤维钉住；0 命中时不往 `dim_coverage` 里塞过滤值 |

语料库：从 [ops-transformer PR 10546](https://gitcode.com/cann/ops-transformer) 的 `refs/merge-requests/10546/head` 稀疏检出 `attention/flash_attention_score_grad`、`attention/common`、`common`，拷回 `TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10546/`。golden 已按这份源码重冻。

---

## 6. 待提交文件

工作树里这几个是新增未跟踪的，别漏掉：

```text
engines/understand-operator/src/uo_init/store/view_projection.py
engines/understand-operator/tools/uo_answer_gate.py
engines/understand-operator/tests/unit/test_path_canonicalization.py
engines/understand-operator/tests/unit/test_view_projection.py
```

门槛的 golden 在 `engines/understand-operator/tests/baselines/flash_attention_score_grad.arch35.answers.json`（59 条答案）。CI 不跑完整 FAG 查询；单测只检查 golden 存在，以及 `compare()` 在 tiny fixture 上的 diff。

有意改变答案时用 `--freeze`，并在提交信息里说清改了哪几例、为什么。

全量 analyze 计时：

```bash
python tools/uo_perf_bench.py --runs 3 --stages analyze --wipe-compile-cache --label after
python tools/uo_profile_analyze.py --wipe-compile-cache --top 40
```

---

## 7. 几条经验，避免重复踩

1. **一次采样不是测量。** 这台机器同一份代码冷构建能差 4s（10%）。任何低于 10% 的改进都必须靠多次重跑 + 逐 pass 对比才能确认。我因为信了单次采样，把一个净效果不明的阶段当成了 -9.7% 的胜利。
2. **profiler 的收益会被放大。** cProfile 下 `compile.total` 从 80.8s 降到 54.3s，但真实只有 41.5 → 39.9。原因是我消掉的主要是**调用次数**，而 profiler 对每次调用额外收费。用 profiler **定位**热点，用 `[uo-timing]` **验证**收益。
3. **profiler 报的「死索引」要先看回放覆盖率。** 见 §3。
4. **对列套函数（`IFNULL(col,'')`）索引就失效了。** 这一处让 around 查询慢了 67 倍。
5. **`lstrip('./')` 是字符集不是前缀。** 它会吃掉 `../` 的父目录，把兄弟目录的路径变成解析到自己目录下。仓里曾有 7 份拷贝都带这个 bug。
6. **PowerShell 重定向写 UTF-16LE。** 用 utf-8 读日志会静默匹配不到东西。
7. **加缓存前先看缓存会有多大。** `paths._resolved` 实测只有 189 条却挡住 11 万次系统调用；如果当初盲目按「几万条」去设计容量，反而会引入内存/GC 疑虑（我确实为此白查了一轮）。
8. **指纹未变时 analyze 会复用 `_codemap_compile_cache.pkl`。** `uo_perf_bench.py` 默认测的是这个快捷路径（~3s），不是 50s+ 的 compile。要比全量必须 `--wipe-compile-cache`。

---

相关文档：[UO 模块](../modules/uo.md)、[当前版本 benchmark](../benchmark.md)、[测试与评估](testing.md)、[扩展指南](extending.md)。
