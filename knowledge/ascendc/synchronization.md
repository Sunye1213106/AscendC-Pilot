# 同步与可见性

共享状态和同步原语决定核内数据何时可见。这些是实现事实。

## 配对

锁、event、barrier 必须在所有路径配对。错误返回如果跳过 release 或 wait，会留下未完成的同步。

## 双核可见性

AIC / AIV 各有自己的视角。一边写完共享 buffer，另一边未 wait 就读，会看到陈旧或半写入数据。CrossCore 标志必须配对，happens-before 不能从单侧调用点推出。

## 生产者-消费者

EnQue / DeQue 是队列方向上的同步。计算周围缺少这对操作，会读到陈旧 UB 或全零。Set/Wait 看同一 flag 是否成对。

## 共享 buffer

InitBuffer 与 tposition 决定谁在何时拥有一块 UB。生产者尚未交出、消费者已经开始算，属于生命周期错误，不是精度噪声。
