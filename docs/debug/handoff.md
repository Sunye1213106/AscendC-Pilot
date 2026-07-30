# KeyField 派生修复 — 交接

> **调试产物，不是工作流契约 / 验收依据。**  
> 引擎实现：`engines/understand-operator/src/uo_init/derive_key_fields.py`（及相关模块见下文）。  
> Plan：`workflow_closure_keyfield_derivation_05c0da72.plan.md`（G0 / K1–K7 / 三重全覆盖）。

面向「接手这项工作的下一个人」。目标是让 KB 侧把算子的 TilingKey 各维派生到输入根，再驱动 TG 做逐 key Z3。**不要为 FAG 做特化**，机制要能迁移。

---

## 当前状态（2026-07-29 15:50 探针快照）

```
derived 19/19   partial 0   unresolved 0
undecided 177   sched 7     max_chars 39574   ~5.3s
```

以 `history.jsonl` / 最近一次 `scripts/_probe_derive.py` 为准。明细：`fag_arch35.md`。

| 验收项 | 状态 |
| --- | --- |
| 字段覆盖 19/19 | **已到**，假成功（B1–B5）已清 |
| I1–I12 条件对齐 | **结构性通过**（`.probe_cache/diag_align.py`） |
| key 判定 8705/8705 | **未做**（K6） |
| 值域覆盖 | **未做** |
| G0 fixture / K5 / K7 | **未做** |

**不能宣称三重全覆盖已达成。**

起点曾是 `derived 14/19、max_chars 3.38 亿、全量数分钟`。`undecided` 从早期「假成功的 0」涨到现在 177，是更多真实守卫被显式化后的**可审计过近似**，不是回归。

---

## 工具

`scripts/_probe_derive.py` 是唯一调试入口。每字段独立进程 + 超时。

```powershell
python scripts/_probe_derive.py                         # 全量，约 5–15s（有缓存）
python scripts/_probe_derive.py IsTndSwizzle --timeout 60
python scripts/_probe_derive.py --show IsTndSwizzle
python scripts/_probe_derive.py --refresh               # 重跑 clang，约 2–3 分钟；改了 clang_walk 才需要
```

缓存（gitignore）：`.probe_cache/fag_bundle.pkl`、`fag_derive.json`。

```python
import sys, pickle
sys.path.insert(0, "engines/understand-operator/src")
b = pickle.load(open(".probe_cache/fag_bundle.pkl", "rb"))
ir, resolver, model, binding = b["host_ir"], b["resolver"], b["var_model"], b["binding"]
```

诊断脚本（均可从仓库根跑）：

| 脚本 | 用途 |
| --- | --- |
| `.probe_cache/diag_align.py` | 19 维值叶 + I1–I12 对齐（**改派生后必跑**） |
| `.probe_cache/diag_collapse.py` | 恒真/恒假比较、值叶塌缩 |
| `.probe_cache/diag_undecided_impact.py` | undecided 主题分类 / 对后续任务影响 |
| `.probe_cache/diag_bn2s2.py` | `bn2S2RouteLimit` 是否残留不透明 Ref |
| `.probe_cache/diag_independent.py` | 表达式支持是否真正进 value_expr |

单测：从 `engines/understand-operator` 跑；仓库根会因 rootdir 误报。基线约 4 个与本工作无关的红测，勿混淆。

```powershell
cd engines/understand-operator; python -m pytest tests/unit/test_host_ir_clang.py -q
```

---

## 已完成的修复（按依赖 / 时间顺序）

### A. 基础设施（早先）

1. **复合赋值** `clang_walk.py`：`+=` 从 token 重建 RHS，避免记成覆盖。  
2. **表达式 DAG** `derive_key_fields.py`：`_pretty_dag` / `_ememo` / `_lower` / `_collect_vars_dag` —— `max_chars` 从亿级降到万级，是后续一切前提。  
3. **局部量误判 TILING_DATA** `source_resolver.py`：Params 快速路径降为兜底。  
4. **解析器** `cpp_expr.py`：若干边角。  
5. **分类器多 return 内联**：`≥2/3` 常量 return + 逆序 first-match；修 `_chase_helper_body` 首 return 假成功；`_is_constant` 不把轴名当常量；`_substitute_names` 跳过成员。  
6. **布尔字段走 `_guard`**：否则 `IsTndSwizzle` 等被一个不可约合取项整场打死。

