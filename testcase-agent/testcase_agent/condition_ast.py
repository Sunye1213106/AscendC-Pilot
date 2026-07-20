"""C-subset parser for kernel branch conditions from Understand KB."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ParseError(RuntimeError):
    pass


@dataclass
class Token:
    kind: str
    value: str
    pos: int


def tokenize(text: str) -> list[Token]:
    s = str(text or "")
    i = 0
    n = len(s)
    out: list[Token] = []
    while i < n:
        ch = s[i]
        if ch.isspace():
            i += 1
            continue
        if s.startswith("&&", i):
            out.append(Token("AND", "&&", i))
            i += 2
            continue
        if s.startswith("||", i):
            out.append(Token("OR", "||", i))
            i += 2
            continue
        if s.startswith("==", i):
            out.append(Token("EQ", "==", i))
            i += 2
            continue
        if s.startswith("!=", i):
            out.append(Token("NE", "!=", i))
            i += 2
            continue
        if s.startswith("<=", i):
            out.append(Token("LE", "<=", i))
            i += 2
            continue
        if s.startswith(">=", i):
            out.append(Token("GE", ">=", i))
            i += 2
            continue
        if ch == "<":
            out.append(Token("LT", "<", i))
            i += 1
            continue
        if ch == ">":
            out.append(Token("GT", ">", i))
            i += 1
            continue
        if ch == "!":
            out.append(Token("NOT", "!", i))
            i += 1
            continue
        if ch == "(":
            out.append(Token("LP", "(", i))
            i += 1
            continue
        if ch == ")":
            out.append(Token("RP", ")", i))
            i += 1
            continue
        if ch == ",":
            out.append(Token("COMMA", ",", i))
            i += 1
            continue
        if ch == "+":
            out.append(Token("PLUS", "+", i))
            i += 1
            continue
        if ch == "-":
            # Unary minus handled in parser; binary minus here when not starting a number.
            if i + 1 < n and s[i + 1].isdigit() and (not out or out[-1].kind in {"LP", "PLUS", "MINUS", "STAR", "SLASH", "PERCENT", "AND", "OR", "NOT", "EQ", "NE", "LT", "LE", "GT", "GE", "COMMA"}):
                j = i + 1
                while j < n and (s[j].isdigit() or s[j] == "."):
                    j += 1
                out.append(Token("NUMBER", s[i:j], i))
                i = j
                continue
            out.append(Token("MINUS", "-", i))
            i += 1
            continue
        if ch == "*":
            out.append(Token("STAR", "*", i))
            i += 1
            continue
        if ch == "/":
            out.append(Token("SLASH", "/", i))
            i += 1
            continue
        if ch == "%":
            out.append(Token("PERCENT", "%", i))
            i += 1
            continue
        if ch in {"'", '"'}:
            quote = ch
            j = i + 1
            while j < n and s[j] != quote:
                j += 1
            if j >= n:
                raise ParseError(f"unterminated string at {i}")
            out.append(Token("STRING", s[i + 1 : j], i))
            i = j + 1
            continue
        if ch.isdigit():
            j = i + 1
            while j < n and (s[j].isdigit() or s[j] == "."):
                j += 1
            out.append(Token("NUMBER", s[i:j], i))
            i = j
            continue
        if ch.isalpha() or ch in {"_", "~"}:
            j = i + 1
            while j < n:
                if s.startswith("::", j):
                    j += 2
                    continue
                if s.startswith("->", j):
                    j += 2
                    continue
                if s[j] == ".":
                    j += 1
                    continue
                if s[j].isalnum() or s[j] == "_":
                    j += 1
                    continue
                break
            # Template junk: IsSameType<T, float>::value — consume <...> if present.
            # Do not treat comparison digraphs (<=, <<) as template open.
            ident = s[i:j]
            if j < n and s[j] == "<" and not (j + 1 < n and s[j + 1] in {"=", "<"}):
                depth = 1
                k = j + 1
                while k < n and depth:
                    if s[k] == "<":
                        depth += 1
                    elif s[k] == ">":
                        depth -= 1
                    k += 1
                # optional ::value
                m = 0
                if s[k:].startswith("::"):
                    m = 2
                    while k + m < n and (s[k + m].isalnum() or s[k + m] == "_"):
                        m += 1
                ident = s[i : k + m]
                j = k + m
            # Array index: foo[bar] — keep as part of ident for atom binding
            while j < n and s[j] == "[":
                depth = 1
                k = j + 1
                while k < n and depth:
                    if s[k] == "[":
                        depth += 1
                    elif s[k] == "]":
                        depth -= 1
                    k += 1
                ident = s[i:k]
                j = k
            out.append(Token("IDENT", ident, i))
            i = j
            continue
        # Skip unknown single chars that often appear in truncated KB conditions
        if ch in {";", "{", "}", "[", "]", "#"}:
            raise ParseError(f"unsupported character {ch!r} at {i}")
        raise ParseError(f"unexpected character {ch!r} at {i}")
    out.append(Token("EOF", "", i))
    return out


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.i = 0

    def peek(self) -> Token:
        return self.tokens[self.i]

    def bump(self) -> Token:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def parse(self) -> dict[str, Any]:
        node = self.parse_or()
        if self.peek().kind != "EOF":
            raise ParseError(f"trailing tokens near {self.peek().value!r}")
        return node

    def parse_or(self) -> dict[str, Any]:
        left = self.parse_and()
        while self.peek().kind == "OR":
            self.bump()
            right = self.parse_and()
            left = {"op": "or", "args": _flatten("or", left, right)}
        return left

    def parse_and(self) -> dict[str, Any]:
        left = self.parse_not()
        while self.peek().kind == "AND":
            self.bump()
            right = self.parse_not()
            left = {"op": "and", "args": _flatten("and", left, right)}
        return left

    def parse_not(self) -> dict[str, Any]:
        if self.peek().kind == "NOT":
            self.bump()
            return {"op": "not", "arg": self.parse_not()}
        return self.parse_cmp()

    def parse_cmp(self) -> dict[str, Any]:
        left = self.parse_add()
        kind = self.peek().kind
        if kind in {"EQ", "NE", "LT", "LE", "GT", "GE"}:
            op_tok = self.bump()
            right = self.parse_add()
            op_map = {"EQ": "eq", "NE": "ne", "LT": "lt", "LE": "le", "GT": "gt", "GE": "ge"}
            return {"op": op_map[op_tok.kind], "lhs": left, "rhs": right}
        return left

    def parse_add(self) -> dict[str, Any]:
        left = self.parse_mul()
        while self.peek().kind in {"PLUS", "MINUS"}:
            op_tok = self.bump()
            right = self.parse_mul()
            left = {"op": "add" if op_tok.kind == "PLUS" else "sub", "args": [left, right]}
        return left

    def parse_mul(self) -> dict[str, Any]:
        left = self.parse_unary_arith()
        while self.peek().kind in {"STAR", "SLASH", "PERCENT"}:
            op_tok = self.bump()
            right = self.parse_unary_arith()
            op = {"STAR": "mul", "SLASH": "div", "PERCENT": "mod"}[op_tok.kind]
            left = {"op": op, "args": [left, right]}
        return left

    def parse_unary_arith(self) -> dict[str, Any]:
        if self.peek().kind == "MINUS":
            self.bump()
            return {"op": "sub", "args": [{"op": "lit", "value": 0}, self.parse_unary_arith()]}
        if self.peek().kind == "PLUS":
            self.bump()
            return self.parse_unary_arith()
        return self.parse_primary()

    def parse_primary(self) -> dict[str, Any]:
        tok = self.peek()
        if tok.kind == "LP":
            self.bump()
            node = self.parse_or()
            if self.peek().kind != "RP":
                raise ParseError("expected ')'")
            self.bump()
            return node
        if tok.kind == "IDENT":
            name = self.bump().value
            if name in {"unlikely", "likely"} and self.peek().kind == "LP":
                self.bump()
                inner = self.parse_or()
                if self.peek().kind != "RP":
                    raise ParseError(f"expected ')' after {name}")
                self.bump()
                return {"op": "wrap", "name": name, "arg": inner}
            if name.startswith("static_cast") and self.peek().kind == "LP":
                self.bump()
                inner = self.parse_or()
                if self.peek().kind != "RP":
                    raise ParseError("expected ')' after static_cast")
                self.bump()
                return {"op": "wrap", "name": "static_cast", "arg": inner}
            if self.peek().kind == "LP":
                self.bump()
                args: list[dict[str, Any]] = []
                if self.peek().kind != "RP":
                    args.append(self.parse_or())
                    while self.peek().kind == "COMMA":
                        self.bump()
                        args.append(self.parse_or())
                if self.peek().kind != "RP":
                    raise ParseError("expected ')' in call")
                self.bump()
                return {"op": "call", "name": name, "args": args}
            return {"op": "name", "name": name}
        if tok.kind == "NUMBER":
            raw = self.bump().value
            if "." in raw:
                return {"op": "lit", "value": float(raw)}
            return {"op": "lit", "value": int(raw)}
        if tok.kind == "STRING":
            return {"op": "lit", "value": self.bump().value}
        raise ParseError(f"unexpected token {tok.kind} ({tok.value!r})")


def parse_condition(text: str) -> dict[str, Any]:
    """Parse condition string into AST. Raises ParseError on failure."""
    cleaned = _preprocess(text)
    if not cleaned.strip():
        raise ParseError("empty condition")
    tokens = tokenize(cleaned)
    return _Parser(tokens).parse()


def try_parse_condition(text: str) -> tuple[dict[str, Any] | None, str]:
    try:
        return parse_condition(text), ""
    except ParseError as exc:
        return None, str(exc)


def _preprocess(text: str) -> str:
    s = str(text or "").strip()
    # Truncated KB conditions often end mid-token; keep as-is for parse fail.
    # Normalize C++ bools.
    return s


def _flatten(op: str, left: dict[str, Any], right: dict[str, Any]) -> list[dict[str, Any]]:
    args: list[dict[str, Any]] = []
    for node in (left, right):
        if node.get("op") == op and isinstance(node.get("args"), list):
            args.extend(node["args"])
        else:
            args.append(node)
    return args
