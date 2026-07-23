# 合同构建

## Purpose

基于只读 UO KB 生成 TG 合同骨架，缺口显式列出。

## Method

1. 确认 UO KB 定稿可读。
2. 映射字段到合同 schema。
3. 无法映射的写入 gaps，不伪造。

## Hard Constraints

- MUST NOT：修改 UO KB。
- MUST NOT：直调领域 CLI；经 Pilot 包装动作执行。
