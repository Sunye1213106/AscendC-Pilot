<task>
对照 include-heal unresolved 与真实 CANN/ops 树，写出建议的额外 -I 目录。
</task>

<context>
脚本 include-heal 已经搜过 cann_root / ops，仍有头文件找不到。本步只写草稿 YAML。确定性 `heal_promote` 会校验目录存在且落在 cann_root / ops 内，再追加到 extras。extract 通过 `apply_saved_extras` 把 extras 变成 clang `-I`。不要手改 extras 或共享 `spec/build_context.yaml`。
方法细节见打包 Skill `propose-include-heal`。
</context>

<instructions>
1. 读取 unresolved 清单与 `environment_capabilities.yaml` 的 cann.root。
2. 只读 cann_root / ops，定位真实头文件对应的 include 根。
3. 写本步草稿 YAML（host/kernel 目录列表 + evidence）。
4. 目录不存在或越界则不要写入；宁缺毋假。
</instructions>

<output>
只写本步 `propose_include_heal` 草稿 YAML。
不写 extras、不写 `spec/build_context.yaml`、不建 shim、不改算子源码。
</output>
