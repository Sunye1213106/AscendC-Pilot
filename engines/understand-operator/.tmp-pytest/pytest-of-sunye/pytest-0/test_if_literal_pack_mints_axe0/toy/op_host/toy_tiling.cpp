uint64_t GenerateTilingKey() {
  uint64_t tilingKey = 9000000000000000ULL;
  if (socVer_ == 950) tilingKey = 9050000000000000ULL;
  if (dataType_ == 1) tilingKey += 22220ULL;
  if (kvCacheLayout_ == 1) tilingKey += 30000000ULL;
  if (hasPagedCache) tilingKey += 1000000ULL;
  if (innerPrecise_ == 1) tilingKey += 100000ULL;
  if (maskType_ == 3) tilingKey += 3000ULL;
  if (qInputLayout_ == 2) tilingKey += 2;
  if (softmaxLseFlag_) tilingKey += 100000000ULL;
  return tilingKey;
}
