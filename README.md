# AscendC Agent Harness

面向 **Ascend C 自定义算子** 的统一 Agent 套件：Harness 控制面 + UO 知识库 + TG 测例生成。

| 层 | 作用 |
| --- | --- |
| [harness/](./harness/) | 唯一控制面：状态、门禁、路由、Context、记忆 |
| [engines/uo/](./engines/uo/) | Understand Operator 领域引擎 |
| [engines/tg/](./engines/tg/) | Testcase Agent 领域引擎 |
| [skills-src/](./skills-src/) · [prompts-src/](./prompts-src/) · [agents-src/](./agents-src/) | 组合式业务源（Policy/Capability/Action/Prompt/Agent） |
| [generated/](./generated/) | Composer 宿主产物（可丢弃，安装前重生成） |

支持安装到 **OpenCode / Codex / Cursor**。

---

## 功能一览

| 命令 | 功能 |
| --- | --- |
| `/uo-init` | 建 KB（环境准备 → 范围确认 → 结构抽取 → 语义闭合 → 导出与校验 → 产物审查） |
| `/uo-query` | 定稿后只读问答 |
| `/uo-update` | 增量刷新 KB |
| `/uo-code-review` | 基于 KB 的缺陷/功能审查 |
| `/tg-init` | 测项合同与绑定 → 人工确认 |
| `/tg-plan` | 覆盖规划与人工批准 |
| `/tg-solve` | Z3 求解 → CSV 投影 |

用户可见阶段名使用中文；禁止「Phase 0」表述。控制面说明见 [docs/overview/workflows.md](./docs/overview/workflows.md)。

本地统一产物：

```text
<算子仓>/.ascendc-agent/{uo,tg,memory,runs,context,state}/
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

### `/tg-init` 前置条件

合同构建需要**测试脚本 / CSV 消费端目录**（用于动态抽取表头与读取逻辑），任选其一：

```powershell
# 环境变量
$env:ASCENDC_TEST_SCRIPT_ROOT = "<算子仓>/tests"
# 或 harness 上下文
# context/harness_params.yaml → test_script_root / csv_consumer_root
```

缺失时 `contract_build` 会明确失败：`TEST_SCRIPT_ROOT_REQUIRED`。

完整运行环境 ≠ Plugin 安装成功：

| 检查项 | 说明 |
| --- | --- |
| `harness doctor` | Composer/Agent、Z3、CBM MCP、consumer root 提示 |
| CBM MCP | 见 [docs/cbm-mcp-setup.md](./docs/cbm-mcp-setup.md)；未配置时 UO 源码证据能力降级 |
| Z3 | `pip install -e "./engines/tg[solver]"`；否则 `/tg-solve` 不可用 |