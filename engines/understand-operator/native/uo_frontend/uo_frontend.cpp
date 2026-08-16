// uo_frontend — one-shot libclang facts extractor.
// CLI: uo_frontend --file PATH --side host|kernel --args ARGFILE --out OUT.json
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
  std::string current_func_usr;
  std::string current_type;
  std::vector<std::string> func_stack;
  std::vector<std::string> functions;
  std::vector<std::string> call_sites;
  std::vector<std::string> controls;
  std::vector<std::string> writes;
  std::vector<std::string> local_writes;
  std::vector<std::string> diagnostics;
  std::vector<std::string> field_decls;
  std::vector<std::string> local_decls;
  std::vector<std::string> type_decls;
  std::vector<std::string> alias_decls;
  std::vector<std::string> base_decls;
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
  const char *cs = clang_getCString(sp);
  std::string p = cs ? cs : "";
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
  if (!op_root.empty() && file.find(op_root) == 0)
    return true;
  if (!needle.empty() && file.find(needle) != std::string::npos)
    return true;
  return op_root.empty() && needle.empty();
}

static std::string spelling(CXCursor cur) {
  CXString s = clang_getCursorSpelling(cur);
  const char *cs = clang_getCString(s);
  std::string out = cs ? cs : "";
  clang_disposeString(s);
  return out;
}

static std::string usr_of(CXCursor cur) {
  CXString s = clang_getCursorUSR(cur);
  const char *cs = clang_getCString(s);
  std::string out = cs ? cs : "";
  clang_disposeString(s);
  return out;
}

static std::string type_spelling(CXType t) {
  CXString s = clang_getTypeSpelling(t);
  const char *cs = clang_getCString(s);
  std::string out = cs ? cs : "";
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
    const char *cs = clang_getCString(ts);
    out += cs ? cs : "";
    clang_disposeString(ts);
  }
  clang_disposeTokens(tu, toks, n);
  return out;
}

static std::string json_str_array(const std::vector<std::string> &items) {
  std::ostringstream os;
  os << '[';
  for (size_t i = 0; i < items.size(); ++i) {
    if (i)
      os << ',';
    os << '"' << json_escape(items[i]) << '"';
  }
  os << ']';
  return os.str();
}

