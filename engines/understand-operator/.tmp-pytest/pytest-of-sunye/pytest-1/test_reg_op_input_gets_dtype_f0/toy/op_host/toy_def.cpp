class Toy : public OpDef {
  explicit Toy(const char *name) : OpDef(name) {
    this->Input("x").DataType({ge::DT_FLOAT16, ge::DT_BF16});
    this->Output("y").DataType({ge::DT_FLOAT16});
  }
};
