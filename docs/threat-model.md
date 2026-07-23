# 威胁模型（Harness 控制面）

## 声明

在 **AscendC Agent**（OpenCode `mode: primary`）内：

- Agent frontmatter：`bash: "*": deny` + `harness *: allow`
- Plugin `tool.execute.before` → `harness authorize`

可阻止**常规**越级（直调 `build_layered_kb.py` / `tg-solve`、乱写正式 IR/review）。

## 不能宣称的

以下**不是** OS 级禁止，仍可绕过软控制面：

- 用户 Tab 切回 Build / 其他 Agent
- 本机终端直接改 `.ascendc-agent/`
- UI 直接 @ subagent 且宿主未走 authorize

## 完成态仍硬

绕过路径**无法**合法获得 `status: passed`。正式完成只认：

1. Harness 签发的 Receipt  
2. Deterministic Checker / KEY gates  
3. `harness complete`

## 语言

- 机器字段（reason_code / ID / status）：英文  
- 用户可见文案（message_zh / reason / finding）：简体中文  
- **不**把「模型隐藏推理语言」写成可测验收项
