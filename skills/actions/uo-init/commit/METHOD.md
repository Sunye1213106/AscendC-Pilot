# commit

确定性写入权威 CodeMap 产品：

```text
.ascendc-pilot/uo/<op>.<arch>.uo
```

输入来自当前 compiler/pass 已产生并通过校验的事实与 semantic patch。兼容层数据可以作为 engine 内部迁移输入，但不能作为对 Agent 暴露的第二 authority，也不能要求模型维护额外 KB/YAML 投影。

本 Action 不调用 Agent、不绑定 task prompt。
