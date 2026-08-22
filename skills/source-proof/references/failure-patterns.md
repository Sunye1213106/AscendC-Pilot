# 证明失败模式

**何时加载**：准备宣称 PROVED，或排查「看起来像证明其实会误杀可达态」时。

## 没钉层 / 用错层的 cover

「没有 4/5/6」可能是 template 不编，也可能是 Host 拒掉。组合 cover>0 只说明 SEL 接纳。  
**对策**：先 `Dim=` / 组合查询。product 无值 → template。product 有、仍称不可达 → 必须证 host。

## 赋值当成发出的 Key

`DetermineMode` 给 `inputDtype` 赋了 4/5/6，就说这些 Key 会产生。  
**对策**：还要看同一条调用链上有没有 `GRAPH_FAILED` / early return。写出 ≠ 活到 `GetTilingKey`。

## 第一页 snippet 当函数已读完

`ProcessQuantInfo` 卡停在 `if (queryType == FP8…)`，没看到 `return GRAPH_FAILED`。  
**对策**：按定义 span 读完函数。截断处不得关入口 / 返回义务。

## packing writers 当字段写点全集

`IsRope` 的 writers 只有 `GetTilingKey` 的 `hasRope` 打包。`hasRope` 本身在哪赋值，图上可能没有。  
**对策**：另查 `fBaseParams.<field>`。写点不全 → 覆盖义务最多 `BLOCKED`。

## 第一张卡是错 kind

`IsRope` 先落到 TilingData `isRope`（空 tensor），`hasRope` 先落到 kernel 分支。  
**对策**：看卡片全部 kind，跟 `next`。禁止只信第一页。

## cover=0 当 Host 不可达

`IsNEqual=1,DeterType=0` 模板未编，不能直接写成 Host 从不产生。  
**对策**：template 排除只写 template。host 仍要 packing 公式。

## 漏例外分支

无 mask 时 `SetSparseParams` 的 PREFIX 可走 `DeterType=1`。漏掉会误杀可达 Key。  
**对策**：第一行分流、PREFIX / 改写 layout / 空 tensor 必须进替代路径。

## 搜索耗尽 / 无观测写运行时不可达

有限构造未命中，或没有 REWRITE/REFUSE 就写运行时不可达。  
**对策**：`INSUFFICIENT`。运行时值不能回填成宏条件。
