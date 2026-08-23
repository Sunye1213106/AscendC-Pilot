<task>
结合 plan_scope 回答与 plan_fuse YAML，写 plan.md 三节散文。不要写覆盖模型，不要 Write。
</task>

<input>
- Scope answer: Host 注入的 plan_scope 自然语言
- Fuse YAML: Host 注入的 plan_fuse 覆盖模型
- Init: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
</input>

<output>
最终消息只交三节：

## 测什么
## 覆盖什么
## 怎么判定

禁止交 YAML。禁止 Write `tg/plan.md`。promote 会把这三节与 fuse YAML 拼成正式 plan.md。
</output>
