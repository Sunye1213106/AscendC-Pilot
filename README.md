# AscendC-Pilot

面向 AscendC 算子理解、测试生成、代码工程辅助的 AI Agent 平台。

```text
AscendC-Pilot

├── Understand Operator
├── Testcase Generation
└── Code Engineering
```

| 层 | 作用 |
| --- | --- |
| [pilot/](./pilot/) | Pilot 控制面：状态、门禁、路由、Context、记忆 |
| [engines/understand-operator/](./engines/understand-operator/) | Understand Operator（UO）领域引擎 |
| [engines/testcase-generation/](./engines/testcase-generation/) | Testcase Generation（TG）领域引擎 |
| [engines/code-engineering/](./engines/code-engineering/) | Code Engineering（CE）；当前实现 `/ce-review` |
| [skills/](./skills/) · [prompts/](./prompts/) · [agents/](./agents/) | 组合式业务源（Policy/Capability/Action/Prompt/Agent） |
| [generated/](./generated/) | Composer 宿主产物（可丢弃，安装前重生成） |

支持安装到 **OpenCode / Codex / Cursor**。

---

## 功能一览

| 命令 | 功能 |
| --- | --- |
| `/uo-init` | 建 KB（环境准备 → 范围确认 → 结构抽取 → 语义闭合 → 导出与校验 → 产物审查） |
| `/uo-query` | 定稿后只读问答 |
| `/uo-update` | 增量刷新 KB |
| `/tg-init` | 测项合同与绑定 → 人工确认 |
| `/tg-plan` | 覆盖规划与人工批准 |
| `/tg-solve` | Z3 求解 → CSV 投影 |
| `/ce-review` | 基于 UO KB 的代码审查（Code Engineering） |

本地统一产物：

```text
<算子仓>/.ascendc-pilot/{uo,tg,ce,memory,runs,context,state}/
```

---

## 安装

```powershell
pip install -r requirements.txt
pip install -e "./pilot"
pip install -e "./engines/understand-operator"
pip install -e "./engines/testcase-generation[solver]"
./install.ps1 opencode   # 或 cursor / codex
acp doctor
```

CBM： [docs/cbm-mcp-setup.md](./docs/cbm-mcp-setup.md)

---

## CLI

```powershell
acp --help
acp doctor
acp route /uo-init
acp route /tg-init
acp route /ce-review
```

完成态只认 `acp complete`。

---

## 端到端

```text
/uo-init → /tg-init → --confirm → /tg-plan → approve → /tg-solve
```

代码工程：

```text
/uo-init → /ce-review
```
