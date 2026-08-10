// Optional fast libclang walker for uo-init cold start.
// CLI: uo_walk --file PATH --side host|kernel --args ARGFILE --out OUT.json
//      [--needle N] [--op-root R]

#include <clang-c/Index.h>

#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace {

struct Options {
  std::string file;
  std::string side = "host";
  std::string argfile;
  std::string out;
  std::string needle;
  std::string op_root;
};

struct WalkState {
  std::string tu_path;
  std::string needle;
  std::string op_root;
  std::string current_func;
  std::vector<std::string> functions;
  std::vector<std::string> call_sites;
  std::vector<std::string> controls;
  std::vector<std::string> writes;
  std::vector<std::string> diagnostics;
  std::unordered_set<std::string> class_fields;
  int ctrl_ordinal = 0;
};

static std::string json_escape(const std::string &s) {
  std::string out;
  out.reserve(s.size() + 8);
  for (unsigned char c : s) {
    switch (c) {
    case '\\':
      out += "\\\\";
      break;
    case '"':
      out += "\\\"";
      break;
    case '\n':
      out += "\\n";
      break;
    case '\r':
      out += "\\r";
      break;
    case '\t':
      out += "\\t";
      break;
    default:
      if (c < 0x20) {
        char buf[8];
        std::snprintf(buf, sizeof(buf), "\\u%04x", c);
        out += buf;
      } else {
        out += static_cast<char>(c);
      }
    }
  }
  return out;
}

static std::string norm_path(CXFile file) {
  if (!file)
    return "";
  CXString sp = clang_getFileName(file);
  std::string p = clang_getCString(sp);
  clang_disposeString(sp);
  for (char &c : p) {
    if (c == '\\')
      c = '/';
  }
  return p;
}

static bool in_scope(const std::string &file, const std::string &needle,
                     const std::string &op_root) {
  if (file.empty())
    return false;
  if (!needle.empty() && file.find(needle) == std::string::npos &&
      (op_root.empty() || file.find(op_root) == std::string::npos)) {
    if (!op_root.empty() && file.find(op_root) != 0)
      return false;
    if (!needle.empty() && file.find(needle) == std::string::npos)
      return false;
  }
  if (!op_root.empty() && file.find(op_root) == 0)
    return true;
  if (!needle.empty() && file.find(needle) != std::string::npos)
    return true;
  return op_root.empty() && needle.empty();
}

static std::string spelling(CXCursor cur) {
  CXString s = clang_getCursorSpelling(cur);
  std::string out = clang_getCString(s);
  clang_disposeString(s);
  return out;
}

static std::string tokens_text(CXTranslationUnit tu, CXCursor cur, unsigned max) {
  CXToken *toks = nullptr;
  unsigned n = 0;
  clang_tokenize(tu, clang_getCursorExtent(cur), &toks, &n);
  std::string out;
  for (unsigned i = 0; i < n && i < max; ++i) {
    if (i)
      out += ' ';
    CXString ts = clang_getTokenSpelling(tu, toks[i]);
    out += clang_getCString(ts);
    clang_disposeString(ts);
  }
  clang_disposeTokens(tu, toks, n);
  return out;
}

static std::string func_json(const std::string &name, const std::string &file,
                             unsigned line, const std::vector<std::string> &params) {
  std::ostringstream os;
  os << "{\"name\":\"" << json_escape(name) << "\",\"file\":\""
     << json_escape(file) << "\",\"line\":" << line << ",\"params\":[";
  for (size_t i = 0; i < params.size(); ++i) {
    if (i)
      os << ',';
    os << '"' << json_escape(params[i]) << '"';
  }
  os << "]}";
  return os.str();
}

