# 只读源码检索

## When to use

需要在 confirmed scope 内定位源码命中，且不得使用裸 Bash/PowerShell 写盘检索。

## Tools

1. `pilot_cli` command=`ro-search --pattern ... --paths ...`
2. 命中后用 `source-reading` 取连续证据窗

## Output shape

- locate-only 命中列表（路径 / 行 / 预览）
- locate-only 结果不算 verified 证据；闭合前必须再取窗口

证据硬规则见 policy `evidence`，勿复述。

硬限制：禁止 `>` / `tee` / `Set-Content` / `Out-File` / `sed -i` / 任意 python 写盘。
