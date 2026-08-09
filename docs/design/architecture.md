# AscendC-Pilot 架构现状

本文只写**当前已落地的形态**，不写历史计划。闭环认知见 `skills/domain/tg-closure` 与 `skills/domain/source-lemma-proof`；组合式 skill 原则见 [skill-prompt.md](./skill-prompt.md)；系统数据流见 [system-design.md](./system-design.md)。

---

## 1. 三层分工

| 层 | 职责 | 权威入口 |
| --- | --- | --- |
| Pilot | 工作流状态机、`acp next` / `run-action`、gate、收据 | `pilot/ascendc_pilot/` |
| UO | 静态抽取 Host / TilingKey / Kernel / TilingData → KB | `engines/understand-operator/` |
| TG | 合同、计划、TilingKey 闭环 `(D,R,E)` | `engines/testcase-generation/` |

编排骨架：`Policy`（全局规则）→ `Capability`（可组合能力）→ `Action METHOD`（单步领域）→ `Task prompt`（有界壳）。权威组合在 `pilot/.../workflows/specs.py`，由 `scripts/compose_runtime.py` 编译到 `generated/<host>/`。

---

## 2. UO 流水线（现状）

主路径 action（`uo_init.pilot_engines.ENGINES`）：

```text
prepare_layout → scope_scan → scope_confirm
  → extract_host → extract_tiling_key → extract_registry → extract_kernel
  → derive_key_fields → normalize_predicates → resolve_gaps → apply_gap_patch
  → export_kb → build_index → export_tg_host_view → export_integrity → kb_review
```

要点：

- **静态主路径**：libclang HostIR、`kernel_ir`（`if constexpr`）、`tiling_data_ir`、派生 `host_derivation`。
- **Z3 默认关闭**：`UO_DEEP_SOLVE` 未设时 materialize 走 `deep_solve_off`。
- **产物目录**：工作区仍可在 `<op>/.ascendc-pilot/<arch>/uo/`；**正式权威产物**为 `<op>/.ascendc-pilot/uo/<op>.<arch>.uo`（统一 CodeMap SQLite，`meta.authority=uo`）。旧 `indexes/kb_graph.sqlite` / YAML 投影由 `uo-dump` 临时展开，不再作为产品面。
- **YAML**：可选导出，由 `UO_KB_YAML` 控制（默认 `1` 兼容测试；生产目标 `0`）。按需：`python -m uo_init.dump <view>`。

`resolve_gaps` 的 LLM 补洞**不得**默认进 sound 排除集；默认应关闭或产出 `grade: llm`。

---

## 3. TG / TilingKey 闭环（现状）

闭合契约：

```text
D = (R ∩ D) ∪ E    且    R ∩ E = ∅
```

- **R** 只来自真实 Host 裁决（`###DONE` / 宽表）。
- **E** 只来自 `SOUND_GRADES = {source_lemma, solver_derived}`，且须过反例检验与证明五检查。
- **代理模型只排序候选，永不排除 Key。**

引擎包：`testcase_agent/closure/`（ledger / search_round / lemma / construct / explain / mine / report…）。  
CLI：`tg-closure`（`python -m testcase_agent.closure.cli`）。  
确定性路由：`search_round.route()` → `GAP_ZERO | ORACLE_SUSPECT | SEARCH_STALLED | CONSTRUCT_TARGETS | NEED_LEMMA | SEARCH_PROGRESS`。

Pilot 工作流 `tg-solve`（mode `tilingkey_full_coverage`）把上述步骤编排进 `acp` 阶段机；领域证据纪律见 `skills/domain/tg-closure` 与 `skills/domain/source-lemma-proof`。

算子侧冷启动契约（目标）：`operators/<op>/<arch>/` 仅保留

- `operator.yaml`
- `log_protocol.yaml`
- `input_semantics.py`

其余 adapter pack（bridge / feature_bindings / search_hints / construction_hints）由 UO 从 KB **自动导出**，默认写入 `.ascendc-pilot/<arch>/uo/adapter/`；`proof_rules` / active lemmas 由闭环自证，不预置先验。

---

## 4. 三域同构（方向）

TilingKey / KernelBranch / TilingDataField 共用同一账本形状 `(D,R,E)`：

| 域 | D 来源 | R 来源 | E 来源 |
| --- | --- | --- | --- |
| TilingKey | TPL header 声明 | Host witness | 源码引理 |
| KernelBranch | `views/kernel` / DB | witness key 上求值 constexpr | 条件在 `D−E_key` 上恒假的源码证明 |
| TilingDataField | `views/tilingdata` / DB | 真机 dump 或标注为 over-approx 的静态覆盖 | 缺陷（no_writer/no_reader）+ 可证不可达 |

跨层边已在 KB schema：`controls` / `binds` / `writes` / `reads`。

---

## 5. 相关文档

| 文档 | 用途 |
| --- | --- |
| `skills/domain/tg-closure` | 闭环认知（含 `closure-safety`） |
| `skills/domain/source-lemma-proof` | 源码引理证明 |
| [system-design.md](./system-design.md) | 数据流与模块边界 |
| [skill-prompt.md](./skill-prompt.md) | Domain / Prompt / Harness 原则 |
| [principles.md](./principles.md) | 产品修改口诀 |
| [../fag/tilingkey-closure-report.md](../fag/tilingkey-closure-report.md) | 历史校准结果（非 Skill） |
| [../case-studies/](../case-studies/) | 命名案例溯源（Agent 默认不读） |
