# AscendC 性能风险

切分、核数、Buffer / 队列和 dtype 计算路径决定数据搬运与计算占用。这些是实现事实。

## tiling 切分

TilingData 切分字段的 writer 或 rhs 变了，tile 大小和核边界会跟着变。切不整时 remainder tile 的工作量与主 tile 不同。

## usedCoreNum 与负载均衡

usedCoreNum / 多核谓词决定单核还是满核。核数变化会改变每核 shape 和同步等待。负载不均表现为部分核空转或尾核拖住整体。

## buffer 与队列

InitBuffer、QUEUE tposition、队列深度影响 UB 压力和生产者-消费者等待。Buffer 变小或方向变了，可能增加搬次或堵核。

## 数据搬运

Host workspace、post copy、scatter 一类额外搬运会吃掉切分省下的时间。减少 copy 如果换成更紧的核内 Buffer，可能只是把压力换位置。

## dtype 计算路径

同一算法的 fp16 与 fp32 路径吞吐不同。路径切换（含量化 / 反量化）会改变计算与搬运比例。

## tail / 非整除

非整除 tile 和核边界 shape 通常不是主路径的性能代表。它们容易暴露额外同步或二次 copy。
