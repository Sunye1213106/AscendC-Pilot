# AscendC-Pilot

AscendC-Pilot 是面向 **AscendC 算子开发的 AI Agent Harness 与代码知识基础设施**。

它通过 Clang 和 CANN 编译环境分析 AscendC 源码，构建 **Operator CodeMap**，并在此基础上支持测试覆盖、代码审查和影响分析。

* **UO**：构建和查询 Operator CodeMap
* **TG**：把 CodeMap 变成 `init.yaml` / `plan.md` / `worklog.md` 与脚本可读的 cases 表
* **CE**：基于跨层关系做代码审查与影响分析

```text
AscendC Source → UO → Operator CodeMap → TG → Coverage
                                  └────→ CE → Review / Impact
```

> 项目当前处于 **experimental** 阶段。

---

# 安装

要求 Python 3.10+ 和 **OpenCode 1.18**（V1 plugin API：`~/.config/opencode/plugins/*.ts` 自动加载）。可编辑 pip 安装绑定本仓库，**不要装完删除 clone**。

建议先建虚拟环境，再装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts/dev/check_install.py
```

Linux 若没有 `python` 命令，用 `python3`。Windows 若 ExecutionPolicy 拦截脚本：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 opencode
```

接入 Host（推荐 OpenCode）。先**完全退出 OpenCode**，再运行：

```powershell
.\install.ps1 opencode
```

```bash
./install.sh opencode
```

然后：

```bash
python -m ascendc_pilot doctor --host opencode
```

完全退出再打开 OpenCode，Tab 切换到 **AscendC-Pilot**。也支持 `cursor` / `codex`。完整环境见 [Installation](docs/getting-started/installation.md)。开发迭代可用 `.\refresh-opencode.ps1`（先卸载再安装）。卸载：`.\uninstall.ps1` / `./uninstall.sh`。

---

# 快速开始

在**目标 AscendC 算子仓库**中打开 OpenCode，Tab 切换到 AscendC-Pilot，然后：

```text
帮我为当前算子建立 CodeMap
```

或：

```text
/uo-init
```

Architecture **对 `/uo-init` 和 `/uo-update` 强制**：选项从当前算子仓的 `op_host/arch*` / `op_kernel/arch*` 中发现；缺一会要求从发现的架构中选择，不会使用固定默认值。TG / CE 从已有 `.uo` 取 arch。产物在：

```text
<operator-repo>/.ascendc-pilot/
```

更多步骤见 [Quick Start](docs/getting-started/quickstart.md)。

---

# 常用入口

| 目标 | 命令或说法 |
| --- | --- |
| 建立 / 更新 CodeMap | `/uo-init`、`/uo-update` |
| 查询或调查 gap | `/uo-query`、`/uo-investigate` |
| 生成测试覆盖 | `/tg-init` → `/tg-plan` → `/tg-solve` |
| 自己有需求：计划并改码 | `/ce-plan` → `/ce-apply` |
| 已有 diff / PR：只读审查 | `/ce-review` |
| 会话交接 | `/handoff` |

自然语言示例：

```text
这个 TilingKey 是怎么决定的？
帮我补齐当前没有覆盖的 TilingKey
帮我检查当前修改会影响哪些 Host、Tiling 和 Kernel 路径
```

通常不需要记住全部命令，直接告诉 Agent 目标即可。

---

# 文档

* 入门：[Installation](docs/getting-started/installation.md) → [Quick Start](docs/getting-started/quickstart.md) → [ACP 工具使用](docs/getting-started/acp-tools.md)
* 模块：[UO](docs/modules/uo.md) · [TG](docs/modules/tg.md) · [CE](docs/modules/ce.md)
* 设计：[Architecture](docs/architecture/overview.md) · [Agent Runtime](docs/architecture/agent-runtime.md) · [Artifacts](docs/architecture/artifacts-and-authority.md)
* 完整导航：[docs/README.md](docs/README.md)

---

# 开发

```bash
pytest
python scripts/check_docs.py
python scripts/generate_reference_docs.py
```

扩展见 [Extension Guide](docs/development/extending.md)。仓库布局见 [Repository Layout](docs/reference/repository-layout.md)。

```text
adapters/   Host 接入
agents/     Agent identity
engines/    UO / TG / CE
pilot/      Workflow、Action、Gate、CLI
skills/     Agent skills
docs/       Documentation
```

---

# License

当前仓库尚未声明 License。
