// Replay driver: reads one CSV line per case, runs the real host tiling, and
// fences each case's log so the Windows side can attribute it.
//
// Input line (semicolon-separated):
//   id ; inShapes ; inDtypes ; outShapes ; outDtypes ; attrs ; deterministic
//   - shapes: N comma-separated tensors, dims joined by '|', empty = absent.
//             A tensor that holds const data is `len@val1/val2/...`.
//   - dtypes: N comma-separated ge::DataType codes, same slot order as shapes.
//   - attrs:  '&'-joined name=kind:value, kind in {f, i, s}.
//
// Emits, on stdout, interleaved with OP_LOG output:
//   ###CASE <id>
//   ... tiling logs ...
//   ###DONE <id> ok=<0|1> key=<uint64>
// and appends one `id,ok,key` row per case to the out CSV.
//
// Usage: replay_main <in.csv> <out.csv> [operator.so]
//   When the third arg is absent, $REPLAY_SO is used.

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

#include "tiling/platform/platform_ascendc.h"
#include "op_host/tiling_base.h"
#include "tiling_context_faker.h"
#include "tiling_case_executor.h"
#include "base/registry/op_impl_space_registry_v2.h"

using Ops::Transformer::OpTiling::FlashAttentionScoreGradCompileInfo;
using gert::TilingContextPara;

namespace {

// One ASCII char for a datatype code is a checksum the parser relies on;
// anything unparseable is refused with a clear message rather than coerced.
constexpr int kInCount = 24;
constexpr int kOutCount = 6;
constexpr uint64_t kTilingDataBytes = 65536;  // TND swizzle needs more than the UT's 4096.

std::vector<std::string> Split(const std::string& s, char sep) {
    std::vector<std::string> out;
    std::string cur;
    std::stringstream ss(s);
    while (std::getline(ss, cur, sep)) out.push_back(cur);
    if (!s.empty() && s.back() == sep) out.emplace_back("");
    return out;
}

// One tensor slot: dims plus optional const payload, kept alive for the call.
struct TensorSpec {
    std::vector<int64_t> dims;
    std::vector<int64_t> payload;      // int64 const data (prefix sums, indices).
    bool hasPayload = false;
};

bool ParseTensor(const std::string& field, TensorSpec& out, std::string& err) {
    if (field.empty()) return true;  // absent tensor: empty shape is valid.
    std::string shape = field;
    const auto at = field.find('@');
    if (at != std::string::npos) {
        shape = field.substr(0, at);
        for (const auto& v : Split(field.substr(at + 1), '/')) {
            if (v.empty()) continue;
            try {
                out.payload.push_back(std::stoll(v));
            } catch (...) {
                err = "bad const value: " + field;
                return false;
            }
        }
        out.hasPayload = true;
    }
    if (shape.empty()) return true;
    for (const auto& d : Split(shape, '|')) {
        if (d.empty()) continue;
        try {
            out.dims.push_back(std::stoll(d));
        } catch (...) {
            err = "bad dimension: " + field;
            return false;
        }
    }
    return true;
}

TilingContextPara::TensorDescription ToDescription(const TensorSpec& spec,
                                                   const std::string& dtypeField) {
    ge::DataType dtype = ge::DT_FLOAT;
    if (!dtypeField.empty()) dtype = static_cast<ge::DataType>(std::atoi(dtypeField.c_str()));
    // Built up dim by dim: the shape only takes an initializer_list, and a
    // replayed rank is whatever the CSV says.
    gert::StorageShape shape;
    for (const int64_t d : spec.dims) {
        shape.MutableShape().AppendDim(d);
        shape.MutableStorageShape().AppendDim(d);
    }
    if (spec.hasPayload) {
        return {shape, dtype, ge::FORMAT_ND, true,
                const_cast<int64_t*>(spec.payload.data())};
    }
    return {shape, dtype, ge::FORMAT_ND};
}

bool ParseAttrs(const std::string& field, std::vector<TilingContextPara::OpAttr>& attrs,
                std::string& err) {
    if (field.empty()) return true;
    for (const auto& token : Split(field, '&')) {
        if (token.empty()) continue;
        const auto eq = token.find('=');
        const auto colon = token.find(':', eq == std::string::npos ? 0 : eq);
        if (eq == std::string::npos || colon == std::string::npos) {
            err = "bad attr: " + token;
            return false;
        }
        const std::string name = token.substr(0, eq);
        const std::string value = token.substr(colon + 1);
        switch (token[eq + 1]) {
            case 'f':
                attrs.emplace_back(name, Ops::Transformer::AnyValue::CreateFrom<float>(
                                             std::strtof(value.c_str(), nullptr)));
                break;
            case 'i':
                attrs.emplace_back(name, Ops::Transformer::AnyValue::CreateFrom<int64_t>(
                                             std::strtoll(value.c_str(), nullptr, 10)));
                break;
            case 's':
                attrs.emplace_back(name, Ops::Transformer::AnyValue::CreateFrom<std::string>(
                                             value));
                break;
            default:
                err = "bad attr kind: " + token;
                return false;
        }
    }
    return true;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 3) {
        std::fprintf(stderr, "usage: replay_main <in.csv> <out.csv> [operator.so]\n");
        return 2;
    }
    const char* soPath = argc > 3 ? argv[3] : std::getenv("REPLAY_SO");
    if (soPath == nullptr || !*soPath) {
        std::fprintf(stderr, "no operator .so given and $REPLAY_SO is empty\n");
        return 2;
    }

