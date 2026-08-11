# 跨层契约一致性

**何时加载**：改动触及 dtype、layout、optional input、attribute、template 参数、dispatch key、feature flag、architecture，或 Host/Kernel 声明空间时。

## 一般形式

同一语义状态经过多层：

```text
D_interface      接口 / Proto / OpDef 声明的合法集合
D_validation     Host 校验接受的集合
D_dispatch       Host 编码出的调度表示集合
D_implementation 实现声明（模板实例 / TPL / 注册）集合
```

正确系统应满足：

```text
所有被上游接受并成功 dispatch 的状态
都必须有下游 implementation
```

即：运行时成功产生的调度状态不得落在实现声明之外。

## 典型缺陷

```text
上游允许
  → Host 未拒绝
  → 生成 dispatch state X
  → implementation domain 中无 X
  → 契约断裂（accepted-but-undeclared）
```

这不是「随机非法输入」，而是**层间支持集合不一致**。

## 检查路径

```text
接口声明
→ validation
→ Host derived state
→ dispatch encoding
→ implementation declaration
→ implementation body
```

对每个新增或放宽的组合，问：下游是否有对应声明与实现？对每个收窄下游，问：上游是否仍允许该组合？

## 泛化示例

接口声明 `dtype=A` 与 `optional_feature=true` 合法；Host 同样允许并编码 `dispatch=(A,true)`。  
但 implementation declarations 只存在 `(A,false)`。  
则存在 accepted-but-undeclared 状态，应报告为跨层契约断裂。

命名历史案例见 `docs/history/case-studies/`（Agent 默认不读）。
