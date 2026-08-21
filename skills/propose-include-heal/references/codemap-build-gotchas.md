# Include 探针失败

**何时加载**：探针报缺头、`clang_probe_unclean`、`SCOPE_VALIDATE_BLOCKED`，要判断环境 vs 真缺头时。

这是 **include 路径与当前 CANN 树没对齐**，不是官方包缺文件，也不是算子图上的 `unknown`。

`CANN_ENV_NOT_READY` 只表示 cann_root 没配上或目录不像 CANN。配好根目录后，prepare 不得再因某个硬编码相对路径失败。

1. 先确认 cann_root：`UO_CANN_ROOT` / `_cann/pkg` / 官方 `ASCEND_HOME_PATH`。
2. 等 prepare 的 include_heal 自动补 `-I`，写入 `uo/summary/build_context_extras.yaml`。不要手改算子源码、不要假造缺失头。
3. 脚本仍找不到：本步只写 staging；`heal_promote` 校验后追加 extras。不要手改 extras，不要改共享 `spec/build_context.yaml`。
4. 不要把 `ascendc/include/basic_api` 加成 kernel 主 include。
5. 不要把 CANN / 共享头残差当成算子错误；不要把 `RegTensor` / `VecReg` 再 stub 一遍。

staging ≠ canonical：正式 `.uo` 只由 commit 写入。
