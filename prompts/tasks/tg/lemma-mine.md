<task>
对本轮 Round Analysis 给出的源码引理线索做证明或反驳（轮内 claim，不是搜完后的清理）。
</task>

<input>
- Targets: `<TARGET_IDS_OR_FILES>`
- Project: `<PROJECT_ROOT>`
- UO: `<UO_ROOT>`
- TG: `<TG_ROOT>`
权威闭合证据只有 Host Replay（R）与经审查的源码引理（E）。
</input>

<delta_constraints>
1. 只处理 closed lead pack 中的线索，禁止发明新 lead；有 companion evidence pack 时一并使用。
2. 优先对照最新一轮 Host `refuse` / rewrite 观察与 `round_analysis.yaml` 模式。
3. 主动寻找反例；闭合所需 proof obligations。
4. 不得把 missing / search failure / replay reject 单独升级为 exclusion。
</delta_constraints>

<output>
每个候选给出 `PROVED` | `REFUTED` | `INSUFFICIENT`，并附源码窗口证据。
只写入本 Action 的 `parts/` 草稿，不要写正式 closure IR。
</output>
