# Contract

TG 的契约就是 **一份** `init.yaml`：列、mapping、值域、golden、精度/性能口径、`uo_digest`。

- 声明 Key 空间仍来自 UO（`product_uo.legal_key_rows`），但控制面是脚本仓的列。
- `uo_digest` 变了必须重跑 `/tg-init`。
- `init.yaml` 不含具体 case 行；case 属于 solve。
- mapping 空（有脚本仓时）不得 human_confirm。
