class InnerParams { public:
  int64_t scale;
};
template <bool Flag>
class PackTilingData { public:
  InnerParams base;
  typename std::conditional<Flag, InnerParams, std::nullptr_t>::type opt;
  int64_t blockStarts[4];
};
