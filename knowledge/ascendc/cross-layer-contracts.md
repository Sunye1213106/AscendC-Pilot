# 跨层契约

同一语义状态经过多层：

```text
D_interface      接口 / Proto / OpDef 声明的合法集合
D_validation     Host 校验接受的集合
D_dispatch       Host 编码出的调度表示集合
D_implementation 实现声明（模板实例 / TPL / 注册）集合
```

正确系统应满足：所有被上游接受并成功 dispatch 的状态，都必须有下游 implementation。运行时成功产生的调度状态不得落在实现声明之外。

## 典型断裂

```text
上游允许
  → Host 未拒绝
  → 生成 dispatch state X
  → implementation domain 中无 X
  → accepted-but-undeclared
```

这不是随机非法输入，而是层间支持集合不一致。TilingKey、optional input、template 参数、dtype、layout、feature flag 都走同一条链。

## 检查维度

对每个新增或放宽的组合：下游是否有对应声明与实现？

对每个收窄下游：上游是否仍允许该组合？

接口声明 `dtype=A` 与 `optional_feature=true` 合法，Host 同样允许并编码 `dispatch=(A,true)`，但 implementation 只存在 `(A,false)`，就是跨层契约断裂。
