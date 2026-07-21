# TG 算子语义 → Task Follow `/uo-query` → merge

（与 `tg-init/references/tg-uo-query-escalation.md` 同步。）

Lexicon = 可执行真值；resolve 必须 `--merge-uo-resolve`。  
**confidence=high only**；`derivation_chain` 叶子到 `VAR_CSV_*`；禁 medium / 半截依赖 / 函数叶。  
Parent 禁手改 YAML / 禁循环 CLI。字面量必须 ∈ CSV 域。  
KEY merge 后做 kernel unbound 第二段 Tasks，再 merge → audit → confirm。
