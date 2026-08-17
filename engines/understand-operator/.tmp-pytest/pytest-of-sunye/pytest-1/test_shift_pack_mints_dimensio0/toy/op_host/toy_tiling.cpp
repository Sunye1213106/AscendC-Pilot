void SetTilingKey(const ge::DataType inDtype, bool doRmsQuant, auto *context) {
  uint64_t tilingKey = static_cast<uint64_t>(inDtype == ge::DT_BF16);
  tilingKey = (tilingKey << 2) + static_cast<uint64_t>(param.cacheMode);
  tilingKey = (tilingKey << 1) + static_cast<uint64_t>(formatWeight1 == ge::FORMAT_FRACTAL_NZ);
  tilingKey = (tilingKey << 1) + static_cast<uint64_t>(formatWeight2 == ge::FORMAT_FRACTAL_NZ);
  tilingKey = (tilingKey << 1) + static_cast<uint64_t>(formatWeight3 == ge::FORMAT_FRACTAL_NZ);
  tilingKey = (tilingKey << 2) + static_cast<uint64_t>(param.quantMode);
  if (!doRmsQuant){
    tilingKey += 1000;
  }
  context->SetTilingKey(tilingKey);
}
