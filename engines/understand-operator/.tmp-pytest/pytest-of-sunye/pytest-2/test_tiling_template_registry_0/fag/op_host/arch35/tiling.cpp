
REGISTER_TILING_TEMPLATE_WITH_ARCH(FlashAttentionScoreGrad, FlashAttentionScoreGradTiling, ASCEND_V220, 900)
REGISTER_TILING_TEMPLATE_WITH_ARCH(FlashAttentionScoreGrad, RegbaseFAG, ASCEND_V350, 950)
REGISTER_TILING_DEFAULT(RegbaseFAG)

class RegbaseFAG {
 public:
  bool IsCapable() { return true; }
};
