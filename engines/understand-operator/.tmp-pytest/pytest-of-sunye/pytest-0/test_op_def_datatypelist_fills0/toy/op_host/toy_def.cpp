class Toy : public OpDef {
  explicit Toy(const char *name) : OpDef(name) {
    this->Input("indices").ParamType(REQUIRED).DataTypeList({ge::DT_INT32});
    this->Output("fetched").DataTypeList({ge::DT_BF16, ge::DT_FLOAT16, ge::DT_FLOAT});
  }
};
