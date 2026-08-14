# 证明失败模式

**何时加载**：准备宣称 PROVED，或排查「看起来像证明其实会误杀可达态」时。

## 漏入口 / 第一行分流

函数第一行 dispatch / early return 未枚举 → 蕴含边界画错 → 误杀可达状态。  
**对策**：入口义务未关不得 `PROVED`。

## 搜索耗尽当不可达

有限构造未命中、样本未出现 → 写成「源码不可达」。  
**对策**：见 `references/evidence-quality.md`；只能 `INSUFFICIENT` 或继续搜。

## domain 当可达域

静态 `domain` / 可能值集合当作「运行不会取其他值」。  
**对策**：`static-evidence.md` — value domain ≠ reachable domain。

## derived 当 exact

有表达式就做排除证明。  
**对策**：`evidence-quality.md` — derived ≠ exact。

## 复合赋值 / 容器写漏记

`+=`、`push_back`、整容器 `operator=` 被当成无关或覆盖错误 → 写点集合假完备。  
**对策**：写点义务要求完整；解析器 partial 时 `INSUFFICIENT`。

## 错误退出守卫一律丢弃

把所有 failure return 的否定扔掉 → 合法输入域被放宽 → 假可达。  
**对策**：区分「重述型 bailout」与「排除型 bailout」。

## 别名 / 保存-修改-恢复

只看主名字赋值，漏别名写。  
**对策**：`references/cpp-semantics.md`。

## 无观测写不可达

没有 REWRITE/REFUSE 等运行事实，仅凭「源码看起来」。  
**对策**：观测绑定义务；无事实不得声称运行时不可达。
