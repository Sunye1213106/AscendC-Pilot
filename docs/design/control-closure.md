# Understand-Operator Init：控制来源闭合图

`uo_init` 以 libclang、确定性源码闭包和 UO 知识图为主路径，抽取 Host、BranchInventory、Registry 与
TilingKey 的可追溯关系。源码证据必须来自 confirmed scope 的有界读取，图查询只能用于定位而不能单独
作为 `source_verified` 结论。

现状架构与三域同构见 [architecture.md](./architecture.md)；闭环认知见 `skills/testcase-generation`。
