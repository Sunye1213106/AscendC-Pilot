# UO · Buffer / LocalTensor

按需阅读。

## 查什么

- BUFFER 实体：scope、存储类（GM / UB / L1 等）、wrapper  
- 与 OPERATION 的读写关系  
- Kernel Root Trace 中的 reached_buffers

## 推荐接口

```text
acp uo-query --mode buffer --pattern <name_or_function>
acp uo-query --mode search --kind BUFFER --pattern <needle>
```