### B. Soundness（problem.md B1–B5）

| Bug | 修法 | 结果 |
| --- | --- | --- |
| B1 SplitAxis 塌成单值 | early-return 守卫 + `_chain` 无守卫写只盖同函数；跨函数 → `__reached_Fn` | 值叶含 BN2 / BN2S2 / BN2GS1S2 |
| B2 IsTndSwizzle 恒 0 | 随 B1 | 多值 |
| B3 IsPse / IsAttenMask 恒 1 | `clang_walk` compound 传播 guard-clause 否定（含 if-return-else） | 双值 + OPTIONAL_INPUT |
| B4 IsEmptyTensor 恒 0 | `merge_literal_encode_alts` 并回 literal-only 空 tensor 站 | 含 TILING_KEY_1 |
| B5 循环 i 折成 0 | `_loop_scoped_only`：仅 for-init 的写不链式折叠 | 不再 `0==0` |

### C. 表达式支持

1. **Select / 下标** → `VAR_ELEM_*`（容器 root）；展开时 array 槽保持符号化。  
2. **back / front / size** → 与归约同类，不展开掉容器名。  
3. **具名常量数值化** `variable_model.named_constants`（enum + constexpr；含 kernel 头）。  
4. **GetData slug 撞名**：元素/归约变量用容器表面名，不用 `GetData`。

### D. 正确性 / 对齐（本轮）

1. **三元 RHS 错绑** `source_resolver.resolve_value`：赋值 RHS 的 `c ? a : b` 不收集 `c` 的 provenance。  
   - 修前：`fBaseParams.d` → `OPTIONAL_INPUT_PRESENCE`（hasRope）  
   - 修后：→ `INPUT_SHAPE`；`d <= NUM128` → 数值 128  
2. **splitAxis ↔ bn2S2RouteLimit 环** `_canonical_name`：裸名与 `fBaseParams.*` 共用栈帧。  
   - 修前：守卫残留 `Ref(bn2S2RouteLimit)`，I12 的 `!hasRope` 进不了树；`max_chars` ~148k  
   - 修后：残留 Ref = 0；`max_chars` ~40k；I12 对齐通过  

### E. 对齐验收口径

```powershell
python .probe_cache/diag_align.py
# 期望: fields_fail=0 | inv_fail=0
```

I2/I3 仍是**过近似**（未建模 `GRAPH_FAILED` 收窄），结构性「能支撑蕴含」即可，不算假成功。

---

## undecided（177）——影响与对策

去重后约十类；**不需要 LLM**。

| 约略条数 | 主题 | 对后续 | 处理 |
| ---: | --- | --- | --- |
| ~32 | `ret != GRAPH_SUCCESS` | 软化 OK | 保持软（合法输入假设） |
| ~28 | `__reached_*` | 过近似 | 保持软；或以后加调用图 |
| ~25 | `PlatformAscendC` / `GetCoreNumAic` | 靠核数的分支 | **K5** |
| ~36 | layout `strcmp` cascade | 展开吵、易 UNMAPPED | **算法**：归一成 `INPUT_FORMAT` |
| ~16 | `isDeterministic` / deter 临时量 | B6 过近似 | 算法展开 / SESSION_OPTION |
| ~7+7+7 | syncRounds / 分核累加 / invalidS1Array | 调度 | **应软化**，勿硬建模 |
| 少量 | `m>n`、`needChangeSplitItem`、`s1s2TemplateSize.second`、`tailZeroCount` | 输入相关 | 局部链 / 形参匹配 / `++` 写点 |

对 **K6 逐 key Z3**：undecided → 自由 bool → 约束变弱 → **可能多放行非法 key**，很少误杀合法 key。  
**可以开 K6，结果偏松**；要收紧先补 layout + K5，调度类继续软。

---

## 剩余问题（按优先级）

### 1. 开 K6 前建议先确认