static CXChildVisitResult visit(CXCursor cursor, CXCursor parent, CXClientData data) {
  WalkState *st = static_cast<WalkState *>(data);
  CXTranslationUnit tu = clang_Cursor_getTranslationUnit(cursor);
  CXCursorKind kind = clang_getCursorKind(cursor);
  if (!file.empty() && !in_scope(file, st->needle, st->op_root) &&
      kind != CXCursor_TranslationUnit) {
    return CXChildVisit_Recurse;
  }
  CXFile cxfile = nullptr;
  unsigned line = 0, col = 0, off = 0;
  clang_getExpansionLocation(loc, &cxfile, &line, &col, &off);
  std::string file = norm_path(cxfile);

  if (kind == CXCursor_FunctionDecl || kind == CXCursor_CXXMethod ||
      kind == CXCursor_Constructor || kind == CXCursor_FunctionTemplate) {
    if (clang_isCursorDefinition(cursor)) {
      std::string name = spelling(cursor);
      if (!name.empty()) {
        st->current_func = name;
        std::vector<std::string> params;
        int n = clang_Cursor_getNumArguments(cursor);
        for (int i = 0; i < n; ++i) {
          CXCursor p = clang_Cursor_getArgument(cursor, i);
          std::string pn = spelling(p);
          if (!pn.empty())
            params.push_back(pn);
        }
        st->functions.push_back(func_json(name, file, line, params));
      }
    }
  } else if (kind == CXCursor_CallExpr || kind == CXCursor_CXXMemberCallExpr) {
    std::string callee = spelling(cursor);
    if (!callee.empty() && !st->current_func.empty()) {
      std::ostringstream os;
      os << "{\"caller\":\"" << json_escape(st->current_func)
         << "\",\"callee\":\"" << json_escape(callee) << "\",\"file\":\""
         << json_escape(file) << "\",\"line\":" << line << ",\"column\":" << col
         << ",\"receiver\":\"\",\"args\":[]}";
      st->call_sites.push_back(os.str());
    }
  } else if (kind == CXCursor_IfStmt || kind == CXCursor_ForStmt ||
             kind == CXCursor_WhileStmt || kind == CXCursor_DoStmt ||
             kind == CXCursor_SwitchStmt || kind == CXCursor_CXXForRangeStmt) {
    const char *k = "if";
    switch (kind) {
    case CXCursor_ForStmt:
      k = "for";
      break;
    case CXCursor_WhileStmt:
      k = "while";
      break;
    case CXCursor_DoStmt:
      k = "do";
      break;
    case CXCursor_SwitchStmt:
      k = "switch";
      break;
    case CXCursor_CXXForRangeStmt:
      k = "cxx_for_range";
      break;
    default:
      break;
    }
    std::string cond = tokens_text(tu, cursor, 48);
    if (cond.size() > 512)
      cond.resize(512);
    std::ostringstream os;
    os << "{\"id\":\"" << json_escape(file) << ":" << line << ":" << col << ":"
       << k << ":" << (st->ctrl_ordinal++) << "\",\"kind\":\"" << k
       << "\",\"file\":\"" << json_escape(file) << "\",\"line\":" << line
       << ",\"column\":" << col << ",\"condition\":\"" << json_escape(cond)
       << "\",\"function\":\"" << json_escape(st->current_func) << "\"}";
    st->controls.push_back(os.str());
  } else if (kind == CXCursor_BinaryOperator) {
    CXCursor lhs = clang_getCursorSemanticParent(cursor);
    (void)lhs;
    std::string op = tokens_text(tu, cursor, 8);
    if (op.find('=') != std::string::npos && op.find("==") == std::string::npos &&
        !st->current_func.empty()) {
      std::ostringstream os;
      os << "{\"path\":\"\",\"line\":" << line << ",\"rhs\":\""
         << json_escape(tokens_text(tu, cursor, 32))
         << "\",\"file\":\"" << json_escape(file) << "\",\"function\":\""
         << json_escape(st->current_func) << "\",\"column\":" << col << "}";
      st->writes.push_back(os.str());
    }
  } else if (kind == CXCursor_FieldDecl) {
    std::string name = spelling(cursor);
    if (!name.empty())
      st->class_fields.insert(name);
  }

  return CXChildVisit_Recurse;
}

static bool parse_args(int argc, char **argv, Options *opt, std::string *err) {
  for (int i = 1; i < argc; ++i) {
    std::string a = argv[i];
    auto need = [&](const char *flag) -> std::string {
      if (i + 1 >= argc) {
        *err = std::string("missing value for ") + flag;
        return "";
      }
      return argv[++i];
    };
    if (a == "--file")
      opt->file = need("--file");
    else if (a == "--side")
      opt->side = need("--side");
    else if (a == "--args")
      opt->argfile = need("--args");
    else if (a == "--out")
      opt->out = need("--out");
    else if (a == "--needle")
      opt->needle = need("--needle");
    else if (a == "--op-root")
      opt->op_root = need("--op-root");
    else {
      *err = "unknown arg: " + a;
      return false;
    }
  }
  if (opt->file.empty() || opt->argfile.empty() || opt->out.empty()) {
    *err = "usage: uo_walk --file PATH --side host|kernel --args ARGFILE --out OUT.json";
    return false;
  }
  for (char &c : opt->op_root) {
    if (c == '\\')
      c = '/';
  }
  return true;
}

