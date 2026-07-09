# Human Review UX (chat-first)

强制人工审阅闸门：**Phase 0.5 / 3.5**（以及 uo-query 缺 KB）。  
**禁止**在 OpenCode / Cursor agent 里跑会抢 stdin 的交互弹窗（↑↓ raw 键盘模式会导致聊天框无法输入）。

## 正确流程（默认）

1. 在聊天里写完审阅摘要。
2. 打印选项列表（可跑脚本，但**不要** `--interactive` / `--arrows`）：

```powershell
python "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate <gate>
```

默认行为：只打印菜单并退出（`UO_REVIEW_DECISION=pending`），**不阻塞、不抢键盘**。

3. **STOP**，等用户在**聊天输入框**回复，例如：
   - `continue`
   - `1`
   - `manual_supplement: 只看 arch35`
   - `dispatch_subset: K_TASK_001,K_TASK_002`

4. 收到用户文字后，用 `--decision` 落盘（不要再开交互弹窗）：

```powershell
python "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate <gate> --decision continue
python "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate <gate> --decision manual_supplement --notes "只看 arch35"
python "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate kernel_dispatch --decision dispatch_subset --approved-task-ids "K_TASK_001,K_TASK_002"
```

5. 读取 `UO_REVIEW_DECISION=...` 与对应 `*_decision.json`，再继续 workflow。

`<gate>`：

| Phase | `--gate` |
|---|---|
| 0.5 Macro Scope | `macro_scope` |
| 3.5 Kernel Dispatch | `kernel_dispatch` |
| uo-query 找不到 KB | `query_missing_kb` |

## 用户可回复的选项

每个闸门最后一项仍是 `manual_supplement`（手工补充）。  
补充内容写在同一条消息里即可：`manual_supplement: <内容>`。

## 可选：真实本地终端

仅当用户明确要求、且在独立终端（非 agent 工具 shell）时：

```powershell
python .../review_checkpoint.py ... --gate macro_scope --interactive
python .../review_checkpoint.py ... --gate macro_scope --arrows
```

**Agent 默认禁止使用 `--interactive` / `--arrows`。**

## 禁止

- 禁止 agent 启动会 `input()` / raw 键盘阻塞的审阅弹窗
- 禁止只贴选项却不告诉用户“请在聊天里回复选项名”
- 禁止替用户默认 `continue`
- 禁止 Phase 3.5 缺少 family/tiling 全貌时放行