- 再跑一遍 `diag_align.py` + `diag_collapse.py`（只剩 IsRegbase 恒 1 合法、IsRope 检测器误报可接受）。  
- 接受 undecided 过近似，或先做 layout strcmp 归一（高杠杆、非必须）。

### 2. K6 — 逐 key Z3（三重覆盖第 2 项）

- 删 `IR_TPL_IDENTITY`、`input_derivable: True` 硬编码。  
- `classify_key_reachability` 逐 key 调 z3，输出 OK / Z3_UNSAT / Z3_UNKNOWN + 见证。  
- **派生假折叠未清时不要接**（当前对齐已过，可接）。

### 3. K5 — platform_context

- 读 CANN platform_config；读不到 → 带值域自由变量。  
- `GetDeterministic` → SESSION_OPTION（与 resolver 的 CONSTANT False 不一致问题一并收）。

### 4. K1 / K2 收尾

- 导出 `ir/host_derivation.yaml`。  
- `select_encode_site` 仍单站；空 tensor 已靠 `merge_literal_encode_alts` 补上，真多站 select 仍缺。

### 5. G0 fixture + K7 gate

- `tests/fixtures/flash_attention_score_grad/{key_field_truth,key_invariants}.yaml`。  
- 把 `diag_align` / collapse 升成正式回归。  
- gate：19/19、relations 非空、8705 判定无 UNKNOWN、不变式自洽。

### 6. 已知过近似（不排除合法用例）

- **B6** `isDeterministic` 仍偏自由（I8 的 DeterType=0 支推不紧）。  
- **VAR_SHAPE_GETSTORAGESHAPE** 过粗（`d`/`d1`/`b` 可能撞 id）—— 影响 Z3 可信度，对齐检查看不出来。  
- I2/I3 值域未按 GRAPH_FAILED 收窄。

### 7. 勿再踩的坑

- **阻塞点 ≠ 根因**：先桩掉第一个 OPAQUE，看后面还有多少致命点。  
- **假成功比 unresolved 更危险**：`derived` 但值域塌成单常量。  
- 改 `clang_walk` 才 `--refresh`；只改 deriver / resolver 用现成 bundle 即可。  
- `_pretty` 会把 DAG 打爆；调试用 `_pretty_dag` 或截断后的 `expanded` 缓存（注意缓存可能截断到 20k，对齐检查要用 live tree）。  
- 环检测不要用「裸名 ↔ 字段路径」误伤首次解析；用 `_canonical_name` 共用栈帧。

---

## 关键文件地图

| 路径 | 角色 |
| --- | --- |
| `uo_init/derive_key_fields.py` | 守卫化赋值 DAG、分类器内联、元素/归约、规范名 |
| `uo_init/clang_walk.py` | 写点 + early-return 守卫、复合赋值、RETURN_SLOT |
| `uo_init/source_resolver.py` | 根归约；`resolve_value` 三元值位置 |
| `uo_init/variable_model.py` | 变量域；`named_constants` |
| `uo_init/predicate.py` | SMT-lite 归一化 |
| `uo_init/tpl_bind.py` | encode 绑定；`merge_literal_encode_alts` |
| `uo_init/assemble_kb.py` | bundle；灌 enum/constexpr |
| `docs/debug/problem.md` | 假成功审计快照（B1–B5 部分已过时，以本文为准） |
| `docs/debug/history.jsonl` | 每次探针指标 |

---

## 建议的下一步顺序

1. `python .probe_cache/diag_align.py` 确认仍全绿。  
2. **K6**：删恒等占位，逐 key Z3（先接受偏松）。  
3. **K5** + layout strcmp 归一（收紧假阳性）。  
4. G0 fixture + 把 align/collapse 做成 CI。  
5. K7 gate；再跑通 uo-init → tg-solve。

每步对比 `history.jsonl` 四数：`derived / undecided / max_chars / seconds`。

---

## 单测基线（勿与新红混淆）

- `test_lineage_records_enclosing_guards` — 空格  
- `test_writes_keep_the_nested_field_path` — 扁平路径  
- `test_coverage_baseline_row` — 签名  
- `test_uint_index_encoding` — UI_LIST  

`test_isnzout_derivation_chain` 通过，是直接测派生链的用例。
