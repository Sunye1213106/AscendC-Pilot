# AscendC 精度风险

Cast、拷贝对齐、累加、队列生命周期和 tail 都会改变核内数值路径。这些是算子实现事实。

## dtype 与 Cast

Cast 改变元素表示。dst dtype 选错、跳过某条 Cast 路径、或同一语义值在 Host 与 Kernel 走不同 dtype，都会与参考实现不一致。多 dtype 分支要分别看计算路径，不能假设 FP16/BF16 与 FP32 只是量化差。

## DataCopy 与对齐

DataCopy / DataCopyPad 对末维对齐敏感。未对齐且未 Pad 的拷贝会读到相邻垃圾或丢掉尾元素。对齐边界与 +1 余数是两类不同形状。

## 累加与长 reduce

reduce / softmax 一类长轴累加会放大低精度误差。缺少稳定累加 dtype（例如在 FP16 上直接累加很长的轴）容易在大序列上漂移。

## tail 与空形状

tail 核、零轴、长度为 1 的维、空 tensor 走的不是主 tile 路径。empty 不是 scalar。这些形状经常绕过主循环或触发 pad / remainder 分支。

## 可选输入

mask / pse / dropout / rope 一类可选输入会切换数值路径：有无输入不只是多一个 tensor，还可能改变 Cast、累加和输出合同。

## 队列生命周期

EnQue / DeQue 配对错误或计算周围缺少队列同步，会让核读到陈旧 UB 或全零。这是错误数据，不是差一点精度。

## clean 与 stress

验证数值路径时，干净输入（normal / zero / 近零 / 全 1）用来证明主路径可复现。极端值能暴露溢出，但不能单独证明主路径正确。
