class AlphaTiling { public:
  int64_t blockFactor;
  void set_blockFactor(int64_t v) { blockFactor = v; }
};
class BetaTiling { public:
  int64_t blockFactor;
  void set_blockFactor(int64_t v) { blockFactor = v; }
};
class AlphaHost {
  AlphaTiling tilingData_;
  void Fill();
};
class BetaHost {
  BetaTiling tilingData_;
  void Fill();
};
