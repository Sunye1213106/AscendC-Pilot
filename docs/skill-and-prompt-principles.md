# Skill / Prompt / Agent / Capability 设计原则（组合式）

## 一句话区分

| 层 | 负责 | 不负责 |
|---|---|---|
| Harness Workflow | 阶段、状态、合法边、Action、门禁、完成条件 | 领域分析细节 |
| Policy | 全局稳定规则 | 具体任务步骤 |
| Capability | 可复用原子工程能力 | 工作流推进 |
| Action Method | 当前 Action 的领域方法 | 其他阶段 / advance |
| Prompt | 一次有界任务 | 完整 Workflow |
| Agent Role | 角色身份、读写边界、输出责任 | 场景路由和状态推进 |
| Generated | 宿主运行产物 | 人工维护业务源 |

## 源目录

| 路径 | 内容 |
|---|---|
| `skills-src/policies/` | 全局 Policy |
| `skills-src/capabilities/` | 原子 Capability |
| `skills-src/actions/` | Action Method |
| `skills-src/roles/` | Role 合同 |
| `skills-src/workflows/` | 薄入口 Skill |
| `prompts-src/tasks/` | 有界 task prompt |
| `agents-src/` | Agent YAML |
| `generated/` | Composer 产物（可丢弃） |

## Composer

```text
python scripts/compose_runtime.py --repo .
# 或
python scripts/compile_skills.py --repo .
```

安装只部署 `generated/<host>/{skills,agents,prompts}`。

## 八问（落在 Capability / Action Method）

Capability / Action Method 应回答：何时用、输入、方法、输出、硬限制、停止条件。  
**不得**描述 Harness advance / complete / 完整 phase WHILE。
