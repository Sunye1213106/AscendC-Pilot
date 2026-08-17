# TG Init Audit — 确定性引擎闭清单

由 **deterministic-tg-engine** 的 `init_audit` Action 执行。不派子代理、不改契约、不重绑、不发明新状态名。

权威 schema：`agents/references/init-audit-schema.md`  
门禁消费者：`init_status.require_audit_pass`（只认顶层 `status: pass|fail`）。

## 必读产物（相对 TG root）

- `init/` 与 `realization/` 下合同、绑定、完整性相关 yaml
- 若存在 `init/test_repo_contract.yaml`：核对 `kind`、schema、findings；测试仓缺口记 `warnings`，不要因此把 tilingkey 全覆盖 audit 写成 fail
- UO 就绪指纹（若 context 给出路径）
- **禁止**臆造 checklist id；必须覆盖 `TILINGKEY_AUDIT_CHECKLIST_IDS` 全量：
  - `tilingkey_contract`
  - `declared_set_nonempty`
  - `binding_inventory`
  - `host_view_aligned`
  - `graph_fingerprint`
  - `integrity_gate`

## 判定规则（full_coverage / tilingkey_full_coverage）

1. **顶层 `status` 只能是 `pass` 或 `fail`**。禁止 `conditional_pass`，禁止嵌套 `verdict.status` 代替顶层 status。
2. 每个 required id 写一条 `checks[]`：`status: pass|fail` + 一句 `detail`。
3. 任一条 required check 为 `fail`，或存在真实 blocker → 顶层 `status: fail`，`blockers` 列出可处置项。
4. 全部 required check 为 `pass` 且无真实 blocker → 顶层 `status: pass`，`blockers: []`。
5. **空 `reads` / 空 `exactness` 在确定性全覆盖模式下不是 blocker**。host-view inventory 允许这些字段为空；不得因此写 `fail` 或塞进 `blockers`，也不得因此要求 human_required。可写入 `warnings`（非阻塞）。
6. `warnings` 仅非阻塞说明；不得用 warning 顶替 fail。

## 输出合同

写入 `init/audit_report.yaml`：

```yaml
version: 1
status: pass   # 或 fail —— 仅此二者
checked_at: <iso>
op_name: <op>
checks:
  - id: tilingkey_contract
    status: pass
    detail: "..."
  # ... 其余 5 个 id ...
blockers: []
warnings: []
```

禁止：

- `status: conditional_pass`
- `verdict: { status: ... }` 作为唯一 status 来源
- 缺 checklist id
- 把空 reads/exactness 写成 blocking gap
