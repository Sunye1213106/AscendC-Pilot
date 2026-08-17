#define TILING_KEY_DIVIDE_BS_FP16 100
#define TILING_KEY_DIVIDE_BS_BF16 101
void GenTilingKey() {
  tilingKey_ = TILING_KEY_DIVIDE_BS_FP16;
  if (tokenDtype_ == 1) tilingKey_ += 1;
}
