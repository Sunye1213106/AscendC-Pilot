# 闭环失败模式

**何时加载**：残差停滞、假 gap=0、E 与 R 冲突、出现未声明运行态时。

## 把引理留到最后

多轮 Replay 有 reject / exclusive open，却一直 SEARCH_PROGRESS，等搜索耗尽才进 lemma。  
**对策**：`search.md` — 每轮 Round Analysis；expected growth 立刻对 reject 证引理。

## 非预期增长仍盲搜

Host 系统性 rewrite / ΔR 落在无关维时，重复同一 mutation，而不是用已发现 R + 源码定向构造。  
**对策**：`search.md` 分支 B → `CONSTRUCT_TARGETS`。

## 把预测写进 R

用构造目标 key 或模型预测充当可达证据。  
**对策**：`closure-safety.md` §1。

## 负证据进 E

搜索耗尽 / 样本缺失 / 模型分数 / 单次 Replay reject 直接抬 E。  
**对策**：`closure-safety.md` §2–3。

## 冲突时丢弃 R

新 witness 击穿旧 exclusion 时删观测而不是 revoke 规则。  
**对策**：优先击穿 E。

## 吞掉 undeclared

Host 产出 `x ∉ D` 时丢弃或强行投影进 D。  
**对策**：单独报告；查跨层契约。

## 继承过期证书

源码或声明变更后继续用旧 gap=0。  
**对策**：源码或声明变更后旧证书作废。

## 假完整性放行

required 文件存在但内容为 `not_extracted` / 空壳，gate 当通过。  
**对策**：文件存在 ≠ 语义完备；空壳 / `not_extracted` 不得当 gate 通过。
