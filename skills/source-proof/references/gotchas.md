# Source Lemma Proof — Gotchas

- **命题必须可反驳**：没有明确 antecedent→consequent 的“感觉正确”不是引理。
- **证据必须可定位到 span**：缺 file/line 的证书无效；禁止 free_repo_search 后无出处引用。
- **不得写 excluded 集**：producer 只写 staging certificate；apply 由 deterministic 路径完成。
- **Referee 独立上下文**：自审自批无效；review.yaml 不得由 lemma producer 填写。
- **Replay 反驳 → 撤销规则**：被 Host 反例打掉的引理要撤销，不是降级继续用。
- **宏/模板条件保留 compile-time provenance**：把运行时观察当成必然条件会假证。
- **Host/Kernel 条件经 TilingKey 映射**：跳过 TemplateArg 的跨层蕴含通常错误。
