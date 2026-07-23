---
name: operator
description: >-
  acp route 别名。不维护第二路由表。
disable-model-invocation: false
---

# operator

本 Skill 不定义工作流阶段。执行时：

1. 调用 `acp route "<用户原文>"`；
2. 按返回加载对应 workflow Skill；
3. 不得自行维护路由规则副本。
