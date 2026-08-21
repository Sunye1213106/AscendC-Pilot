# 闭环失败模式

**何时加载**：残差停滞、假 gap=0、E 与 R 冲突、出现未声明运行态时。

## 把引理留到最后

多轮 Replay 有 reject / exclusive open，却一直盲搜，等搜索耗尽才进引理。  
**对策**：每轮都写 worklog 四段；对 reject 立刻挂可反驳线索，交给 `skills/lemma-mine/SKILL.md` / `skills/source-proof/SKILL.md`。

## 非预期增长仍盲搜

Host 系统性 rewrite、增长落在无关维时，重复同一 mutation。  
**对策**：用已发现观测 + 源码定向改控制列，不要再盲搜。

## 把预测写进 R

用构造目标 key 或模型预测充当可达证据。  
**对策**：R 只能来自真实 oracle 的成功观测（HIT）。target / prediction / 构造意图都不是 R。

## 负证据进 E

搜索耗尽、样本缺失、模型分数、单次 Replay reject 直接抬 E。  
**对策**：这些只能保持 open。`Replay reject ≠ E`。E 只能来自经审查的源码引理。

## 冲突时丢弃 R

新 witness 击穿旧 exclusion 时删观测而不是撤销规则。  
**对策**：优先击穿 E，保留 R。

## 吞掉未声明态

Host 产出 `x ∉ D` 时丢弃或强行投影进 D。  
**对策**：单独报告；当跨层契约问题，不要当普通 miss。

## 继承过期证书

源码或声明变更后继续用旧 gap=0。  
**对策**：源码或声明变了，旧闭合作废。

## 假完整性放行

required 文件存在但内容为 `not_extracted` / 空壳。  
**对策**：文件存在 ≠ 语义完备。
