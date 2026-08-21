# UO · Template / Macro / BuildVariant

按需阅读。

## 查什么

- TEMPLATE / TEMPLATE_ARG / TEMPLATE_INSTANCE  
- MACRO / COMPILE_VAR  
- BuildVariant 与 ARCH 隔离（**禁止跨 variant 混证据**）  
- UI_LIST / TPL 声明对维域的约束

## 推荐接口

```text
uo-query --project <op> <name_or_key>
uo-query --project <op> Dim=V
```

OpenCode：插件 `pilot_cli`，command 即上列 argv。

## Claim 提示

「模板是否接纳某值」停在 template-admissible；不要自动升级到 full reachability。
