"""TOML helpers: stdlib tomllib for reading, a tiny writer for our own files."""

from __future__ import annotations

import copy
import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    pass


def load(path: str | os.PathLike) -> dict[str, Any]:
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def load_if_exists(path: str | os.PathLike) -> dict[str, Any]:
    return load(path) if os.path.exists(path) else {}


def deep_merge(base: dict, override: dict) -> dict:
    """Return a new dict: `override` merged into `base`, tables recursively."""
    out = copy.deepcopy(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], val)
        else:
            out[key] = copy.deepcopy(val)
    return out


_BARE = re.compile(r"^[A-Za-z0-9_-]+$")


def _key(k: str) -> str:
    return k if _BARE.match(k) else json.dumps(k)


def _value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    if isinstance(v, dict):
        if not v:
            return "{}"
        return "{ " + ", ".join(f"{_key(k)} = {_value(x)}" for k, x in v.items()) + " }"
    if v is None:
        return '""'
    raise TypeError(f"cannot write {type(v).__name__} to TOML")


def dumps(data: dict[str, Any], _prefix: str = "") -> str:
    """Serialise nested dicts: scalars first, then one [table] per sub-dict."""
    scalars = [(k, v) for k, v in data.items() if not (isinstance(v, dict) and v)]
    tables = [(k, v) for k, v in data.items() if isinstance(v, dict) and v]
    chunks: list[str] = []
    if scalars:
        chunks.append("\n".join(f"{_key(k)} = {_value(v)}" for k, v in scalars))
    for k, v in tables:
        name = f"{_prefix}.{_key(k)}" if _prefix else _key(k)
        body = dumps(v, name)
        chunks.append(f"[{name}]" + ("\n" + body if body else ""))
    return "\n\n".join(chunks)


def save(path: str | os.PathLike, data: dict[str, Any], header: str = "") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (header.rstrip() + "\n\n" if header else "") + dumps(data).strip() + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