static CXChildVisitResult visit(CXCursor cursor, CXCursor parent, CXClientData data) {
  WalkState *st = static_cast<WalkState *>(data);
  CXTranslationUnit tu = clang_Cursor_getTranslationUnit(cursor);
  CXCursorKind kind = clang_getCursorKind(cursor);
  CXSourceLocation loc = clang_getCursorLocation(cursor);
  CXFile cxfile = nullptr;
  unsigned line = 0, col = 0, off = 0;
  clang_getExpansionLocation(loc, &cxfile, &line, &col, &off);
  std::string file = norm_path(cxfile);
  if (!file.empty() && !in_scope(file, st->needle, st->op_root) &&
      kind != CXCursor_TranslationUnit) {
    return CXChildVisit_Recurse;
  }

  if (kind == CXCursor_FunctionDecl || kind == CXCursor_CXXMethod ||
      kind == CXCursor_Constructor || kind == CXCursor_FunctionTemplate) {
    if (clang_isCursorDefinition(cursor)) {
      std::string name = spelling(cursor);
      if (!name.empty()) {
        st->func_stack.push_back(st->current_func);
        st->current_func = name;
        st->current_func_usr = usr_of(cursor);
        std::vector<std::string> params;
        int n = clang_Cursor_getNumArguments(cursor);
        for (int i = 0; i < n; ++i) {
          CXCursor p = clang_Cursor_getArgument(cursor, i);
          std::string pn = spelling(p);
          if (!pn.empty())
            params.push_back(pn);
        }
        std::ostringstream os;
        os << "{\"name\":\"" << json_escape(name) << "\",\"usr\":\""
           << json_escape(st->current_func_usr) << "\",\"file\":\""
           << json_escape(file) << "\",\"line\":" << line << ",\"params\":"
           << json_str_array(params) << "}";
        st->functions.push_back(os.str());
      }
    }
  } else if (kind == CXCursor_CallExpr || kind == CXCursor_CXXMemberCallExpr) {
    std::string callee = spelling(cursor);
    if (!callee.empty() && !st->current_func.empty()) {
      CXCursor ref = clang_getCursorReferenced(cursor);
      std::string callee_usr = usr_of(ref);
      CXFile decl_file = nullptr;
      unsigned decl_line = 0, decl_col = 0, decl_off = 0;
      clang_getExpansionLocation(clang_getCursorLocation(ref), &decl_file,
                                 &decl_line, &decl_col, &decl_off);
      std::string receiver;
      std::string receiver_type;
      std::vector<std::string> args;
      unsigned argc = clang_Cursor_getNumArguments(cursor);
      for (unsigned i = 0; i < argc; ++i) {
        CXCursor a = clang_Cursor_getArgument(cursor, i);
        std::string ts = tokens_text(tu, a, 24);
        if (!ts.empty())
          args.push_back(ts);
      }
      std::ostringstream os;
      os << "{\"caller_usr\":\"" << json_escape(st->current_func_usr)
         << "\",\"caller\":\"" << json_escape(st->current_func)
         << "\",\"callee_usr\":\"" << json_escape(callee_usr)
         << "\",\"callee\":\"" << json_escape(callee)
         << "\",\"callee_file\":\"" << json_escape(norm_path(decl_file))
         << "\",\"callee_line\":" << decl_line << ",\"receiver\":\""
         << json_escape(receiver) << "\",\"receiver_type\":\""
         << json_escape(receiver_type) << "\",\"args\":" << json_str_array(args)
         << ",\"file\":\"" << json_escape(file) << "\",\"line\":" << line
         << ",\"column\":" << col << "}";
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
    std::string op = tokens_text(tu, cursor, 8);
    if (op.find('=') != std::string::npos && op.find("==") == std::string::npos &&
        !st->current_func.empty()) {
      std::string rhs = tokens_text(tu, cursor, 32);
      std::ostringstream os;
      os << "{\"path\":\"" << json_escape(spelling(cursor)) << "\",\"line\":"
         << line << ",\"rhs\":\"" << json_escape(rhs) << "\",\"file\":\""
         << json_escape(file) << "\",\"function\":\""
         << json_escape(st->current_func) << "\",\"column\":" << col << "}";
      st->writes.push_back(os.str());
      st->local_writes.push_back(os.str());
    }
  } else if (kind == CXCursor_FieldDecl) {
    std::string name = spelling(cursor);
    if (!name.empty()) {
      st->class_fields.insert(name);
      std::string ty = type_spelling(clang_getCursorType(cursor));
      std::ostringstream os;
      os << "{\"host\":\"" << json_escape(st->current_type) << "\",\"name\":\""
         << json_escape(name) << "\",\"type_text\":\"" << json_escape(ty)
         << "\",\"file\":\"" << json_escape(file) << "\",\"line\":" << line
         << "}";
      st->field_decls.push_back(os.str());
    }
  } else if (kind == CXCursor_VarDecl) {
    std::string name = spelling(cursor);
    if (!name.empty() && !st->current_func.empty()) {
      std::ostringstream os;
      os << "{\"name\":\"" << json_escape(name) << "\",\"type_text\":\""
         << json_escape(type_spelling(clang_getCursorType(cursor)))
         << "\",\"file\":\"" << json_escape(file) << "\",\"line\":" << line
         << ",\"function\":\"" << json_escape(st->current_func) << "\"}";
      st->local_decls.push_back(os.str());
    }
  } else if (kind == CXCursor_ClassDecl || kind == CXCursor_StructDecl) {
    std::string name = spelling(cursor);
    if (!name.empty()) {
      st->current_type = name;
      std::ostringstream os;
      os << "{\"name\":\"" << json_escape(name) << "\",\"kind\":\""
         << (kind == CXCursor_ClassDecl ? "class" : "struct") << "\",\"file\":\""
         << json_escape(file) << "\",\"line\":" << line << ",\"usr\":\""
         << json_escape(usr_of(cursor)) << "\"}";
      st->type_decls.push_back(os.str());
    }
  } else if (kind == CXCursor_TypedefDecl || kind == CXCursor_TypeAliasDecl) {
    std::string name = spelling(cursor);
    if (!name.empty()) {
      CXType under = (kind == CXCursor_TypedefDecl)
                         ? clang_getTypedefDeclUnderlyingType(cursor)
                         : clang_getCursorType(cursor);
      std::ostringstream os;
      os << "{\"alias\":\"" << json_escape(name) << "\",\"target\":\""
         << json_escape(type_spelling(under)) << "\",\"file\":\""
         << json_escape(file) << "\",\"line\":" << line << "}";
      st->alias_decls.push_back(os.str());
    }
  } else if (kind == CXCursor_CXXBaseSpecifier) {
    std::ostringstream os;
    os << "{\"derived\":\"" << json_escape(st->current_type) << "\",\"base\":\""
       << json_escape(spelling(cursor)) << "\",\"file\":\"" << json_escape(file)
       << "\",\"line\":" << line << "}";
    st->base_decls.push_back(os.str());
  }

  clang_visitChildren(cursor, visit, data);

  if ((kind == CXCursor_FunctionDecl || kind == CXCursor_CXXMethod ||
       kind == CXCursor_Constructor || kind == CXCursor_FunctionTemplate) &&
      clang_isCursorDefinition(cursor) && !st->func_stack.empty()) {
    st->current_func = st->func_stack.back();
    st->func_stack.pop_back();
  }
  return CXChildVisit_Continue;
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
    *err = "usage: uo_frontend --file PATH --side host|kernel --args ARGFILE --out OUT.json";
    return false;
  }
  for (char &c : opt->op_root) {
    if (c == '\\')
      c = '/';
  }
  return true;
}

