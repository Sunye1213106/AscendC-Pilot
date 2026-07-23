# 语义闭合

## Purpose

对指定 ID 集合做证据驱动的语义闭合；证据不足则保持 unresolved。

## Method

1. 只处理当前 Action 列出的 ID。
2. 组合 source-reading / cbm-navigation / kb-query 收集证据。
3. 仅 high confidence 可闭合；否则保留 open 并写明缺证类型。
4. 输出符合合同的 patch / 候选，不写裁判 verdict。

## Hard Constraints

- MUST NOT：伪造 high；batch 中塞 complex KEY。
- MUST NOT：处理目标集外 ID。
