# 闭环证书与审计

**何时加载**：准备签发 gap=0 或审计闭环证书时。

签发前检查：

1. `R ∩ E = ∅`
2. E 中每条规则有可 replay 证书且过反例检验
3. 与当前 R 冲突的规则已 revoke
4. 全覆盖证书：`D = (R ∩ D) ∪ E`（当计划 `T=D` 时与 Solve 闭合 `T = (R ∩ T) ∪ E` 重合）
5. `scenario_targeted` overlay 闭合的是 ScenarioSet 义务，不把 `T` 改写成 `D`
6. Corpus 不含不可信裁决

审计角色只验证上述性质，不开放式发明新排除规则。
