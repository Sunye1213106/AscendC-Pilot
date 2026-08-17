REG_OP(Toy)
  .INPUT(x,
         TensorType({DT_FLOAT16, DT_BF16}))
  .DYNAMIC_INPUT(y, TensorType({DT_FLOAT}))
  .OUTPUT(z, TensorType({DT_FLOAT16}))
  .OP_END_FACTORY_REG(Toy)
