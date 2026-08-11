# 覆盖义务

**何时加载**：plan-build / plan-scope / cover 确认，处理声明 levels 与 uncovered 集合时。

## 要点

1. 按声明 levels / scope 生成或读取义务集合（L0–L3）
2. 过滤与对称性约束由确定性规则执行
3. uncovered 必须显式输出，不得伪造覆盖
4. 未批准 plan 时不得宣称 solve 完成
5. **L3**：义务元素为 steerable branch 的 True/False 结局（可附 key 轴）；闭环引擎为 `testcase_agent.closure.branch_outcome`，与 L2 共用 solve 相位机，禁止平行 td-* skill 树
