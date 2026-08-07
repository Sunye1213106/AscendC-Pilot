# 产品修改工作准则（摘要）

> Cursor 每次对话自动加载：`.cursor/rules/product-change-principles.mdc`（`alwaysApply: true`）。  
> 文档索引：`docs/README.md`。组合式分层：`docs/skill-and-prompt-principles.md`。

## 核心口诀

**公共优先 · 多复用 · 校验进共享 · Prompt 只引用 · 禁 Host 代写救场**

## 五条

1. **全局规则进 Policy / Capability / 共享模块**，禁止只改个别 Action skill 导致系统碎片化。  
2. **先搜再写**：扩展现有 helper / lease / gate / compose，不平行发明第二套证据或读码路径。  
3. **合同与韧性在产品层**：finalize/sanitize/lease 不变量；不靠「再写一段 CRITICAL 教模型」。  
4. **分层落点清晰**：证据→`evidence`+`source_evidence`；源码导航→`source-navigation`；权限→`lease`；本步字段→该 Action 合同。
5. **改完 compose + 单测 +（需要时）更新 `docs/`**；安装侧 `refresh-opencode.ps1` 后重启才算生效。

## 反模式（禁止）

- 只在单个 Action prompt 里写「高置信必须源码比对」，公共 Policy 不改。  
- Primary `Edit uo/ir/**` 修子代理坏 YAML。  
- rework 时 stub 前后夹诊断长文 / 新开第二个 session。  
- 每个 Action 各自 `safe_load` / 各自证据校验、宽严不一。  
- 把已删除旧引擎的行为写进新 `uo-init` 文档。
