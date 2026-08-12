# UO CodeMap Build — Gotchas

- **确定性 frontend/pass 优先**：LLM 只消解 `unresolved.yaml` 里显式 blocker；不得重做 Clang/extract。
- **范围不由人工确认文件清单**：用户给定 operator+arch 后，prepare 用 Clang include closure 建 authoritative Source Scope；失败记 blocker。
- **Clang 是权威，regex 不是**：regex shared 仅作 bootstrap/诊断；Clang 成功后替换（非 union）。`clang_scope_status!=complete` → `SCOPE_CLANG_CLOSURE_INCOMPLETE`。
- **发现 common ≠ 消费 common**：ScopeSet 含 SHARED 后，walk 必须用 scope 成员判断，禁止裸 `op_needle` 丢掉共享头。
- **禁止 decision=yes 绕过编译验证**：测试仅允许 `UO_TEST_ALLOW_UNVERIFIED_SCOPE=1`。
- **无人工 scope 确认**：Clang include closure + probe 机检即 `scope_confirmed`；`scope_receipt` 认 `action_id=scope_confirmation`（机检收据，勿写成父 Action `prepare`）。
- **scope_receipt 必须进 complete/phase/action gates**：否则 `passed_gates` 不记该门，`scope_confirmed` 义务在 complete 时仍开放（ses_00bf）。
- **staging ≠ canonical**：resolve 只写 staging；canonical IR 由 harness merge / commit。
- **禁止命名闭合**：blocker 不得因变量名相似、文件邻近而关闭。
- **跨层边必须有证据**：Host→Tiling→Kernel 边缺少 source span / evidence_ref 时保持 unresolved。
- **BuildVariant 混用**：不同 architecture / 编译宏下的符号不得并进同一无身份。
- **局部变量生命周期**：保存-修改-恢复模式中，临时写回不是最终 defining site。
- **Replay 反驳规则时撤销该规则**，不要降权后继续保留错误边。

## Clang 探针 / include 失败时（给 Agent）

当出现 `CANN_ENV_NOT_READY`、`clang_probe_unclean`、`SCOPE_VALIDATE_BLOCKED`，或探针 samples 含 `file not found` / 头文件相对路径解析失败时：

1. **先环境**：`acp doctor`。确认 `cann_layout=ok`（需要解包后的 `_cann/pkg` / `UO_CANN_ROOT`，不是只设了 `ASCEND_HOME_PATH`）。
2. **再对照官方编译文件改 BuildContext**（允许改 Pilot 仓内 harness，不是算子 `.ascendc-pilot` IR）：
   - 算子仓 / monorepo：`build.sh`、`**/CMakeLists.txt`（尤其 UT / ST 里 `target_include_directories`、`asc/include`、`asc/impl/*`）。
   - Pilot 真值：`engines/understand-operator/spec/build_context.yaml`（host/kernel `-I` 列表）。
   - 以官方 include 顺序与路径为准补齐 / 纠正；改完后清 probe 缓存或设 `UO_TU_CACHE=0`，再 `retry_failed_action` / 重跑 prepare。
3. **已知陷阱**：不要把 `ascendc/include/basic_api` 当作 kernel 主 `-I`——会把 `../../../../include/utils/std/tuple.h` 解析到错误的 `impl/include`（缺文件 → fatal）。官方路径以 `asc/include`、`asc/impl/basic_api`、`asc/include/utils/std`、`asc/impl/utils/std/{tuple,type_traits}` 为主；`ascendc/include/highlevel_api` 可保留。
4. **判洁口径**：探针以算子源码错误 + fatal 为准；CANN 头内 bisheng residual（如 `vector_u64`）不单独构成 `clang_probe_unclean`。
