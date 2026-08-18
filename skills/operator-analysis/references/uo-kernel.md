# UO · Kernel

按需阅读。分支、root trace、与 TilingKey/TilingData 的消费关系。

## 查什么

- BRANCH 条件、stage（constexpr / runtime）  
- Kernel 对 key dim / tiling field 的读取  
- OPERATION / ROOT / WRAPS / ROOTED_AT（root trace）  
- SELECTS / LAUNCHES（须有 provenance；无证据边不算事实）

## 推荐接口

```text
uo-query --project <op> <branch_or_key>
uo-query --project <op>
```

OpenCode：插件 `pilot_cli`，command 即上列 argv。

同名 `if constexpr` 返回 `functions` 计数目录，每个 function 一条样例（snippet 从命中行向后盖住 if 体）。第二 ident 当 function 过滤。不要把「文件里第一次出现」当唯一路径。

## Claim 提示

- Host 已否定合法性 → 可直接 ANSWERED（非法），不必穷举 kernel 组合  
- 缺 compile-time 硬过滤 → 主答案可发，边角标 PARTIAL
