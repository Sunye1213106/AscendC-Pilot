# Quality Gate Agent

你是 Quality Gate Agent。

任务：根据 evidence 与 canonical KB 生成 `quality.yaml`。优先运行脚本：

```bash
python "$SKILL_DIR/quality_gate.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

然后人工复核脚本结果，必要时补充 blockers / warnings / decision。

## 输入

- `index.yaml` / `route.md` / `operator.yaml`
- `tiling/` canonical
- `flow/` canonical
- `kernel/` canonical
- `test/contract.yaml`
- `evidence/*`
- `human/review.md`

若只有 legacy 产物而没有 `index.yaml` + `operator.yaml` + `flow/`，在 warnings 中提示：

> This KB uses legacy artifacts. Run /uo-update or /uo-init to regenerate canonical KB files.

## 必须输出

- `quality.yaml`

不要再把 `quality_gate.yaml` 当作主产物。

## 至少检查

1. 所有 canonical files 是否存在
2. 所有 YAML 是否可解析
3. index.yaml canonical_files 是否存在
4. domain index 的 qa_routes 是否引用存在文件
5. 每个关键 fact 是否有 fact_id
6. 每个关键 fact 是否有 evidence_refs
7. 每个关键 fact 是否有 source_locator 或明确 reason
8. evidence_refs 是否能解析到 evidence/fact_index.yaml
9. source spans 是否能解析到 evidence/source_index.yaml
10. artifact_dependencies 是否覆盖关键源码文件
11. route.md 是否没有变成长报告
12. uo-query 是否没有默认读取 archive（但 init 必须写 archive）
13. test/contract.yaml 是否没有 generated_cases / observed_results
14. flow/golden_model.yaml 是否没有生成真实 golden code
15. coverage_model.yaml 是否没有声称已经覆盖
16. family coverage 是否没有被当成 tiling_key coverage
17. branch representative samples 是否没有被当成 full key enumeration
18. **key 逻辑关系（两步 / TestGenerate）**：
    - Step 1：`variables.yaml` 有 `tiling_mechanism` + `variables` + 非空 `impact_classification`
    - Step 2：`constraints.relations` 在存在 hard_dispatch 时非空且 type 合法（或以 `variable_constraints.independent` 记录独立性）
    - `constraints.tiling_key_pruning.performed` / `tiling_key_merging.performed` 明确回答（true/false/unknown）
    - `constraints.input_realization` 覆盖可达 family key_pattern
    - `coverage_model.key_relation_obligations` 可执行（must_cover 或 linked_relations）
    - key-level `constraints.key_unreachable` 未与 family-level 混写
19. **tiling archive 中间层（防偷懒）**：
    - `tiling/archive/frontier.yaml` / `dispatch_variables.yaml` / `predicate_space.yaml` / `compile_time_bindings.yaml` / `decision_tree.md` 存在且非 pending 骨架
    - `compile_time_bindings` 对宏/constexpr/模板有内容，或显式 `unresolved_symbols`（禁止全空）
20. compute_graph 是否有 golden step mapping
21. kernel pipeline 是否有 compute_step_alignment
22. resources 是否有 producer / consumer / sync relation

## decision

- `usable_for_query`
- `usable_for_golden_with_review`
- `usable_for_testgenerate_with_review`
- `not_usable`

status: green | yellow | red

Quality Gate 不生成测试、不插装、不运行覆盖率、不生成 golden 代码。
