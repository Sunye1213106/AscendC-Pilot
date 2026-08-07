# 只读源码检索

## Purpose

定位源码时只走 `acp ro-search`，禁止裸 Bash/PowerShell。

## Method

1. `acp ro-search --pattern ... --paths ...`
2. 命中后用 source-reading 取连续证据窗。
3. locate-only 结果不算 verified 证据。

## Hard Constraints

- MUST NOT：`>` / `tee` / `Set-Content` / `Out-File` / `sed -i` / 任意 python 写盘。
- MUST NOT：把 grep 命中当高置信证据闭合。
