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
- 调用 `harness advance` / `complete` / 跳阶段

## 输出

写 `.ascendc-agent/tg/realization/semantic_bind_patch.yaml`：

```yaml
action: bind
bindings:
  - candidate_id: <from bundle>
    key_id: KEY_...
    expr: "..."
    evidence:
      - file_path: ...
        line: ...
```

然后运行领域 API `apply_semantic_bind_patch`（或等价脚本入口），确认
`binding_lexicon.yaml` 有实质变化且 `bind_progress` 可过。

完成后执行：`harness run-action semantic_bind --finalize`
