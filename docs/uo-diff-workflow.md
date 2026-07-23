# `/uo-diff` 工作流

`/uo-diff` 用于在已有 KB 上给出相对上次 revision 的**只读**变更摘要。不写 KB，也不写持久 `diff/` PR 包。

实现方式可概括为：

> 以 manifest revision 与当前 git 对比，结合 confirmed 文件范围做变更检测，输出给人阅读的中文摘要；需要时可用 MCP 定位符号，但不落盘。

整体原则是：

* 只读边界严格，不修改 `$UO_ROOT`；
* 需要可消费 `diff/**` 时应引导 `/uo-update`，本流程不越权生成；
* 本 skill 刻意不合并进 `uo-update`，以保持职责清晰。

---

## 使用条件

| 使用 `/uo-diff` | 不使用 `/uo-diff` |
| --- | --- |
| 「相对上次 KB 改了什么」的快速摘要 | 需要可消费的 `diff/**` → `/uo-update` |
| | 首次建库 → `/uo-init` |
| | 缺陷 / 需求审查 → `/uo-code-review` |

编排入口为 `skills/uo-diff/SKILL.md`。

变量：`SCRIPT_DIR=$PLUGIN_ROOT/engines/uo/uo/scripts`；`UO_ROOT=$PROJECT_ROOT/.ascendc-agent/uo`。

---

## 核心功能文件入口

| 角色 | 路径 |
| --- | --- |
| Skill | `skills/uo-diff/SKILL.md` |
| 检测脚本 | `uo/scripts/detect_kb_changes.py` |
| 可选源码定位 | `prompts/common/cbm.md` |

---

# Phase 1：校验与检测

## Step 1：校验 KB 存在

**关键文件**

* Skill：`skills/uo-diff/SKILL.md`

**执行内容**

检查 `$UO_ROOT` 是否存在。不存在时报告路径，建议 `/uo-init`，并 **STOP**。

---

## Step 2：执行变更检测

**关键文件**

* 脚本：`uo/scripts/detect_kb_changes.py`

**执行命令**

```powershell
python -X utf8 "$SCRIPT_DIR/detect_kb_changes.py" "$PROJECT_ROOT" `
  --op-name "$OP_NAME"
```

**执行内容**

依据 manifest revision 与当前 git，对 confirmed 文件做只读 diff。机制是 git diff，不是 AST。

**输入 / 输出**

输入为 KB 与 git 状态；输出为 stdout / 结构化变更列表。

---

# Phase 2：摘要输出

## Step 3：生成人读摘要

**关键文件**

* 可选已有产物：`$UO_ROOT/diff/change_set.yaml`
* 可选定位规则：`prompts/common/cbm.md`

**执行内容**

| 条件 | 动作 |
| --- | --- |
| 已存在 `$UO_ROOT/diff/change_set.yaml` | **只读**摘要该文件 |
| 否则 | 用 Step 2 的 detect 输出做简洁中文摘要 |

可选：对关键符号用 MCP 定位，仍不写盘。

---

## Step 4：结束

无持久 review 产物；不修改任何 KB / `diff/**`。  
若用户需要 PR 用的 `diff/` 包，引导 `/uo-update`。

---

# 正式产物

* 对话 / 终端中的变更摘要（可为空集）。

无必须落盘的正式文件。

---

# 禁止事项

* 写或覆盖 KB / `diff/**`；
* 安装 code-review-graph；
* 使用本地 CBM CLI；
* 把 `/uo-diff` 当作 update 流程。

---

# 质量标准

一次合格摘要应能说明：

1. 对比基线 revision；
2. 哪些 confirmed 文件发生变更；
3. 是否建议继续执行 `/uo-update`。

失败与门禁细则见 `skills/uo-diff/SKILL.md`。