static std::vector<const char *> read_compile_args(const std::string &path) {
  std::vector<std::string> storage;
  std::vector<const char *> out;
  std::ifstream in(path);
  std::string line;
  while (std::getline(in, line)) {
    while (!line.empty() && (line.back() == '\r' || line.back() == '\n'))
      line.pop_back();
    if (line.empty())
      continue;
    storage.push_back(line);
    out.push_back(storage.back().c_str());
  }
  return out;
}

static int run(const Options &opt, std::string *err) {
  auto args = read_compile_args(opt.argfile);
  CXIndex idx = clang_createIndex(0, 0);
  CXTranslationUnit tu = nullptr;
  unsigned flags = CXTranslationUnit_DetailedPreprocessingRecord;
  CXErrorCode ec = clang_parseTranslationUnit2(
      idx, opt.file.c_str(), args.data(), static_cast<int>(args.size()), nullptr, 0,
      flags, &tu);
  if (ec != CXError_Success || !tu) {
    *err = "clang_parseTranslationUnit2 failed";
    clang_disposeIndex(idx);
    return 1;
  }

  WalkState st;
  st.tu_path = opt.file;
  st.needle = opt.needle;
  st.op_root = opt.op_root;
  for (unsigned i = 0; i < clang_getNumDiagnostics(tu); ++i) {
    CXDiagnostic d = clang_getDiagnostic(tu, i);
    CXString ds = clang_formatDiagnostic(d, CXDiagnostic_DisplaySourceLocation);
    CXFile df = nullptr;
    unsigned dl = 0, dc = 0, dof = 0;
    clang_getExpansionLocation(clang_getDiagnosticLocation(d), &df, &dl, &dc, &dof);
    std::string dfname = norm_path(df);
    std::ostringstream os;
    os << '[' << static_cast<int>(clang_getDiagnosticSeverity(d)) << ',"'
       << json_escape(dfname) << "\",\"" << json_escape(clang_getCString(ds))
       << "\"]";
    st.diagnostics.push_back(os.str());
    clang_disposeString(ds);
    clang_disposeDiagnostic(d);
  }

  CXCursor root = clang_getTranslationUnitCursor(tu);
  clang_visitChildren(root, visit, &st);

  std::ostringstream json;
  json << "{\n  \"path\": \"" << json_escape(opt.file) << "\",\n";
  json << "  \"functions\": [";
  for (size_t i = 0; i < st.functions.size(); ++i) {
    if (i)
      json << ',';
    json << st.functions[i];
  }
  json << "],\n  \"call_sites\": [";
  for (size_t i = 0; i < st.call_sites.size(); ++i) {
    if (i)
      json << ',';
    json << st.call_sites[i];
  }
  json << "],\n  \"controls\": [";
  for (size_t i = 0; i < st.controls.size(); ++i) {
    if (i)
      json << ',';
    json << st.controls[i];
  }
  json << "],\n  \"writes\": [";
  for (size_t i = 0; i < st.writes.size(); ++i) {
    if (i)
      json << ',';
    json << st.writes[i];
  }
  json << "],\n  \"diagnostics\": [";
  for (size_t i = 0; i < st.diagnostics.size(); ++i) {
    if (i)
      json << ',';
    json << st.diagnostics[i];
  }
  json << "],\n  \"class_fields\": [";
  bool first = true;
  for (const auto &f : st.class_fields) {
    if (!first)
      json << ',';
    first = false;
    json << '"' << json_escape(f) << '"';
  }
  json << "]\n}\n";

  std::ofstream out(opt.out);
  if (!out) {
    *err = "cannot write " + opt.out;
    clang_disposeTranslationUnit(tu);
    clang_disposeIndex(idx);
    return 1;
  }
  out << json.str();

  clang_disposeTranslationUnit(tu);
  clang_disposeIndex(idx);
  return 0;
}

} // namespace

int main(int argc, char **argv) {
  Options opt;
  std::string err;
  if (!parse_args(argc, argv, &opt, &err)) {
    std::fprintf(stderr, "%s\n", err.c_str());
    return 2;
  }
  if (run(opt, &err) != 0) {
    std::fprintf(stderr, "%s\n", err.c_str());
    return 1;
  }
  return 0;
}
