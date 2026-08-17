void ToyInferShape() {
  this->Input("tokens").ParamType(REQUIRED);
  this->Output("y").ParamType(REQUIRED);
  this->Attr("axis");
}
