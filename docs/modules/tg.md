# TG：Testcase Generation

TG 把 UO 的 Operator CodeMap 变成**脚本仓能直接跑的用例表**，再用 Host tiling 回放（无 NPU）核对义务。正式产物只有三份，外加 cases 表。

| 阶段 | 产物 | 谁写 |
| --- | --- | --- |
| `/tg-init` | `tg/init.yaml` | 两路草稿在 `runs/`，主控裁判放行后 `bind_promote` 落盘并确认 |
| `/tg-plan` | `tg/plan.md` | 上半散文，下半 YAML 义务表；人批准打 `approved` |
| `/tg-solve` | `tg/worklog.md` + `cases.csv`/`xls`/`xlsx` | 构造→Replay→分析，直到文首 `open: []` |

草稿只留 `runs/`。人确认走已有 `control/decisions/`。不要 inventory / audit / review / fingerprint YAML 旁路。

## 门禁

```text
无 .uo            → /uo-init
无 init.yaml      → /tg-init     （plan 强制这份；测试脚本仓可选，先问）
意图              → 有则从 ce/plan/*_plan.md / 对话 / session_handoff.md 自己总结，不做文件强制
无批准 plan.md    → /tg-plan
test_harness_gap 未落地 → 禁止 start solve
TG 永不改算子仓
```

`init.yaml` 必须有：`table_kind`、入口与 `--case`、精度/性能怎么跑、列映射（API 入参绑脚本读点 + UO 标识符；`script_meta` 可无标识符）、双源值域、golden、脚本比对口径、`generate_inputs`、`uo_digest`。有脚本仓但 API 入参 mapping 空 → init 失败。无脚本仓时用 `/uo-query` 读输入 API 设计控制面。扫描必须含 xls/xlsx。FAG 精度写 `only_grad`，性能写 `profiler`，禁止把精度记成 `--golden-only`。

## 规划是融合，不是套覆盖

控制面 = CSV/XLS 列。每条义务：

`id, why, uo{query,span}, control{columns,recipe}, class, hit, cover`

`class` 只有 `replay`（Host tiling）和 `derived`（公式）。root 不到的另列 `untestable.reason`。覆盖 L0–L3 写在 `cover` 上。全量 tilingkey 只在意图点名时做，**不是默认 T=D**。CE 不传 yaml 意图。

缺列或缺 `generate_inputs` → `test_harness_gap`，先 `/ce-apply` 改**测试脚本仓**，再 `/tg-init`。

## 求解

```text
已批准 plan.md
    → 构造 cases 表（脚本可直接吃）
    → Host Replay（无 NPU；无 WSL/CANN 则 replay_round 失败停住，不进 analyze）
    → 对照预期：一致进 R，不一致分类并推引理
    → open: [] 才签发
```

引理：`Replay reject ≠ E`。查算子语义优先 `uo-query`；Grep 只作定位辅助。

## 相位

```text
/tg-init
kb_check [D] → repo_scan [D] → bind_init [S fanout=2] → bind_review [Primary 通读 PASS/REWORK]
    → bind_promote [D] → validate_init [D]
                                          ──gate: init_confirmed, uo_digest

/tg-plan
plan_precheck [D] → plan_scope [S] → plan_fuse [S] → plan_promote [D]
    → plan_validate [D] → plan_approve [H]
                                          ──gate: plan_approved

/tg-solve
solve_precheck [D] → construct_cases [S] → construct_promote [D]
    → replay_round [D] → analyze_round [S] → analyze_promote [D]
    → solve_certify [D]
                                          ──gate: worklog_closed
rework: analyze → construct；validate → fuse/bind
```

Host replay 基础设施（`HostOracle`、WSL replay）仍复用；不再写 `tg/closure/**` 证书森林。

## 实现锚点

- Workflow：`pilot/ascendc_pilot/workflows/tg_specs.py`
- 确定性引擎：`pilot/ascendc_pilot/actions/tg_product.py`
- 产物校验：`engines/testcase-generation/testcase_agent/products.py`
- 改动记录：[TG 产物模型重建](../development/tg-rebuild.md)
