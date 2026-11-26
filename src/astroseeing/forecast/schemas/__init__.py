"""Machine-checkable schemas for the files the F1 page reads (spec Module 7).

The schemas are JSON Schema (draft 2020-12) files beside this module, so Python
tests, the publisher and the page's own tests all read the same files:

- ``f1-latest-1.schema.json``: ``latest.json`` (``"schema": "f1-latest/1"``);
- ``f1-place-1.schema.json``: the per-place file (``"schema": "f1-place/1"``).

:func:`validate` checks a document with a small built-in validator for the subset
of keywords these schemas use (D71: no new dependency). Any other keyword is refused
when the schema is read, so a schema can never be silently half-checked. Numbers must
be finite: a NaN or infinity in a page file is an error, never a value.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

SCHEMA_DIR = Path(__file__).resolve().parent

#: Schema name (the document's own ``"schema"`` value) → file beside this module.
SCHEMA_FILES = {
    "f1-latest/1": "f1-latest-1.schema.json",
    "f1-place/1": "f1-place-1.schema.json",
}

_ANNOTATIONS = {"$schema", "$id", "$comment", "title", "description", "$defs"}
_CHECKED = {
    "type", "properties", "required", "additionalProperties", "propertyNames", "items",
    "minItems", "maxItems", "enum", "const", "pattern", "minLength", "minimum", "maximum",
    "exclusiveMinimum", "exclusiveMaximum", "anyOf", "$ref",
}  # fmt: skip


class SchemaError(ValueError):
    """A schema is unknown, or uses something the validator does not check."""


class SchemaViolation(ValueError):
    """A document does not match its schema; ``errors`` lists every problem found."""

    def __init__(self, schema: str, errors: list[str]):
        super().__init__(f"{schema}: {len(errors)} problem(s):\n  " + "\n  ".join(errors))
        self.schema = schema
        self.errors = errors


def schema_path(name: str) -> Path:
    if name not in SCHEMA_FILES:
        raise SchemaError(f"no schema {name!r}; known: {sorted(SCHEMA_FILES)}")
    return SCHEMA_DIR / SCHEMA_FILES[name]


@cache
def load_schema(name: str) -> Mapping[str, Any]:
    schema = json.loads(schema_path(name).read_text())
    _check_keywords(schema, "#")
    return schema


def validate(document: Any, schema: str | None = None) -> None:
    """Raise :class:`SchemaViolation` unless ``document`` matches its schema.

    ``schema`` defaults to the document's own ``"schema"`` value.
    """
    if schema is None:
        schema = document.get("schema") if isinstance(document, Mapping) else None
        if not isinstance(schema, str):
            raise SchemaError('the document names no schema (no "schema" string)')
    errors = check_document(document, load_schema(schema))
    if errors:
        raise SchemaViolation(schema, errors)


def check_document(document: Any, schema: Mapping[str, Any]) -> list[str]:
    """Every way ``document`` fails ``schema`` (empty if it matches)."""
    _check_keywords(schema, "#")
    return _Validator(schema).errors(document, schema, "$")


def _check_keywords(schema: Any, where: str) -> None:
    if not isinstance(schema, Mapping):
        if isinstance(schema, bool):
            return
        raise SchemaError(f"{where}: a schema must be an object or a boolean")
    unknown = sorted(set(schema) - _ANNOTATIONS - _CHECKED)
    if unknown:
        raise SchemaError(f"{where}: keyword(s) {unknown} are not checked by this validator")
    for key in ("properties", "$defs"):
        for name, sub in schema.get(key, {}).items():
            _check_keywords(sub, f"{where}/{key}/{name}")
    for key in ("items", "additionalProperties", "propertyNames"):
        if key in schema:
            _check_keywords(schema[key], f"{where}/{key}")
    for i, sub in enumerate(schema.get("anyOf", [])):
        _check_keywords(sub, f"{where}/anyOf/{i}")


class _Validator:
    def __init__(self, root: Mapping[str, Any]):
        self.root = root

    def resolve(self, ref: str) -> Mapping[str, Any]:
        if not ref.startswith("#/$defs/"):
            raise SchemaError(f"only local '#/$defs/...' references are supported, got {ref!r}")
        try:
            return self.root["$defs"][ref.removeprefix("#/$defs/")]
        except KeyError as e:
            raise SchemaError(f"unresolved reference {ref!r}") from e

    def errors(self, value: Any, schema: Any, path: str) -> list[str]:
        if schema is True:
            return []
        if schema is False:
            return [f"{path}: no value is allowed here"]
        if "$ref" in schema:
            return self.errors(value, self.resolve(schema["$ref"]), path)
        if "anyOf" in schema:
            return self._any_of(value, schema["anyOf"], path)
        if "const" in schema and not _same(value, schema["const"]):
            return [f"{path}: must be {schema['const']!r}, got {value!r}"]
        if "enum" in schema and not any(_same(value, e) for e in schema["enum"]):
            return [f"{path}: must be one of {schema['enum']}, got {value!r}"]
        if "type" in schema:
            types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            if not any(_is_type(value, t) for t in types):
                return [f"{path}: must be {' or '.join(types)}, got {value!r}"]
        out: list[str] = []
        if isinstance(value, str):
            if "pattern" in schema and not re.search(schema["pattern"], value):
                out.append(f"{path}: {value!r} does not match {schema['pattern']!r}")
            if "minLength" in schema and len(value) < schema["minLength"]:
                out.append(f"{path}: shorter than {schema['minLength']} characters")
        if _is_type(value, "number"):
            for key, ok in (("minimum", lambda v, b: v >= b), ("maximum", lambda v, b: v <= b),
                            ("exclusiveMinimum", lambda v, b: v > b),
                            ("exclusiveMaximum", lambda v, b: v < b)):  # fmt: skip
                if key in schema and not ok(value, schema[key]):
                    out.append(f"{path}: {value!r} fails {key} {schema[key]!r}")
        if isinstance(value, list):
            if "minItems" in schema and len(value) < schema["minItems"]:
                out.append(f"{path}: {len(value)} items, at least {schema['minItems']} needed")
            if "maxItems" in schema and len(value) > schema["maxItems"]:
                out.append(f"{path}: {len(value)} items, at most {schema['maxItems']} allowed")
            if "items" in schema:
                for i, item in enumerate(value):
                    out += self.errors(item, schema["items"], f"{path}[{i}]")
        if isinstance(value, Mapping):
            out += self._object(value, schema, path)
        return out

    def _object(self, value: Mapping, schema: Mapping, path: str) -> list[str]:
        out = [f"{path}: missing required key {key!r}"
               for key in schema.get("required", []) if key not in value]  # fmt: skip
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, sub_value in value.items():
            sub_path = f"{path}.{key}"
            if "propertyNames" in schema:
                out += [f"{path}: key {key!r}: {e.split(': ', 1)[1]}"
                        for e in self.errors(key, schema["propertyNames"], sub_path)]  # fmt: skip
            if key in props:
                out += self.errors(sub_value, props[key], sub_path)
            elif extra is False:
                out.append(f"{path}: unexpected key {key!r}")
            else:
                out += self.errors(sub_value, extra, sub_path)
        return out

    def _any_of(self, value: Any, options: list, path: str) -> list[str]:
        results = [self.errors(value, option, path) for option in options]
        if any(not r for r in results):
            return []
        closest = min(results, key=len)
        return [f"{path}: matches none of the {len(options)} allowed forms; closest: "
                + "; ".join(closest)]  # fmt: skip


def _is_type(value: Any, t: str) -> bool:
    if t == "null":
        return value is None
    if t == "boolean":
        return isinstance(value, bool)
    if t in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, int | float):
            return False
        if not math.isfinite(value):
            return False
        return t == "number" or float(value).is_integer()
    if t == "string":
        return isinstance(value, str)
    if t == "array":
        return isinstance(value, list)
    if t == "object":
        return isinstance(value, Mapping)
    raise SchemaError(f"unknown type {t!r}")


def _same(a: Any, b: Any) -> bool:
    """JSON equality: 1 == 1.0, but true is not 1."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return a == b
