# 结构化审查

## Purpose

独立审查既有产物，写符合 schema 的 review，不修改被审正文。

## Method

1. 只读被审产物与声明的证据面。
2. 按 schema 逐项判定 pass / fail / needs_human。
3. finding 用中文；reason_code 用英文。
4. 写唯一允许的 review 输出路径。

## Hard Constraints

- MUST NOT：改被审产物。
- MUST NOT：缺少证据却标 pass。
