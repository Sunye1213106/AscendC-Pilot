# Contract

TG 契约描述求解前的变量域、IO 与 TilingKey 维信息。

- 权威 Key 空间来自 UO（`.uo` 内 legal-key / host view），不是手写表。
- 契约变更必须留下 fingerprint；solve 侧用 fingerprint gate 防漂移。
- 契约不包含具体 case 行；case 属于 solve / replay。
- 完整性 gate（integrity）失败时不得 human_confirm。
