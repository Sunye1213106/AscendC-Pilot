                # 构建合同骨架

                ## Goal

                构建 TG CSV/合同骨架。

                ## Input Interpretation

                仅处理 `harness next` 提供的当前 unresolved / target 子集与上下文包。

                ## Domain Procedure

                1. 使用 capability `contract-building`。
2. 使用 capability `kb-query`。
3. 使用 capability `obligation-analysis`。
                4. 只处理当前 Action 指定的 ID 或文件。
                5. 按输出合同生成候选产物；证据不足保留 unresolved。

                ## Domain Decisions

                - 遵循已加载 Policy 与 Capability 硬限制。
                - 本 Action 特有分类/闭合规则见关联 task prompt（若有）。

                ## Output

                - 合同 id：`csv-contract-v1`
                - 不得写声明外路径。

                ## Cannot Decide

                - 证据不足 → unresolved / needs_human
                - 缺工具或 gate 前置 → 停止并回报 blocking reason

                本文件不得描述 Harness advance、complete 或其他阶段。
