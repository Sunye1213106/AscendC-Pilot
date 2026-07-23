# Task: tg/semantic-bind

你是 `tg-semantic-bind` producer。只处理当前 Action 的 binding gaps。

## 允许读取

- `.ascendc-agent/tg/realization/llm_bind_prompt_bundle.yaml`
- `.ascendc-agent/tg/realization/binding_inventory.yaml`
- `.ascendc-agent/tg/realization/binding_gaps.yaml`
- `.ascendc-agent/tg/realization/unresolved.yaml`
- bundle 内给出的源码窗口路径（仅这些文件）

## 禁止

- 全仓搜索或打开未在窗口中的源码
- 发明 CSV 列名 / KEY id / 表达式
- 空 accept、无 candidate_id 的批量升级
- 直接修改 `binding_lexicon.yaml`（由 finalize 确定性应用）
- 调用 `harness advance` / `complete` / 跳阶段

## 输出

写 `.ascendc-agent/tg/realization/semantic_bind_patch.yaml`（必须带本次 prepare 的 nonce）：

```yaml
action: bind
prepare_nonce: <from Runtime Bundle / binding_inventory.harness_prepare.nonce>
bindings:
  - candidate_id: <from bundle>
    key_id: KEY_...
    expr: "..."
    evidence:
      - file_path: ...
        line: ...
```

然后执行：`harness run-action semantic_bind --finalize`

Finalize 会调用 `apply_semantic_bind_patch`、校验 fingerprint / Output Contract / `bind_progress`。
若仍有 unresolved gaps，保持 `ready_for_llm`，不得宣称完成。
