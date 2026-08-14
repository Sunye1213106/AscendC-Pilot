# Risk Classes

Classify each impacted anchor by observable failure mode, not file name.
Obligations attach from the anchor's CodeMap `kind` (and OPERATION callee).

Developer language maps onto these classes:

| 失败怎么说 | class | 何时挂 |
| --- | --- | --- |
| Tiling 失败、Kernel 找不到、dispatch 漏分支 | **dispatch** | TILING_KEY / TEMPLATE / PREDICATE |
| 接口、字段布局、输入输出合同 | **contract** | INPUT/OUTPUT、TILING_FIELD/DATA |
| 覆盖缺口、路径没跑到 | **coverage** | BRANCH / KERNEL / 未分类 OPERATION |
| 越界、rank/dtype/tail、切分公式 | **shape** | TILING_FIELD/DATA |
| 同步缺失、卡死、队列/Buffer 生命周期 | **sync** | BUFFER/REGISTER/QUEUE/PIPE/EVENT、SetFlag 族 |
| 精度不对（Cast / DataCopy / 多 dtype） | **precision** | Cast / DataCopy 类 OPERATION；**V 需外部测量** |
| 性能回退 | **perf** | BUFFER 等；**V 需 profiling 收据** |

Kind routing:

- **API/contract:** INPUT/OUTPUT, plus TilingData field layout.
- **Control/selection:** TilingKey, template, predicate, or dispatch branch.
- **Data/layout:** TilingData field, size, offset, alignment, or serialization.
- **Kernel/memory:** bounds, address space, copy extent, buffer, queue, or register.
- **Synchronization:** BUFFER/REGISTER/QUEUE/PIPE/EVENT, or SetFlag/WaitFlag family.
- **Build/variant:** macro, include closure, specialization, or architecture.
- **Quality:** correctness evidence, regression coverage, precision, or performance.

A BUFFER-only slice does not create a dispatch obligation. Untyped anchors with
an explicit `risk_classes` list still attach to those classes.

Severity and likelihood must cite evidence separately. Flag APIs expose
identity-level pair appearance (`flag_paired`); that is not happens-before.
TQue EnQue/DeQue are outside the flag pair check. Precision and performance
risks require external measurements (`ce-external-evidence/v1`) before they
can enter `V`.

精度 → `P-*`，性能 → `F-*`，dispatch 走全量 Key overlay 而不是场景子集。id 与挂载规则只认 `references/scenario-catalog.md`。
