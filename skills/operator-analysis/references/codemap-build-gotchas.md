# UO CodeMap Build — Gotchas

Agent 规则。假编译环境、补头、prelude 由 engine 做，不要在本文件里复述实现。

- **确定性提取优先**：未闭合项记入 `unresolved.yaml`；不要用 LLM 补进正式 `.uo`。调查走 `/uo-investigate`。
- **范围不由人工确认文件清单**：operator + arch 给定后，prepare 用 Clang include closure 建范围；失败记 blocker。
- **Clang 是权威，regex 不是**：regex 只作引导；Clang 成功后替换，不是并集。
- **发现 common ≠ 消费 common**：共享头进范围后必须按范围成员走，不得按算子名丢掉。
- **禁止跳过编译验证**：产品路径禁止测试开关绕过探针。
- **staging ≠ canonical**：正式 `.uo` 只由 commit 写入。
- **禁止命名闭合**：blocker 不得因变量名相似、文件邻近而关闭。
- **跨层边必须有证据**：Host→Tiling→Kernel 边缺少 source span 时保持 unresolved。
- **BuildVariant 混用**：不同 architecture / 编译宏下的符号不得并进同一无身份。
- **局部变量生命周期**：保存-修改-恢复里，临时写回不是最终 defining site。

## 探针 / include 失败时

出现 `clang_probe_unclean`、`SCOPE_VALIDATE_BLOCKED`，或探针报缺头文件时：这是 **include 路径与当前 CANN 树没对齐**，不是官方包缺文件，也不是算子图上的 `unknown`。

`CANN_ENV_NOT_READY` 只表示 **cann_root 没配上或目录不像 CANN**（没有 `cann-asc-devkit/` / `cann-metadef/` / `{host}/asc`）。配好根目录后，prepare **不得**再因某个硬编码相对路径（例如 `asc/impl/include`、`tuple.h`）失败。官方 `.run` 不缺这些头；`asc/impl/include` 是 clang shim，engine 会尽量自动建。

1. **先确认 cann_root**。`UO_CANN_ROOT` / `_cann/pkg` / 官方 `ASCEND_HOME_PATH` 指向真实 CANN 即可。
2. **等 prepare 的 include_heal** 自动补 `-I`，写入 `uo/summary/build_context_extras.yaml`。不要手改算子源码、不要假造缺失头。
3. **脚本仍找不到**：workflow 进入 `heal`。`propose_include_heal` 只写 staging；`heal_promote` 校验后追加 extras。不要手改 extras，不要改共享 `spec/build_context.yaml`。
4. **不要**把 `ascendc/include/basic_api` 加成 kernel 主 include（相对路径会解析错）。
5. **不要**把 CANN / 共享头残差当成算子错误；不要把 `RegTensor` / `VecReg` 再 stub 一遍。