static std::vector<std::string> read_compile_args(const std::string &path) {
  std::vector<std::string> storage;
  std::ifstream in(path);
  std::string line;
  while (std::getline(in, line)) {
    while (!line.empty() && (line.back() == '\r' || line.back() == '\n'))
      line.pop_back();
    if (!line.empty())
      storage.push_back(line);
  }
  return storage;
}

static int run(const Options &opt, std::string *err) {
  std::vector<std::string> arg_storage = read_compile_args(opt.argfile);
  std::vector<const char *> clang_args;
  clang_args.reserve(arg_storage.size());
  for (auto &arg : arg_storage)
    clang_args.push_back(arg.c_str());

  CXIndex idx = clang_createIndex(0, 0);
  CXTranslationUnit tu = nullptr;
  unsigned flags = CXTranslationUnit_DetailedPreprocessingRecord;
  CXErrorCode ec = clang_parseTranslationUnit2(
      idx, opt.file.c_str(), clang_args.data(),
      static_cast<int>(clang_args.size()), nullptr, 0, flags, &tu);
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
    const char *dcs = clang_getCString(ds);
    std::ostringstream os;
    os << '[' << static_cast<int>(clang_getDiagnosticSeverity(d)) << ",\""
       << json_escape(dfname) << "\",\"" << json_escape(dcs ? dcs : "") << "\"]";
    st.diagnostics.push_back(os.str());
    clang_disposeString(ds);
    clang_disposeDiagnostic(d);
  }

  CXCursor root = clang_getTranslationUnitCursor(tu);
  clang_visitChildren(root, visit, &st);

  auto dump_list = [](std::ostringstream &json, const char *key,
                      const std::vector<std::string> &rows, bool last) {
    json << "  \"" << key << "\": [";
    for (size_t i = 0; i < rows.size(); ++i) {
      if (i)
        json << ',';
      json << rows[i];
    }
    json << (last ? "]\n" : "],\n");
  };

  std::ostringstream json;
  json << "{\n  \"schema\": \"compiler-facts/v2\",\n";
  json << "  \"path\": \"" << json_escape(opt.file) << "\",\n";
  dump_list(json, "functions", st.functions, false);
  dump_list(json, "call_sites", st.call_sites, false);
  dump_list(json, "controls", st.controls, false);
  dump_list(json, "writes", st.writes, false);
  dump_list(json, "local_writes", st.local_writes, false);
  dump_list(json, "field_decls", st.field_decls, false);
  dump_list(json, "local_decls", st.local_decls, false);
  dump_list(json, "type_decls", st.type_decls, false);
  dump_list(json, "alias_decls", st.alias_decls, false);
  dump_list(json, "base_decls", st.base_decls, false);
  dump_list(json, "diagnostics", st.diagnostics, false);
  json << "  \"macro_idioms\": 0,\n";
  json << "  \"class_fields\": [";
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