    // Register the operator SO exactly once; the tiling function is then
    // resolved by name for every case, which is what makes a batch cheap.
    auto registry = std::make_shared<gert::OpImplSpaceRegistryV2>();
    gert::OppSoDesc desc({ge::AscendString(soPath)}, "op_host_so");
    if (registry->AddSoToRegistry(desc) == ge::GRAPH_FAILED) {
        std::fprintf(stderr, "add so to registry failed: %s\n", soPath);
        return 2;
    }
    gert::DefaultOpImplSpaceRegistryV2::GetInstance().SetSpaceRegistry(registry);

    // arch35 / Ascend950. Keeping this in the driver (not the CSV) is why one
    // binary serves every arch35 replay; a different arch needs a rebuild, not
    // a new column.
    // npuArch is the last field and was being left value-initialised, which
    // reads as "not dav-3510". Only one thing branches on it -- the empty
    // output path, which then picks the pre-regbase tiling and emits key 0 --
    // so every other key came out right and the omission stayed invisible.
    // Ascend950 is dav-3510, so saying so is what the rest of the struct
    // already claims.
    FlashAttentionScoreGradCompileInfo compileInfo = {
        64, 32, 196608, 524288, 65536, 65536, 131072, 33554432, 32,
        platform_ascendc::SocVersion::ASCEND950,
        NpuArch::DAV_3510,
    };
    static const char* kSocInfo =
        "{\"hardware_info\":{"
        "\"BT_SIZE\":0,\"load3d_constraints\":\"1\","
        "\"Intrinsic_fix_pipe_l0c2out\":false,"
        "\"Intrinsic_data_move_l12ub\":true,"
        "\"Intrinsic_data_move_l0c2ub\":true,"
        "\"Intrinsic_data_move_out2l1_nd2nz\":false,"
        "\"UB_SIZE\":262144,\"L2_SIZE\":134217728,\"L1_SIZE\":524288,"
        "\"L0A_SIZE\":65536,\"L0B_SIZE\":65536,\"L0C_SIZE\":262144,"
        "\"CORE_NUM\":32,\"socVersion\":\"Ascend950\"}}";

    std::ifstream in(argv[1]);
    std::ofstream out(argv[2]);
    if (!in) {
        std::fprintf(stderr, "cannot open %s\n", argv[1]);
        return 2;
    }
    out << "id,ok,key\n";

    std::string line;
    while (std::getline(in, line)) {
        if (line.empty()) continue;
        const std::vector<std::string> f = Split(line, ';');
        std::string id = f.empty() ? "?" : f[0];

        std::string err;
        std::vector<TensorSpec> inSpecs(kInCount), outSpecs(kOutCount);
        std::vector<TilingContextPara::TensorDescription> inputs, outputs;
        std::vector<TilingContextPara::OpAttr> attrs;
        int deterministic = 0;
        bool parseOk = true;

        const std::string inShapes = f.size() > 1 ? f[1] : "";
        const std::string inDtypes = f.size() > 2 ? f[2] : "";
        const std::string outShapes = f.size() > 3 ? f[3] : "";
        const std::string outDtypes = f.size() > 4 ? f[4] : "";
        const std::string attrField = f.size() > 5 ? f[5] : "";
        if (f.size() > 6) deterministic = std::atoi(f[6].c_str());

        const auto inShapeF = Split(inShapes, ',');
        const auto inDtypeF = Split(inDtypes, ',');
        const auto outShapeF = Split(outShapes, ',');
        const auto outDtypeF = Split(outDtypes, ',');

        for (int i = 0; i < kInCount && parseOk; ++i) {
            parseOk = ParseTensor(i < (int)inShapeF.size() ? inShapeF[i] : "",
                                  inSpecs[i], err);
            inputs.push_back(ToDescription(
                inSpecs[i], i < (int)inDtypeF.size() ? inDtypeF[i] : ""));
        }
        for (int i = 0; i < kOutCount && parseOk; ++i) {
            parseOk = ParseTensor(i < (int)outShapeF.size() ? outShapeF[i] : "",
                                  outSpecs[i], err);
            outputs.push_back(ToDescription(
                outSpecs[i], i < (int)outDtypeF.size() ? outDtypeF[i] : ""));
        }
        if (parseOk && !ParseAttrs(attrField, attrs, err)) parseOk = false;

        std::printf("###CASE %s\n", id.c_str());
        std::fflush(stdout);

        uint64_t key = 0;
        bool ok = false;
        if (!parseOk) {
            std::fprintf(stderr, "[ERROR] %s parse: %s\n", id.c_str(), err.c_str());
        } else {
            TilingContextPara para(
                "FlashAttentionScoreGrad", inputs, outputs, attrs, &compileInfo,
                "Ascend950", kSocInfo, kTilingDataBytes, deterministic);
            TilingInfo info{};
            ok = ExecuteTiling(para, info);
            if (ok) key = info.tilingKey;
        }

        out << id << ',' << (ok ? 1 : 0) << ',' << key << '\n';
        std::printf("###DONE %s ok=%d key=%llu\n", id.c_str(), ok ? 1 : 0,
                    (unsigned long long)key);
        std::fflush(stdout);
    }
    return 0;
}
