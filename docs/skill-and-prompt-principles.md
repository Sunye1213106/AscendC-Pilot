# Skill / Prompt / 脚本 设计原则（仓内摘要）

本文是本仓库可复核的最小原则集，替代对仓外 `优秀skill和prompt.md` 的硬依赖。

## 一句话区分

**Skill 管流程、状态、权限和质量门；Prompt 只处理当前有限的语义任务；脚本负责确定性逻辑。**

| 层 | 职责 | 本仓例子 |
|---|---|---|
| Skill | 可重复执行的工作流协议：触发条件、I/O、阶段、门禁、失败码 | `/uo-init`、`/uo-query`、`/tg-plan`、`/tg-solve` |
| Prompt / Agent | 单次有界任务：权威源、输出 schema、验收 | `uo-semantic-resolve` 任务合同、`tpl_*` |
| 脚本 | 确定性逻辑，不靠 LLM 猜 | classify / apply / integrity / Z3 / `uo_kb_query` |

## Skill 必须回答的八问

1. 什么时候触发
2. 输入是什么
3. 输出什么
4. 按什么阶段执行
5. 每个阶段允许使用什么工具
6. 哪些事情绝对禁止
7. 失败后怎么处理
8. 怎样判断真正完成

### 可执行细则

- **单一职责**：Skill 名应能概括唯一状态转换（例如 approved plan → CSV rows）。
- **唯一事实源**：声明哪个文件拥有定义权、冲突时谁优先、哪些路径禁止生成或修改。
- **有限状态机**：阶段有进入/退出条件；禁止写成「分析项目并生成结果」式模糊流程。
- **工具策略**：按阶段限制工具面；确定性步骤走脚本，不让 Agent 手算覆盖率或手写全量对齐。
- **失败路径**：显式失败码 / 停机条件；禁止跨阶段擅自补救。

## Prompt / Agent 必须具备

- **单次有界**：一次任务只做一类语义工作，不接管整个 Skill 状态机。
- **权威源**：写明可读路径与禁止写入面（见 `spec/ownership.yaml`）。
- **输出 schema**：结构化字段、必填项、不得臆造的枚举。
- **验收**：怎样算完成；缺证据时如何降级或上报，而不是静默编造。

## 脚本边界

- 分类、合并、完整性、导出、SMT 求解等确定性步骤 **MUST** 走脚本。
- Prompt 不得要求 Agent「手工复现」脚本已能完成的计算。
- 路径以 `PLUGIN_ROOT` / `SCRIPT_DIR` 为准；禁止依赖幻觉出的相对目录（见 `skills/*/PATHS.md`）。

## 本仓落点

| 类型 | 权威位置 |
|---|---|
| Skill 流程 | `skills/*/SKILL.md` + `docs/uo-*-workflow.md` / `docs/tg-*-workflow.md` |
| Prompt 布局 | `prompts/README.md` |
| 子代理模板 | `prompts/init/references/tpl_*.md` |
| Agent schema | `agents/references/` |
| 可写面 | `spec/ownership.yaml`（UO）；TG 见 `skills/PATHS.md` UO 边界 |
