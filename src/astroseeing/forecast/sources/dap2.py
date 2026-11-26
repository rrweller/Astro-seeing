"""A small reader for OPeNDAP (DAP 2.0) responses: ``.dods`` data and ``.das`` attributes.

Only the part of DAP 2.0 that THREDDS returns for gridded data is read: atomic
variables (scalars and arrays of the numeric types) and ``Grid``s (an array plus its map
vectors). Anything else (``Structure``, ``Sequence``, strings in the data, an error
document) raises :class:`DapFormatError`, so a format change fails loudly instead of
being misread.

The format (OPeNDAP, "The Data Access Protocol — DAP 2.0", NASA ESE-RFC-004, §§ 3.2,
7.3): a ``.dods`` body is the DDS text, a line ``Data:``, then every variable in DDS
order, XDR-encoded (big-endian). An array is its length written twice as 32-bit
unsigned integers, then its values; a scalar is its value alone; ``Byte`` arrays are
padded to a multiple of 4 bytes, and 16-bit integers are sent as 32-bit ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: DAP atomic type → (XDR dtype on the wire, bytes per value).
_XDR = {
    "Byte": (">u1", 1),
    "Int16": (">i4", 4),
    "UInt16": (">u4", 4),
    "Int32": (">i4", 4),
    "UInt32": (">u4", 4),
    "Float32": (">f4", 4),
    "Float64": (">f8", 8),
}
_DECL = re.compile(r"^(\w+)\s+([\w.]+)((?:\s*\[[^\]]*\])*)\s*;$")
_DIM = re.compile(r"\[\s*(?:([\w.]+)\s*=\s*)?(\d+)\s*\]")
_SEPARATOR = re.compile(rb"\r?\nData:\r?\n")


class DapFormatError(ValueError):
    """The response is not the part of DAP 2.0 this reader understands."""


@dataclass(frozen=True)
class DapArray:
    """One decoded array (or scalar, with no dimensions): its DAP type, its dimension
    names and sizes in order, and its values in that shape."""

    name: str
    dap_type: str
    dims: tuple[tuple[str, int], ...]
    values: np.ndarray

    @property
    def dim_names(self) -> tuple[str, ...]:
        return tuple(d for d, _ in self.dims)


@dataclass(frozen=True)
class DapVariable:
    """A top-level variable: an atomic array or scalar, or a ``Grid`` with its maps."""

    array: DapArray
    maps: dict[str, DapArray] = field(default_factory=dict)


def parse_dods(body: bytes) -> dict[str, DapVariable]:
    """Decode a ``.dods`` response into its variables, by name, in the order sent."""
    if body.lstrip().startswith(b"Error"):
        raise DapFormatError(f"the server sent an error: {_text(body[:300])}")
    m = _SEPARATOR.search(body)
    if m is None:
        raise DapFormatError("no 'Data:' line after the DDS")
    decls = parse_dds(_text(body[: m.start()]))
    data, pos = body, m.end()
    out: dict[str, DapVariable] = {}
    for name, (array, maps) in decls.items():
        decoded, pos = _decode(array, data, pos)
        decoded_maps = {}
        for mp in maps:
            decoded_maps[mp.name], pos = _decode(mp, data, pos)
        out[name] = DapVariable(decoded, decoded_maps)
    if pos != len(data):
        tail = data[pos : pos + 200]
        raise DapFormatError(f"{len(data) - pos} bytes left after the last variable: {tail!r}")
    return out


def parse_dds(text: str) -> dict[str, tuple[DapArray, list[DapArray]]]:
    """The DDS's top-level declarations: name → (array, map arrays), values empty."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines or not re.match(r"^Dataset\s*\{$", lines[0]):
        raise DapFormatError(f"not a DDS: {text[:100]!r}")
    out: dict[str, tuple[DapArray, list[DapArray]]] = {}
    i = 1
    while i < len(lines):
        line = lines[i]
        if line.startswith("}"):
            if i != len(lines) - 1:
                raise DapFormatError(f"text after the dataset's end: {lines[i + 1]!r}")
            return out
        if re.match(r"^Grid\s*\{$", line):
            i, name, array, maps = _grid(lines, i)
            out[name] = (array, maps)
            continue
        array = _decl(line)
        out[array.name] = (array, [])
        i += 1
    raise DapFormatError("the DDS does not end")


