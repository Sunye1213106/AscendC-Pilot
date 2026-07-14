# Human Review UX — selectable UI (Plan-style)

强制人工审阅闸门：**Phase 0.5 / 3.5**（以及 uo-query 缺 KB）。

**只有这些闸门**才允许：暂停（STOP）+ 在对话里附上可供人判断的审阅摘要。  
普通 phase（含 Phase 1 宏观边界完成后）**禁止**输出审阅式摘要或假装等人。

目标交互与 Cursor Plan / OpenCode `question` 一致：

- **↑/↓ 或点击选择**固定选项
- **最后一项支持自由输入**（手工补充）
- 选完后 agent 用 `--decision` 落盘，再继续

**禁止**再用会抢 stdin 的 Python raw 键盘弹窗（`--arrows` / 阻塞 `input()`）。那会让聊天框无法打字。

## 优先：原生选择 UI

### OpenCode

使用内置 **`question`** 工具（permission 需 allow）。用户可：

- 用键盘/鼠标选固定选项
- 或输入 custom answer（对应手工补充）

示例问题结构：

```text
header: Phase 0.5 Macro Scope
question: 请确认 Phase 1 探索范围后如何继续？
options:
  - continue — 按当前范围进入 Phase 1
  - revise — 调整 include/exclude/skip 后重审
  - stop — 停止 workflow
  - manual_supplement — 手工补充（选此项后请输入补充内容）
```

若用户选了 `manual_supplement` 或提交了 custom text：把文本当作 `notes`。

### Cursor

若环境提供 **AskQuestion**（或同等选择 UI）：

- 单选固定选项
- 最后一项必须是：`手工补充（我来输入）` / `Something else (I will type it)`
- 不要在同一题再放另一个 “Other”

若 AskQuestion 不可用：在聊天里给出同样选项，并明确写「请回复选项名；选手工补充时在同一条消息写内容」。

## 落盘（两种 UI 选完后都要做）

```powershell
python "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate <gate> --decision <choice> [--notes "..."] [--approved-task-ids "..."]
```

`<gate>`：

| Phase | `--gate` |
|---|---|
| 0.5 Macro Scope | `macro_scope` |
| 3.5 Kernel Dispatch | `kernel_dispatch` |
| uo-query 找不到 KB | `query_missing_kb` |

可选：先打印菜单备忘（不阻塞）：

```powershell
python "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate <gate>
```

## 各闸门选项（最后一项 = 可输入）

### macro_scope

1. `continue`
2. `revise`
3. `stop`
4. `manual_supplement` ← **支持输入**（范围/跳过分支等）

### kernel_dispatch

1. `dispatch_all`
2. `dispatch_subset` ← 选后需提供 task_id（可在 custom 输入里写）
3. `revise`
4. `stop`
5. `manual_supplement` ← **支持输入**

### query_missing_kb

1. `init`
2. `source`
3. `stop`
4. `manual_supplement` ← **支持输入**（KB 路径 / op-name）

## Agent 步骤（必须）

1. **仅在闸门 turn**：展示审阅摘要（3.5 必须含全量 tiling/family）
2. 调用原生 `question` / AskQuestion（最后一项可输入）
3. **STOP** 等待 UI 返回
4. `--decision` 写入 `*_decision.json` / review yaml
5. 按决策继续；`manual_supplement` / `revise` 吸收 notes 后可再次提问

## 禁止

- 禁止在非闸门 phase（尤其 Phase 1 结束后）向对话输出 Boundary/IO/open_questions 等「给人看的审阅材料」
- 禁止 Python `--arrows` / `--interactive` 作为 OpenCode/Cursor 默认路径
- 禁止替用户默认 `continue`
- 禁止只贴静态列表却不唤起可选择 UI（有 `question`/AskQuestion 时）
- 禁止在未获得明确 `continue` 时进入下一阶段
