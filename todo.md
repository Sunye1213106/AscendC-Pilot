# 任务：pilot_run Task Harness

## 目标
把 `pilot_run` 从启动单一 workflow 升级为 Task Harness：自然语言原文进 LLM，slash 工作流全部保留。本次 golden E2E 是 PR → 定向 cases。

## 待办事项
- [x] Slice 1：删除短语路由；NL 原文进 LLM；Task Plan
- [x] Slice 2：Todo SoT = Goal public_plan；Public Projection
- [x] Slice 3：Primary / 文档双路径
- [x] Slice 4：Workspace Manager
- [x] Slice 5：删 TG 阶段确认；test_scope
- [x] Slice 6：test_generation 展开 + METHOD
- [x] Slice 7：Interrupt reconcile

## 进度
7/7 完成。CI 合同与 Task Harness 相关 pytest 已通过。
