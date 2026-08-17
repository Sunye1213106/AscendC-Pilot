uint64_t GetTilingKey() const {
  uint64_t tilingKey = 10;
  if (tmpData.attenEnable) { tilingKey += 1; }
  tilingKey *= 10;
  if (tmpData.ropeDim != 0) { tilingKey += 1; }
  tilingKey *= 10;
  if (tmpData.layout == 1) { tilingKey += 1; }
  tilingKey *= 10;
  if (tmpData.deterministic) { tilingKey += 1; }
  tilingKey *= 10;
  if (tmpData.kvMerge) { tilingKey += 1; }
  return tilingKey;
}
