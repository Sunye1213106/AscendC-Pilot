class BaseParams { public:
  int64_t s1;
  uint32_t d;
  int64_t get_s1() const { return s1; }
};
class ToyTilingData { public:
  BaseParams base;
  uint32_t blockOuter;
};