def dds_dims(text: str) -> dict[str, int]:
    """Each top-level array's first dimension size in a DDS (a scalar has none)."""
    return {name: a.dims[0][1] for name, (a, _) in parse_dds(text).items() if a.dims}


def _grid(lines: list[str], i: int) -> tuple[int, str, DapArray, list[DapArray]]:
    if lines[i + 1] != "ARRAY:":
        raise DapFormatError(f"Grid without ARRAY: {lines[i + 1]!r}")
    array = _decl(lines[i + 2])
    if lines[i + 3] != "MAPS:":
        raise DapFormatError(f"Grid without MAPS: {lines[i + 3]!r}")
    maps, j = [], i + 4
    while j < len(lines) and not lines[j].startswith("}"):
        maps.append(_decl(lines[j]))
        j += 1
    end = re.match(r"^\}\s*([\w.]+)\s*;$", lines[j]) if j < len(lines) else None
    if end is None:
        raise DapFormatError("a Grid does not end")
    if [m.name for m in maps] != list(array.dim_names):
        raise DapFormatError(f"Grid {end.group(1)}: maps {[m.name for m in maps]} do not "
                             f"match its dimensions {list(array.dim_names)}")  # fmt: skip
    return j + 1, end.group(1), array, maps


def _decl(line: str) -> DapArray:
    m = _DECL.match(line)
    if m is None or m.group(1) not in _XDR:
        raise DapFormatError(f"unsupported declaration {line!r}")
    dims = tuple((d or f"dim{k}", int(n)) for k, (d, n) in enumerate(_DIM.findall(m.group(3))))
    return DapArray(m.group(2), m.group(1), dims, np.empty(0))


def _decode(decl: DapArray, data: bytes, pos: int) -> tuple[DapArray, int]:
    dtype, size = _XDR[decl.dap_type]
    shape = tuple(n for _, n in decl.dims)
    count = int(np.prod(shape)) if shape else 1
    if shape:
        if pos + 8 > len(data):
            raise DapFormatError(f"{decl.name}: the data ends before its length")
        n1, n2 = np.frombuffer(data, ">u4", 2, pos)
        if n1 != n2 or n1 != count:
            raise DapFormatError(f"{decl.name}: length {n1}/{n2}, expected {count} {shape}")
        pos += 8
    nbytes = count * size
    if pos + nbytes > len(data):
        raise DapFormatError(f"{decl.name}: the data ends before its {count} values")
    values = np.frombuffer(data, dtype, count, pos).reshape(shape)
    pos += nbytes + ((-nbytes) % 4 if decl.dap_type == "Byte" else 0)
    return DapArray(decl.name, decl.dap_type, decl.dims, values), pos


def parse_das(text: str) -> dict[str, dict[str, Any]]:
    """A ``.das`` response's attributes: container name → attribute name → value (a
    number or string, or a tuple of them when several are given). Nested containers
    become nested dicts."""
    tokens = re.findall(r'"(?:[^"\\]|\\.)*"|[{};,]|[^\s{};,"]+', text)
    if tokens[:2] != ["Attributes", "{"]:
        raise DapFormatError(f"not a DAS: {text[:100]!r}")
    out, pos = _container(tokens, 2)
    if pos != len(tokens):
        raise DapFormatError(f"text after the attributes' end: {tokens[pos : pos + 5]}")
    return out


def _container(tokens: list[str], pos: int) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    while pos < len(tokens):
        tok = tokens[pos]
        if tok == "}":
            return out, pos + 1
        if pos + 1 < len(tokens) and tokens[pos + 1] == "{":
            out[tok], pos = _container(tokens, pos + 2)
            continue
        if pos + 2 >= len(tokens):
            break
        kind, name, pos = tok, tokens[pos + 1], pos + 2
        values = []
        while pos < len(tokens) and tokens[pos] != ";":
            if tokens[pos] != ",":
                values.append(_attr_value(kind, tokens[pos]))
            pos += 1
        out[name] = values[0] if len(values) == 1 else tuple(values)
        pos += 1
    raise DapFormatError("the DAS does not end")


def _attr_value(kind: str, tok: str) -> Any:
    if tok.startswith('"'):
        return re.sub(r"\\(.)", r"\1", tok[1:-1])
    if kind in ("String", "Url"):
        return tok
    try:
        return float(tok) if kind.startswith("Float") else int(tok)
    except ValueError as e:
        raise DapFormatError(f"attribute value {tok!r} is not a {kind}") from e


def _text(b: bytes) -> str:
    return b.decode("utf-8", errors="replace")
