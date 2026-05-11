"""Shared helpers for configuration repositories."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping


def isoformat(value: object | None) -> str | None:
    if value is None:
        return None
    isoformat_method = getattr(value, "isoformat", None)
    if callable(isoformat_method):
        return str(isoformat_method())
    return str(value)


def normalize_text_tuple(value: Iterable[Any] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def list_param(value: Iterable[Any] | None) -> list[str]:
    return list(normalize_text_tuple(value))


def jsonb_to_mapping(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(bytes(raw).decode("utf-8"))
    if isinstance(raw, str):
        return json.loads(raw) if raw.strip() else {}
    return dict(raw)


def mapping_to_jsonb(value: Mapping[str, Any] | None) -> str:
    return json.dumps(dict(value or {}), separators=(",", ":"))


__all__ = [
    "isoformat",
    "jsonb_to_mapping",
    "list_param",
    "mapping_to_jsonb",
    "normalize_text_tuple",
]
