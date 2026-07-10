# KB File Map（canonical）

KB 根目录形态：

```text
<repo>/.understand-operator/<op_name>/
  index.yaml               # 全局机器路由入口（先读）
  route.md                 # 人类地图（overview）
  operator.yaml            # 边界 / IO / ontology / analysis_plan
  quality.yaml             # 质量门
  human/review.md          # 人工确认合并入口
  tiling/                  # canonical tiling（已定稿，勿重设计）
  flow/                    # compute / dataflow / golden / numerical
  kernel/                  # paths / pipeline / resources
  test/                    # contract only（非真实测试）
  evidence/                # source / fact / deps / issues
  archive/                 # cbm dumps / runs / legacy / raw_agents（默认不读）
  cbm/                     # 运行时 CBM 工作目录（工具用；非问答默认读）
```

## 默认读取逻辑

**所有问题先读 `<op>/index.yaml`。**

然后按 `index.yaml.qa_routes` 或下表下钻。不要默认读完整 KB。不要默认读 `archive/`、raw agent output、legacy 文件。

| 问题类型 | 读取路径 |
|---|---|
| overview | `route.md` |
| operator / IO / optional / dtype / layout | `operator.yaml` |
| tiling | `tiling/index.yaml` → 按其 `qa_routes` |
| tiling 机制 / 变量 / 影响分类 | `tiling/variables.yaml`（`tiling_mechanism` / `variables` / `impact_classification`） |
| tiling_key（编码） | `tiling/key_space.yaml` + `tiling/families.yaml` |
| tiling_key 逻辑关系 / 合法组合 / mutex·implies | `tiling/constraints.yaml`（`relations` / `variable_constraints`）+ `tiling/key_space.yaml`（`derived_fields`） |
| tiling_key 剪枝 / 合并 | `tiling/constraints.yaml`（`tiling_key_pruning` / `tiling_key_merging`） |
| tiling_key → 输入构造（TestGenerate） | `tiling/constraints.yaml`（`input_realization`）+ `operator.yaml` |
| tiling_key 关系覆盖债务 | `tiling/coverage_model.yaml`（`key_relation_obligations`） |
| tilingdata | `tiling/data_model.yaml` + `tiling/families.yaml` |
| compute flow | `flow/index.yaml` + `flow/compute_graph.yaml` |
| dataflow | `flow/dataflow.yaml` |
| golden generation | `flow/golden_model.yaml` + `flow/numerical_model.yaml` + `operator.yaml` + `tiling/data_model.yaml` |
| numerical accuracy | `flow/numerical_model.yaml` + `flow/golden_model.yaml` + `test/contract.yaml` |
| kernel path | `kernel/index.yaml` + `kernel/paths.yaml` |
| kernel pipeline | `kernel/pipeline.yaml` + `flow/compute_graph.yaml` |
| buffer / sync | `kernel/resources.yaml` + `flow/dataflow.yaml` |
| test generation | `test/index.yaml` + `test/contract.yaml` + `tiling/coverage_model.yaml` + `flow/golden_model.yaml` |
| source / evidence | `evidence/fact_index.yaml` + `evidence/source_index.yaml` |
| missing / conflict | `evidence/issues.yaml` + `quality.yaml` |
| human decision | `human/review.md` |

## 导出视图（脚本）

```bash
python kb_query_export.py <PROJECT_ROOT> --op-name <OP> --view tiling-test|golden-gen|testgenerate|kernel-debug|human
```

视图文件列表以 `index.yaml.export_views` 为准。

## tiling/（已定稿）

| 文件 | 语义 |
|---|---|
| `variables.yaml` | Step 1 variable-model source of truth (mechanism + variables + impact classification) |
| `key_space.yaml` | tiling_key encoding source of truth |
| `constraints.yaml` | Step 2 constraint-model source of truth (relations + pruning + merging + input_realization + key_unreachable) |
| `families.yaml` | structural route / family source of truth |
| `data_model.yaml` | tilingdata source of truth |
| `coverage_model.yaml` | coverage obligations only |
| `route.md` | human tiling route |
| `index.yaml` | tiling qa_routes |
| `evidence_index.yaml` | tiling source evidence |

### tiling/archive/（init 强制中间层，问答默认不读）

远程旧版把这些放在 `tiling/` 根目录；本地合并成 7 个 canonical 后曾变成可选，导致 AI 跳过宏/编译期细节。现已恢复为 **`/uo-init` 强制落盘**：

| 文件 | 语义 |
|---|---|
| `frontier.yaml` | 所有 tiling 决策点（guard / key setter / writer / template） |
| `dispatch_variables.yaml` | 分流变量分类（再合并进 key_space） |
| `predicate_space.yaml` | 归一化谓词与 mutex/implies 关系 |
| `compile_time_bindings.yaml` | 宏 / constexpr / 模板 / `if constexpr` reachability |
| `decision_tree.md` | 编译期 vs 运行期决策树，叶子 → TFxxx |
| `kernel_evidence_backfill.yaml` | Phase 5 回填（非 host 阶段） |

barrier / quality gate 会检查上述前 5 个非空且非 pending。调试宏/DeterType/arch 开关时，可显式读 archive。

重要区分：

- family coverage != tiling_key coverage
- seed_cases / branch samples != full key enumeration
- has_varlen-like paths may share tiling_key but differ in tilingdata numeric behavior
- compile-time axes (DeterType / arch / dtype) must be in `compile_time_bindings` before shallow family merge

## flow/

| 文件 | 存什么 |
|---|---|
| `compute_graph.yaml` | 计算语义步骤 Cxxx（非 kernel pipeline） |
| `dataflow.yaml` | 搬运 / memory level Dxxx |
| `golden_model.yaml` | GoldenGenerate 语义模型（无代码） |
| `numerical_model.yaml` | dtype / cast / tolerance / randomness |

## kernel/

| 文件 | 存什么 |
|---|---|
| `paths.yaml` | family ↔ kernel path 结构映射 |
| `pipeline.yaml` | path 内 stages + compute_step_alignment |
| `resources.yaml` | buffer / workspace / sync |

## test/

| 文件 | 存什么 |
|---|---|
| `contract.yaml` | TestGenerate 契约；禁止 generated_cases / CSV / observed_coverage |

## evidence/

| 文件 | 存什么 |
|---|---|
| `source_index.yaml` | SPxxx source spans |
| `fact_index.yaml` | fact ↔ evidence ↔ spans |
| `artifact_dependencies.yaml` | PR impact / 增量更新 |
| `issues.yaml` | missing / conflicts / warnings / unknowns |

## Legacy KB 检测

若缺少 `index.yaml` / `operator.yaml` / `flow/`，但存在旧文件（`summary/`、`flows/`、`testing_hints/`、`route.json`、`quality_gate.yaml`、`tiling/tiling_branch_families.yaml` 等），提示：

> This KB uses legacy artifacts. Run `/uo-update` or `/uo-init` to regenerate canonical KB files.

不要在 uo-query 里做复杂 legacy migration。

## 禁止

- 默认读取 `archive/`
- 默认读取 raw agent output
- 默认读取旧 legacy 主产物
- 每次读完整 KB
- 用 branch_matrix / seed_cases 回答 full tiling_key coverage
- 用 family count 回答 tiling_key coverage
