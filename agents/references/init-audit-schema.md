# tg-init-audit — `init/audit_report.yaml` schema

路径（装机后）：`$PLUGIN_ROOT/agents/references/init-audit-schema.md`  
清单权威：`$PLUGIN_ROOT/skills/testcase-generation/capabilities/tg-init-audit/METHOD.md`  
执行方：`deterministic-tg-engine` / Action `init_audit`（不是 LLM 子代理）。

`checks[].id` **MUST** 覆盖 `resolve_policy.TILINGKEY_AUDIT_CHECKLIST_IDS` 全量  
（`checklist=tilingkey`；旧 CSV closure 清单已移除，不得再要求任何旧 CSV checklist id）。

Live gate `audit_pass` / `init_status.require_audit_pass(..., checklist="tilingkey")` 只认下列 id：

```yaml
version: 1
status: pass | fail
checked_at: <iso>
op_name: <op>
checks:
  - id: tilingkey_contract
    status: pass | fail
    detail: "tilingkey contract skeleton present and well-formed"
  - id: declared_set_nonempty
    status: pass | fail
    detail: "declared TilingKey set is nonempty"
  - id: binding_inventory
    status: pass | fail
    detail: "host binding inventory covers declared keys"
  - id: host_view_aligned
    status: pass | fail
    detail: "host view aligns with binding inventory"
  - id: graph_fingerprint
    status: pass | fail
    detail: "graph fingerprint matches current KB/product"
  - id: integrity_gate
    status: pass | fail
    detail: "integrity gate artifacts present"
blockers: []
warnings: []
next: "acp next"
```

warn 仅允许非阻塞说明；任一 required id 为 `fail` → `status: fail`，不得进入 `human_confirm` finalize。

**全覆盖确定性模式**：host-view 绑定中空的 `reads` / `exactness` **不是** blocker，不得因此 `fail`
或写入 `blockers`，也不得发明 `conditional_pass` / 嵌套 `verdict.status`。

恢复路径（失败时）：`/uo-init` 产出定稿 `.uo` → `/tg-init` 重跑 contract/bind/gate → AskQuestion 后 `human_confirm --finalize`。  
禁止引导已删除的 CSV closure / merge 动作。
