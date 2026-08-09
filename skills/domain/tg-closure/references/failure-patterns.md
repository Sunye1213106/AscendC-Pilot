# 闭环失败模式

**何时加载**：残差停滞、假 gap=0、E 与 R 冲突、出现未声明运行态时。

## 把预测写进 R

用构造目标 key 或模型预测充当可达证据。  
**对策**：`closure-safety.md` §1。

## 负证据进 E

搜索耗尽 / 样本缺失 / 模型分数直接抬 E。  
**对策**：`closure-safety.md` §2–3。

## 冲突时丢弃 R

新 witness 击穿旧 exclusion 时删观测而不是 revoke 规则。  
**对策**：优先击穿 E。

## 吞掉 undeclared

Host 产出 `x ∉ D` 时丢弃或强行投影进 D。  
**对策**：单独报告；查跨层契约。

## 继承过期证书

源码或声明变更后继续用旧 gap=0。  
**对策**：`_shared/artifact-freshness.md`。

## 假完整性放行

required 文件存在但内容为 `not_extracted` / 空壳，gate 当通过。  
**对策**：`uo-kb-build/references/completeness.md` — existence ≠ completeness。
