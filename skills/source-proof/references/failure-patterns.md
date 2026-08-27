# 证明失败模式

**何时加载**：准备宣称 PROVED，或排查「看起来像证明其实会误杀可达态」时。

## 没钉层 / 用错层的 cover

「没有某几个取值」可能是 template 不编，也可能是 Host 拒掉。组合 cover>0 只说明 SEL 接纳。
**对策**：先查 template 覆盖。product 无值 → template。product 有、仍称不可达 → 必须证 host。

## 赋值当成发出的 Key

赋值函数给宿主字段写了某值，就说对应 Key 会产生。
**对策**：还要看同一条调用链上有没有 `GRAPH_FAILED` / early return。写出 ≠ 活到 packing 出口。

## 第一页 snippet 当函数已读完

卡片停在 dtype / 模式分支，没看到 `return` 或失败码。
**对策**：按定义 span 读完函数。截断处不得关入口 / 返回义务。

## packing writers 当字段写点全集

标识符的 writers 只有 packing 出口的打包点。字段本身在哪赋值，图上可能没有。
**对策**：另查宿主字段块。没有 writer-closure receipt → 覆盖义务最多 `BLOCKED`。

## 第一张卡是错 kind

标识符先落到 TilingData 字段（空 tensor），kernel 侧标志先落到 kernel 分支。
**对策**：看卡片全部 kind。禁止只信第一页。

## cover=0 当 Host 不可达

某组合模板未编，不能直接写成 Host 从不产生。
**对策**：template 排除只写 template。host 仍要 packing 公式。

## 漏例外分支

第一行分流、PREFIX / 改写 layout / 空 tensor 可能另开可达路径。漏掉会误杀可达 Key。
**对策**：这些例外必须进替代路径。

## 搜索耗尽当成不可达

有限构造未命中，或「我没观测到」就写运行时不可达。
**对策**：`INSUFFICIENT`。缺少观测不是证明。完整静态证明（义务关闭且 completeness 有 receipt）可以没有 runtime witness。
