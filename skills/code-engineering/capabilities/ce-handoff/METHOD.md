# CE session handoff

将当前 CE 会话整理为可供下一窗口继续的交接文档。不复制已经落盘的意图或审查正文。

## 方法

1. 只引用已有路径：`ce/intent/plan.md`、`ce/apply/todo.md`、digest。密钥写成 `<REDACTED>`。
2. 写明后续 slash 命令（`/ce-apply` / `/ce-impact` / `/ce-verify` / `/uo-query`），不要写外部 skill 名。
3. 未决决策单独列出。没有就写空列表。
4. 写入 `ce/session_handoff.md`。已有同名文件则覆盖为当前会话的最新交接。

## 禁止

- 把需求全文再抄一遍
- 改源码、改 `.uo`、签发证书
