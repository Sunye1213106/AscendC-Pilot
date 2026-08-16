# 扩展 AscendC-Pilot

新增能力前，先判断它应落在何处。把所有新想法都包装成 Agent 会造成身份、权限和 prompt 的不必要膨胀。

```text
确定性计算              -> Engine
领域推理方法            -> Skill
一次任务说明            -> Prompt
状态与迁移              -> Workflow
可执行步骤              -> Action
需要独立 identity/context/permission/referee -> Agent
工具或 runtime 方法合同 -> Capability
控制面传输与派发        -> Host Session Driver（Host Adapter 运行时）
```

## 新增或修改 Workflow / Action

Workflow 权威在 `pilot/ascendc_pilot/workflows/specs.py`。新增状态时要同时定义 forward 和 rework transition、phase gate、完成条件及 `write_roots`。每个 action 还需要明确 `agent_id`、`role_id`、`execution_mode`、prompt、capability、输入输出合同和允许读写路径。

路径规则变化时同步更新 `pilot/ascendc_pilot/ownership.py`，并为 phase movement、gate 和 lease scope 增加测试。完成后重新生成 host runtime：

```bash
python scripts/compose_runtime.py --repo . --host opencode
python scripts/compose_runtime.py --repo . --host cursor
python scripts/compose_runtime.py --repo . --host codex
```

## 何时新增 Agent

只有确实需要上下文隔离、并行 bounded bundle、更窄权限、producer/referee 分离或对抗性审查时，才添加 `agents/<id>.yaml` 并在 action 中引用它。Agent YAML 只是权限上限；最终权限仍由 Action Lease 的三层交集决定。

不要把 canonical 路径授给 staged producer，也不要让 producer 与 adversarial referee 使用同一 identity。修改 Agent 后生成 matrix：

```bash
python scripts/generate_reference_docs.py
python scripts/check_ownership_contracts.py
```

## 新增或扩展 Skill

Skill 是自包含的 runtime method bundle。修改 `skills/<domain>/SKILL.md`，将必要的证据、完整性和易错点规则放在 `references/`，将可执行示例放在 `examples/`。行为改变时更新 `evals/skills/<domain>/`。

不要往已删除的 `skills/_shared/` 加文件（**已删除，勿再添加**），也不要把项目架构说明复制进 Skill。运行：

```bash
python scripts/check_skill_architecture.py
```

认知 skill 仍是闭合的五个（见 `skills/SCHEMA.md`）。开发 Pilot 本仓的 grilling / TDD / 诊断 / PR 审查放在 `.cursor/skills/`，不要写进 `agents/*.yaml` 的 `skill_ids`，compose 也不会投影它们。改 agent 向文档时读 `.cursor/skills/writing-for-pilot-skills`。共享语言改 `agents/CONTEXT.md`。这些维护者 skill 吸收了 [mattpocock/skills](https://github.com/mattpocock/skills) 的写法（grilling、缝上的 TDD、双轴 review、CONTEXT），没有把 `/implement` 装进算子主控。

## 新增 Engine、Capability 或 Host Adapter

Engine 放在 `engines/<name>/`，应有 package metadata、测试和需要时的 CLI entry point；若 Pilot 需要授权它，则新增 deterministic identity 并把 action 接入 workflow。Capability 应描述可调用的工具或 runtime 方法合同，而非承载领域解释。

Host Adapter 负责两件事：安装期 composition，以及（OpenCode）运行时 Session Driver（`pilot_run` / `host_step` 派发）。Driver 不得改写 workflow 事实、不得 advance/complete、不得宣布 `passed`。修改 plugin 或 dispatch 协议后：

```bash
python scripts/compose_runtime.py --repo . --host opencode
# 再跑 install 把 plugin 投影到用户 Host
acp doctor --host opencode
python scripts/check_host_driver_contract.py
```

并在 [Agent Runtime](../architecture/agent-runtime.md) 中登记对人类有意义的 Engine / adapter 边界。Agent YAML 路径优先使用 `pilot:` / `method:` / `source:` 命名空间；prepare 会物化 cognitive skill 正文，读失败走 `BUNDLE_NOT_READABLE`。

## Gate、测试与 Reference

任何会影响规范产物或状态迁移的能力都需要 gate/contract 与针对失败路径的测试。最后运行：

```bash
python scripts/generate_reference_docs.py
python scripts/check_docs.py
python scripts/check_ownership_contracts.py
pytest
```
