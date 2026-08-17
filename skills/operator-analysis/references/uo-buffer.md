# UO · Buffer / LocalTensor

按需阅读。

## 查什么

- BUFFER 实体：scope、存储类（GM / UB / L1 等）、wrapper  
- `facts.tposition`：`TPosition` / `QuePosition`（VECIN / VECOUT / A1 …），不要把 VECIN 与 VECOUT 都只看成 UB  
- QUEUE 同样投影 `tposition`  
- 与 OPERATION 的读写关系  
- Kernel Root Trace 中的 reached_buffers

## 推荐接口

```text
acp uo-query --project <op> <name_or_function>
```
