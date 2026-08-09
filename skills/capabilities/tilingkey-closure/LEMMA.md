# 引理证明纪律

引理回答的问题是：**我构造并回放了针对某 open key 的 case，为何没命中？**  
合法答案只有：Host 拒绝，或 Host 改写成了别的 key——两者都必须能从源码证明。

Producer（`lemma_mine`）输入必须是 `lemma_leads` 从**构造/回放观测**生成的封闭包，禁止自行发明 lead，禁止把 `construct_reasons` 假设直接当 lead。

## 触发条件（先事实，后证明）

对每个目标 key，闭环必须先留下至少一类 oracle 事实：

| 结果 | 含义 | 引理方向 |
|---|---|---|
| HIT | 得到目标 key | 进 R；不写 E |
| REWRITE | 得到其他 key | 证明「目标维组合在 host 上必然被改写」 |
| REFUSE | 明确拒绝（非 crash） | 证明「该输入类在入口/守卫上不可达」 |
| CRASH / NOT_RUN | oracle 不可信 | 禁止写 E；修环境 |

没有上述事实，不得进入 `lemma_mine`。

## 三条推导路径

| 路径 | 做法 |
|---|---|
| A 合取式 | 从改写/拒绝对应的长合取末尾项读出互斥 |
| B 全部赋值点 | 列全 write site、early return、后续覆盖与 guard |
| C 运行时稳定替换 | 从 `explain` 的「要的→给的」**稳定**统计反查赋值点（须有多次一致回放） |

## 蕴含检查清单（硬规则）

对 `A ⇒ B`：

1. A 的所有构造入口
2. 相关函数 early return
3. 分流调用（尤其函数第一行）
4. A/B 字段全部赋值点
5. 后续覆盖
6. 例外分支
7. 最后才形成证明
8. **对照本轮构造 case**：说明该 case 走了哪条入口，为何命中上述守卫/改写

反面教材：`SetSparseParams` 第一行 PREFIX 分流——漏看会把「无 mask → DeterType∈{0,2}」写错，误杀可达 Key。  
反面教材：把构造器先验拒采（旧 `construct_reasons` 硬返回空）写成不可达——那是生成器缺陷，不是算子性质。

## 生命周期

```text
construct → replay → classify(HIT|REWRITE|REFUSE)
     → lead（绑定观测） → candidate → source_supported
     → counterexample_checked → reviewed → active
active → refuted → revoked  （new_R ∩ excluded ≠ ∅）
```

等级：仅 `source_lemma_verified` / `solver_unsat_verified`（实现映射：`source_lemma` / `solver_derived`）可进 E。

## Hard Constraints

- MUST NOT：无回放事实的「源码看起来不可达」。
- MUST NOT：`construct_reasons` / pair 频率 / 模型分数单独进 E。
- MUST：每条 lemma 的 `when` 不命中当前 R；新 R 出现冲突必须 revoke。
