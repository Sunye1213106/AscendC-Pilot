# 覆盖义务分析

## Purpose

分析覆盖义务集合与未覆盖项，供 plan/solve 使用。

## Method

1. 按声明 levels / scope 生成或读取义务。
2. 过滤与对称性约束由确定性规则执行。
3. uncovered 显式输出。

## Hard Constraints

- MUST NOT：在未批准 plan 时宣称 solve 完成。
- MUST NOT：伪造覆盖。
