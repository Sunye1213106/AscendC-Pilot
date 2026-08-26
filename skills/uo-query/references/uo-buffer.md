# Buffer / Register 与 LocalTensor

按需阅读。

## 查什么

- BUFFER 实体：scope、存储类（GM / UB / L1 等）、wrapper
- REGISTER 实体：RegTensor / MaskReg / …，arch35 寄存器压力
- `facts.tposition`：`TPosition` / `QuePosition`（VECIN / VECOUT / A1 …），不要把 VECIN 与 VECOUT 都只看成 UB
- QUEUE 同样投影 `tposition`
- 与 OPERATION 的 REFERENCES / 读写关系
- Kernel Root Trace 中的 `reached_buffers` / `reached_registers`

## 推荐接口

```text
uo-query --project <op> <buffer_or_register_name>
```

OpenCode：插件 `pilot_cli`，command 即上列 argv。

名字命中 BUFFER / REGISTER 后，卡片 edges 里看 REFERENCES（哪些 OPERATION 用了这块存储 / 寄存器）和 ROOTED_AT（AscendC 类型根）。

不要搜类型根 `LocalTensor` / `RegTensor` / `TQue`：那是 catalog ident，查询会故意空返回并给 hint。搜实例名。
