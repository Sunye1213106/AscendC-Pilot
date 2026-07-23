# 域对称（tg-solve 启动门禁）

Lexicon / resolve 中的字面量必须 ∈ 对应 CSV 列 domain（含 optional presence 语义）。

## Fail →

`ask=domain_asymmetry` → `tg-init --merge-uo-resolve`（必要时重跑 uo-query Tasks）。

## MUST NOT

- 会话 Edit YAML 把域外常量改成「看起来合法」
- optional 列偷写成常量 `0` 糊弄
- 修改 approved plan 来消掉义务
