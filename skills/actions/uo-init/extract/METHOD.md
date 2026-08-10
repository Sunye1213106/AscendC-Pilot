# extract

确定性运行 Clang/frontend 抽取 CompilerFacts，覆盖 Host、TilingKey/registry、Kernel 与当前 BuildVariant 可见的编译期事实。

内部步骤：`extract_host` → `extract_tiling_key` → `extract_registry` → `extract_kernel`。

本 Action 不调用 Agent、不绑定 task prompt，也不猜测 AscendC 业务语义；无法由 frontend 可靠确定的内容交给后续 CodeMap Pass 形成 explicit unresolved。
