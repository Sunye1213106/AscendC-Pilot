
struct PreParams { uint32_t flag; uint32_t optionalOn; uint8_t modeTag; };
struct DemoTilingData {
  void set_flag(uint32_t v) { flag = v; }
  void set_optionalOn(uint32_t v) { optionalOn = v; }
  void set_modeTag(uint8_t v) { modeTag = v; }
  uint32_t flag; uint32_t optionalOn; uint8_t modeTag;
};

void Decide(PreParams& params, int x, bool hasOpt) {
  params.flag = 1;
  if (x % 8 != 0) {
    params.flag = 0;
  }
  params.optionalOn = hasOpt ? 1 : 0;
  params.modeTag = 0;
}

void Pack(DemoTilingData* td, PreParams& params) {
  td->set_flag(params.flag);
  td->set_optionalOn(params.optionalOn);
  td->set_modeTag(params.modeTag);
}
