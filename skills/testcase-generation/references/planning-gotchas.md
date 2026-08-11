# TG Plan — Gotchas

- **Plan 只冻结 T**：不构造 case、不 Host、不证明不可达、不扩大声明集合 D。
- **默认 T=D**：用户未指定时计划全部源码声明 Key；指定 packed keys / 过滤时不得偷偷加回全量。
- **L3 元素是 (key, site, outcome)**：不要把 L0 Key 集合直接当成 L3 目标。
- **approve 前目标可变，approve 后不可变**：solve 不得自行改 `target_set.yaml`。
- **不可达证明属于 solve/lemma**：plan 阶段写“此 Key 不可达”无效。
