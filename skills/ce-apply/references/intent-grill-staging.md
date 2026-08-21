# Intent grill staging

本步草稿只写当前 action 目录。确认存在后进入计划草稿，不 promote 成 yaml。

路径：

```text
<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/intent_grill/staging.md
```

也可拆成 `parts/*.md`。不要写 `staging.yaml`。

建议小节：

- 范围
- 不做的事
- 测试内容（给 `/tg-plan` 读，不要编码成 CE yaml）
- 未决决策（带推荐答案）
- 侧别：kernel / tiling / host / mixed

超时或中止前，已用插件 `pilot_cli` `uo-query` 查到的结论仍须写进最终消息。
