# UO CodeMap Build — Gotchas

- **确定性 frontend/pass 优先**：LLM 只消解 `unresolved.yaml` 里显式 blocker；不得重做 Clang/extract。
- **范围不由人工确认文件清单**：用户给定 operator+arch 后，prepare 用 Clang include closure 建 authoritative Source Scope；失败记 blocker。
- **Clang 是权威，regex 不是**：regex shared 仅作 bootstrap/诊断；Clang 成功后替换（非 union）。`clang_scope_status!=complete` → `SCOPE_CLANG_CLOSURE_INCOMPLETE`。
- **发现 common ≠ 消费 common**：ScopeSet 含 SHARED 后，walk 必须用 scope 成员判断，禁止裸 `op_needle` 丢掉共享头。
- **禁止 decision=yes 绕过编译验证**：测试仅允许 `UO_TEST_ALLOW_UNVERIFIED_SCOPE=1`。
- **无人工 scope 确认**：Clang include closure + probe 机检即 `scope_validated`；`scope_receipt` 认 `action_id=scope_validated`（机检收据，勿写成父 Action `prepare`）。
- **scope_receipt 必须进 complete/phase/action gates**：否则 `passed_gates` 不记该门，`scope_validated` 义务在 complete 时仍开放（ses_00bf）。
- **staging ≠ canonical**：resolve 只写 staging；canonical IR 由 harness merge / commit。
- **禁止命名闭合**：blocker 不得因变量名相似、文件邻近而关闭。
- **跨层边必须有证据**：Host→Tiling→Kernel 边缺少 source span / evidence_ref 时保持 unresolved。
- **BuildVariant 混用**：不同 architecture / 编译宏下的符号不得并进同一无身份。
- **局部变量生命周期**：保存-修改-恢复模式中，临时写回不是最终 defining site。
- **Replay 反驳规则时撤销该规则**，不要降权后继续保留错误边。

## Clang 探针 / include 失败时（给 Agent）

当出现 `CANN_ENV_NOT_READY`、`clang_probe_unclean`、`SCOPE_VALIDATE_BLOCKED`，或探针 samples 含 `file not found` / 头文件相对路径解析失败时：

这是 **CANN 包与 BuildContext 的问题**，不是算子图上的 `unknown`。**禁止**用 `UO_TEST_ALLOW_UNVERIFIED_SCOPE` 走产品路径。

1. **prepare 已自动 include-heal**：`scope_scan` 会从探针 / `#include` 抽出缺头文件名，在 `{cann_root}` 与 `{ops_root}` 定位，把对应目录补进 runtime `-I`（不改共享 yaml），写入 `.ascendc-pilot/<arch>/uo/summary/build_context_extras.yaml`，再重试 enrich。extract 经 `BuildContext.load` 自动合并 extras。独立调试：`python engines/understand-operator/tools/uo_heal_includes.py --op-dir <op> --arch-dir <arch> [--probe]`。
2. **仍 `file not found`**：先看 `candidates.yaml` 的 `include_heal.unresolved`。头文件不在解包树 → `acp doctor`，并对照算子仓 `CMakeLists.txt` / `target_include_directories` 修正 `engines/understand-operator/spec/build_context.yaml` 基线，清 probe 缓存后重试。禁止停下来问用户要不要绕过。
3. **已知陷阱**：不要把 `ascendc/include/basic_api` 当作 kernel 主 `-I`——会把 `../../../../include/utils/std/tuple.h` 解析到错误的 `impl/include`（缺文件 → fatal）。include-heal 会拒绝这条路径。官方路径以 `asc/include`、`asc/impl/basic_api`、`asc/include/utils/std`、`asc/impl/utils/std/{tuple,type_traits}` 为主；`ascendc/include/highlevel_api` 可保留。
4. **判洁口径**：探针以算子源码错误 + fatal 为准。诊断路径先 `Path.resolve()`，再看是否落在 `op_dir` 下；空 location、家族 `common/` / `3rd/`、CANN 头一律当共享残差，不单独构成 `clang_probe_unclean`。相对 include 的词法路径里常带着算子目录名（`op_kernel/arch22/../../../../3rd/...`），不要用 `op_needle in loc_file`。`TypeGet` / `ROUND` / `Mode` / `atomic_type_t` / `float32_t` 不是缺头，走 `spec/compat/bisheng_prelude.h`。SIMT 关键字 `__simt_callee__` / `__sync_noalias__` 与 `__aicore__` 一样 erase 成空。Catlass `3rd/template_linear_algebra` 的 `__forceinline__[aicore]` 由 prelude 关上 `CATLASS_DETAIL_MACROS_HPP`，映射到已 erase 的 `__aicore__`。算子 TU 上仍报 `unknown type name 'vector_*'` 时，先补 prelude，不要当语义缺口。prelude 已提供 packed `vector_s4x2` / `vector_u4x2` / `vector_s4` / `vector_u4`，以及与 bisheng `__clang_dpp_types.h` 对齐的 `enum class ROUND { R, A, F, C, Z, O, H }`。不要把 `ROUND` 写成匿名枚举常量（随后 `ROUND::…` 会报「不是 class/namespace/enumeration」）。不要 stub 全局 `RegTensor`/`VecReg`，也不要再引入会和 CANN 头撞车的 `TypeGet` 特化。改 prelude 后必须清 `.ascendc-pilot/<arch>/uo/cache/tu/*.probe.pkl`，cache key 不含 prelude 内容。
5. **跨家族 basename**：`include-heal` 会扫 `ops_root` 下各家族的 `common/`、`common/utils/`、`common/inc/`、`3rd/`（例如 ffn 引用 `mc2/common/utils/context_util.h`）。打分时的 `/test/` 惩罚只看相对 `ops_root`/`cann_root` 的路径，避免把 checkout 目录名 `TEST` 当成算子 `tests/`。`lib/matrix/matmul/X` 在目标文件已存在时改写为 `lib/matmul/X`；`acl/acl_base_mdl.h` 由 `spec/compat/acl/` 洞补。实体文件不在树里时保持 unresolved，禁止假 heal。
6. **没有 `*template_tiling_key.h`**：同目录还认 `*tilingkey.h` / `*_tiling_key.h`。多个头时跟当前 kernel 入口的 `#include`，不要按文件名字母序（`*_apt_tiling_key.h`）抢。仍找不到时从 `TILING_KEY_IS` / `GetTilingKey()` / 宏建 `source_declared` keys，packing 绑返回表达式；`fast` 仍 skip fold。Kernel 入口认 `extern "C" __global__` 与 `#include "./archXX/"`，Host 走 `op_host/**`（含 `op_tiling/`）。TilingData 认 `struct` 与 `class`；kernel 闭包要带上入口 quoted include 的同 arch 头，不能把 `op_kernel/*.h` 当外族源码清掉。
