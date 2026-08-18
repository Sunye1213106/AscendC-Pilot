# propose-include-heal

脚本 include-heal 仍找不到头文件时，对照真实 CANN / ops 树建议额外 `-I`。只写 staging。正式 extras 由 `heal_promote` 写入。

## 方法

1. 读 `uo/summary/scope_candidates.yaml`（或当前 run 的 `scope/candidates.yaml`）里 `include_heal.unresolved`。不要处理清单外的头。
2. 读 session `environment_capabilities.yaml` 的 `cann.root`。只读该树和算子 `ops` 树；禁止改共享 `spec/build_context.yaml`。
3. 为每个 unresolved include 找到真实头文件，写出应加入的 include 根目录（使 `#include "foo/bar.h"` 能从该 `-I` 解析）。
4. 写 `runs/<run_id>/actions/propose_include_heal/staging.yaml`：

```yaml
host:
  - /abs/include/root
kernel:
  - /abs/include/root
evidence:
  - include: foo/bar.h
    dir: /abs/include/root
    side: host
```

路径必须是已存在的目录，且落在 cann_root 或 ops 树内。

## 禁止

- 写 `uo/summary/build_context_extras.yaml` 或任何正式 extras
- 改 `spec/build_context.yaml`
- 建 shim、造缺失头、改算子源码
- 成功路径（脚本已补上）不要调用本步
