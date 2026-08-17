class Toy : public OpDef {
  explicit Toy(const char *name) : OpDef(name) {
    this->Input("x")
        .ParamType(DYNAMIC)
        .DataType({ge::DT_FLOAT16, ge::DT_BF16, ge::DT_INT8})
        .Format({ge::FORMAT_ND});
    this->Output("y").DataType({ge::DT_FLOAT16});
  }
};
