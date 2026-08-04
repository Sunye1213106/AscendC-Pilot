# 引理证明纪律

Producer（`lemma_mine`）输入必须是 `lemma_leads` 确定性生成的封闭包，禁止自行发明 lead。

## 三条推导路径

| 路径 | 做法 |
|---|---|
| A 合取式 | 直接从长合取末尾项读出互斥 |
| B 全部赋值点 | 列全 write site、early return、后续覆盖与 guard |
| C 运行时稳定替换 | 从 `explain` 的「要的→给的」统计反查赋值点 |

## 蕴含检查清单（硬规则）

对 `A ⇒ B`：

1. A 的所有构造入口
2. 相关函数 early return
3. 分流调用（尤其函数第一行）
4. A/B 字段全部赋值点
5. 后续覆盖
6. 例外分支
7. 最后才形成证明

反面教材：`SetSparseParams` 第一行 PREFIX 分流——漏看会把「无 mask → DeterType∈{0,2}」写错，误杀 261 个可达 Key。

## 生命周期

```text
lead → candidate → source_supported → counterexample_checked
     → reviewed → active
active → refuted → revoked  （new_R ∩ excluded ≠ ∅）
```

等级：仅 `source_lemma_verified` / `solver_unsat_verified`（实现映射：`source_lemma` / `solver_derived`）可进 E。
