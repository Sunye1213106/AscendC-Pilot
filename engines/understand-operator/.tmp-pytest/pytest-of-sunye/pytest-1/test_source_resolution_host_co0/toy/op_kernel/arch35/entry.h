using ToyTilingFFFF =
    optiling::ToyTilingData<false, false>;
struct ConstInfo { uint32_t aicCoreNum; };
inline void InitConst() {
  ConstInfo constInfo;
  constInfo.aicCoreNum = tilingData->base.coreNum >> 1;
}
