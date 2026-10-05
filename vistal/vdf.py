"""Parser for Valve's text KeyValues (.vdf/.acf) format."""

from __future__ import annotations

from typing import Any


class VDFError(Exception):
    pass


def _tokens(text: str):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c == "/" and text.startswith("//", i):
            nl = text.find("\n", i)
            i = n if nl < 0 else nl + 1
        elif c in "{}":
            yield c
            i += 1
        elif c == '"':
            i += 1
            buf = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    nxt = text[i + 1]
                    buf.append({"n": "\n", "t": "\t", "\\": "\\", '"': '"'}.get(nxt, "\\" + nxt))
                    i += 2
                    continue
                buf.append(text[i])
                i += 1
            if i >= n:
                raise VDFError("unterminated string")
            i += 1
            yield ("s", "".join(buf))
        else:
            start = i
            while i < n and not text[i].isspace() and text[i] not in '{}"':
                i += 1
            yield ("s", text[start:i])


def loads(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack = [root]
    key: str | None = None
    for tok in _tokens(text):
        if tok == "{":
            if key is None:
                raise VDFError("block without key")
            child: dict[str, Any] = {}
            stack[-1][key] = child
            stack.append(child)
            key = None
        elif tok == "}":
            if len(stack) == 1:
                raise VDFError("unbalanced }")
            stack.pop()
            key = None
        else:
            val = tok[1]
            if key is None:
                key = val
            else:
                stack[-1][key] = val
                key = None
    return root


def load(path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return loads(fh.read())


def get_ci(d: dict[str, Any], key: str, default=None):
    """Case-insensitive lookup (Valve files are not consistent about case)."""
    if key in d:
        return d[key]
    low = key.lower()
    for k, v in d.items():
        if k.lower() == low:
            return v
    return default
