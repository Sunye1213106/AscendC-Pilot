auto queryShape = context_->GetInputShape(static_cast<size_t>(InputIndex::QUERY));
int64_t s1 = queryShape->GetStorageShape().GetDim(0);
data.set_s1(s1);
