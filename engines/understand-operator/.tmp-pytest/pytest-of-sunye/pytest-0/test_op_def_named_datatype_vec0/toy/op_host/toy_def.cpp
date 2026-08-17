static const std::vector<ge::DataType> keyDataType = {
    ge::DT_INT8, ge::DT_FLOAT16, ge::DT_INT8, ge::DT_BF16,
};
class Toy : public OpDef {
  explicit Toy(const char *name) : OpDef(name) {
    this->Input("x").ParamType(REQUIRED).DataType(keyDataType);
    this->Output("y").DataType(keyDataType);
  }
};
