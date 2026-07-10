# ST Design Alignment

本文件说明 `testcase-generator` 与 `ascendc-st-design` 的映射关系。

## 职责边界

| 项目 | 输入 | 输出 | 覆盖对象 |
|---|---|---|---|
| `ascendc-st-design` | aclnn 接口文档 | ST CSV / coverage report | **接口参数空间**（dtype/shape/attr） |
| `testcase-generator` | understand-operator KB | tilingkey cases / audit | **tiling_key / family / tilingdata 空间** |

两者互补，不互相替代：

- ST 保证接口层功能/精度门槛
- TG 保证 host tiling 分发与 key 覆盖可验证（`observed_tiling_key`）

## 流程映射

| ST 步骤 | TG 对应 |
|---|---|
| 1 输入校准（接口文档） | `tg-init` 校准 UO KB（`quality.yaml` + tiling 四件套） |
| 2 参数定义 | `kb_snapshot.operator_io` + `input_realization` |
| 3 测试因子提取 | `engine/factor_space.py` → `generate/factor_space.yaml` |
| 4 约束关系分析 | `engine/rule_model.py` → `generate/rule_model.yaml` |
| 5 隐式约束 | family guard / present_when / constants 自动编译 |
| 6 求解配置 / 拓扑 | `factor_space.solver`（anchors + derivation_order） |
| 7 因子值生成 | candidate 生成 + prune |
| 8 L0/L1/L2 用例 | `tg-generate --level` |
| 9 结果总结 | `tg-audit` + `tg-report` |

## 产物映射

| ST design 产物 | TG 产物 |
|---|---|
| `03_参数定义.yaml` | `kb_snapshot.yaml` 的 `operator_io` |
| `04_测试因子.yaml` | `generate/factor_space.yaml` |
| `05_约束定义.yaml` | `generate/rule_model.yaml` |
| `06_求解配置.yaml` | `factor_space.solver` |
| `07_因子值.csv` | `generate/candidate_keys_valid.yaml` |
| `*_L*_test_cases.csv` | `generate/realized_cases.yaml` + `probe_cases.jsonl` |
| `*_coverage_report.yaml` | `audit/coverage_audit.yaml` |

## 不可混用的概念

1. **ST L2 = 异常用例**；TG 旧实现曾把 pairwise 标成 L2 —— 已纠正。
2. **ST 覆盖率看参数因子**；TG 覆盖率只认 `observed_tiling_key`。
3. **ST 可从文档推导**；TG 禁止重新扫源码，只消费 KB。
4. Family coverage ≠ tiling_key coverage（两边都要写进报告）。
