# AscendC-Pilot

面向 AscendC 算子理解、测试生成、代码工程辅助的 AI Agent 平台。

```text
AscendC-Pilot
├── Understand Operator   (uo_init)
├── Testcase Generation
└── Code Engineering
```

| 层 | 作用 |
| --- | --- |
| [pilot/](./pilot/) | Pilot 控制面：状态、门禁、路由、Context、记忆 |
| [engines/understand-operator/](./engines/understand-operator/) | UO 唯一引擎（包 `uo_init`：init / update / query） |
| [engines/testcase-generation/](./engines/testcase-generation/) | TG |
| [engines/code-engineering/](./engines/code-engineering/) | CE（`/ce-review`） |
| [skills/](./skills/) · [prompts/](./prompts/) · [agents/](./agents/) | 组合式业务源 |
| [generated/](./generated/) | Composer 宿主产物 |
| [docs/](./docs/README.md) | 文档：design / fag / debug（归档见 docs/_archive） |

支持安装到 **OpenCode / Codex / Cursor**。

---

## 功能

| 命令 | 功能 |
| --- | --- |
| `/uo-init` | 建 KB（prepare → scope → extract → normalize → export → review） |
| `/uo-query` | 定稿后只读问答 |
| `/uo-update` | 增量刷新 KB（`uo_init.update`） |
| `/tg-init` / `/tg-plan` / `/tg-solve` | 测项合同 / 规划 / Z3 求解 |
| `/ce-review` | 基于 UO KB 的代码审查 |

产物：`<算子仓>/.ascendc-pilot/{uo,tg,ce,memory,runs,context,state}/`

---

## 安装

```powershell
pip install -r requirements.txt
pip install -e "./pilot"
pip install -e "./engines/understand-operator"
pip install -e "./engines/testcase-generation[ml]"
./install.ps1 opencode   # 或 cursor / codex
acp doctor
```

源码导航由仓内 UO 图与 confirmed-scope 的有界源码读取提供；安装器不依赖外部代码索引服务。

---

## CLI

```powershell
acp doctor
acp route /uo-init
acp uo-query --help
```

完成态只认 `acp complete`。

---

## 文档

- [docs/README.md](./docs/README.md)
- [docs/design/architecture.md](./docs/design/architecture.md)
- [docs/design/tilingkey-closure-agent.md](./docs/design/tilingkey-closure-agent.md)
- [docs/debug/open-problems.md](./docs/debug/open-problems.md)
