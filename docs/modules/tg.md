# TG：Testcase Generation

TG 把 UO 的 Operator CodeMap 变成**脚本仓能直接跑的用例表**，再用 Host tiling 回放（无 NPU）对 Target / Dimension / Guard 做确定性分类。正式产物只有三份：

| 阶段 | 产物 | 谁写 |
| --- | --- | --- |
| `/tg-init` | `tg/init.yaml` | 两路草稿在 `runs/`，主控裁判放行后 `bind_promote` 落盘并确认 |
| `/tg-plan` | `tg/plan.md` | 散文（测什么 / 覆盖什么 / 怎么判定）+ YAML：Target / Dimension / Guard / L0–L3；人批准打 `approved` |
| `/tg-solve` | `tg/worklog.md` + `cases.csv`/`xls`/`xlsx` | 引擎展开义务；Replay 后 `coverage_eval` 更新 worklog 围栏；**certify 才写出正式 cases** |

子代理 `return_value`，禁止 Write。过程中不落 `targets.yaml` / staging / `coverage_ledger.yaml`。

## 门禁

```text
无 .uo            → /uo-init
无 init.yaml      → /tg-init     （plan 强制这份；测试脚本仓可选，先问）
意图              → 有则从 ce/plan/*_plan.md / 对话 / session_handoff.md 自己总结，不做文件强制
无批准 plan.md    → /tg-plan
test_harness_gap 未落地 → 禁止 start solve
TG 永不改算子仓
```

`init.yaml` 必须有：`table_kind`、入口与 `--case`、精度/性能怎么跑、列映射、双源值域、golden、脚本比对口径、`generate_inputs`、`uo_digest`。

## 规划是 Target / Dimension / Guard，不是套覆盖

控制面 = CSV/XLS 列。未指定方向时 Target = Host 接受的 dispatch（`tiling_key` 可观测）；candidate dimensions = UO 已声明且通过 RCPO 的 TilingKey 维。B/N/S/D 默认只是 Control。

谓词必须是结构化 `op=` mapping。覆盖 L0–L3 写在 `coverage` 上。全量 tilingkey 只在意图点名时用 `coverage.enumerate: legal_keys`，**不是默认 T=D**。

缺列或缺 `generate_inputs` → `test_harness_gap`，先 `/ce-apply` 改**测试脚本仓**，再 `/tg-init`。

## 求解

```text
已批准 plan.md
    → compile_obligations 把义务进度写入 worklog 围栏
    → construct 交回 rows 和/或 recipe（不写正式 cases）
    → Host Replay（无 NPU；无 WSL/CANN 则 replay_round 失败停住）
    → coverage_eval 分类 CLOSED / MISS / UNKNOWN / GUARD_LEAK
    → analyze 只处理 MISS / UNKNOWN
    → ledger 闭合才签发，并物化 cases
```

签发看 worklog 围栏 ledger，不看空 `open: []` 散文。`Replay reject ≠ E`。`GUARD_LEAK` 停 refine，留给 CE。

## 相位

```text
/tg-init
kb_check [D] → repo_scan [D] → bind_init [S 1 harness + N bind，每路 ≤20 列] → bind_review [Primary 通读 PASS/REWORK]
    → bind_promote [D] → validate_init [D]
                                          ──gate: init_confirmed, uo_digest

/tg-plan
plan_precheck [D] → plan_scope [S return_value] → plan_fuse [S return_value] → plan_promote [D]
    → plan_validate [D] → plan_approve [H]
                                          ──gate: plan_approved

/tg-solve
solve_precheck [D] → compile_obligations [D]
    → construct_cases [S return_value] → construct_promote [D]
    → replay_round [D] → coverage_eval [D]
    → analyze_round [S return_value] → analyze_promote [D]
    → solve_certify [D]
                                          ──gate: worklog_closed
rework: analyze → construct；validate → fuse/bind
```

Host replay 基础设施（`HostOracle`、WSL replay）仍复用；不再写 `tg/closure/**` 证书森林。插桩只改 TG sandbox 拷贝，禁止改算子 git。

## 实现锚点

- Workflow：`pilot/ascendc_pilot/workflows/tg_specs.py`
- 确定性引擎：`pilot/ascendc_pilot/actions/tg_product.py`
- 产物校验：`engines/testcase-generation/testcase_agent/products.py`
- 覆盖：`engines/testcase-generation/testcase_agent/coverage/`
