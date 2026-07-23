# AscendC Agent Harness

面向 **Ascend C 自定义算子** 的统一 Agent 套件：Harness 控制面 + UO 知识库 + TG 测例生成。

| 层 | 作用 |
| --- | --- |
| [harness/](./harness/) | 唯一控制面：状态、门禁、路由、Context、记忆 |
| [engines/uo/](./engines/uo/) | Understand Operator 领域引擎 |
| [engines/tg/](./engines/tg/) | Testcase Agent 领域引擎 |
| [skills/](./skills/) · [prompts/](./prompts/) · [agents/](./agents/) | 领域 Skill / Prompt / Subagent |

支持安装到 **OpenCode / Codex / Cursor**。

---

## 功能一览

| 命令 | 功能 |
| --- | --- |
| `/uo-init` | 建 KB（Phase0 → Extract → Resolve → Export → Review） |
| `/uo-query` | 定稿后问答 |
| `/uo-update` | 增量刷新 KB + `diff/` |
| `/uo-code-review` | Bug（CBM）+ 语义（KB） |
| `/tg-init` | 测试工具 + 定稿 KB → confirmed realization |
| `/tg-plan` | 覆盖规划（默认 L0+L1，可选 L2） |
| `/tg-solve` | Z3 → CSV |

本地统一产物：

```text
<算子仓>/.ascendc-agent/{uo,tg,memory,runs,context,state}/
```

Legacy `.understand-operator/<op>/` / `.testcase-generator/<op>/` →

```powershell
harness migrate-legacy <算子仓> --op-name <op>
```

---

## 安装

```powershell
pip install -r requirements.txt
pip install -e "./harness" -e "./engines/uo" -e "./engines/tg[solver]"
./install.ps1 opencode   # 或 cursor / codex
harness doctor
```

CBM： [docs/cbm-mcp-setup.md](./docs/cbm-mcp-setup.md)

---

## 质量门禁（tilingkey）

建库 Resolve 完成前必须通过：

```powershell
harness validate-key-gates <算子仓>
harness complete --project <算子仓>
```

禁止：跳过 `uo-key-resolve` triage、empty-only 假闭合、同文 bit-pack `reported` 空过审、跳过 `uo-confidence-review` 原因裁判。  
完成态只认 `harness complete`。

---

## 端到端

```text
/uo-init → /tg-init → --confirm → /tg-plan → approve → /tg-solve
```
