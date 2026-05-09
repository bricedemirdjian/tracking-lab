"""AI-like recovery: when the expected JSON path returns None/0/garbage, walk
the response tree looking for a value that *looks like* what we wanted.

This is the analogue of "find by label proximity" in the Playwright monitor —
but for JSON shapes. Instead of looking for a label in the DOM, we look for
keys whose names match aliases of the field we want, and whose values match
the expected type.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from . import core


def _walk(obj: Any, prefix: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield prefix + k, v
            if isinstance(v, (dict, list)):
                yield from _walk(v, prefix + k + ".")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield f"{prefix}[{i}]", v
            if isinstance(v, (dict, list)):
                yield from _walk(v, f"{prefix}[{i}].")


def _matches_type(value: Any, type_: str) -> bool:
    if type_ in ("number", "signed_number"):
        return isinstance(value, (int, float))
    if type_ == "percent":
        return isinstance(value, (int, float)) and 0 <= value <= 100
    if type_ in ("string", "url", "iso_date"):
        return isinstance(value, str) and bool(value.strip())
    return value is not None


def find_by_aliases(response: Any, aliases: Iterable[str], type_: str = "number") -> Optional[tuple[str, Any]]:
    """Walk the response, return (path, value) where the leaf key matches one
    of the aliases (case-insensitive substring) AND the value matches the type.

    Prefers shorter paths (= more canonical, less buried in nested sections).
    """
    aliases_lower = [a.lower() for a in aliases]
    candidates: list[tuple[int, str, Any]] = []
    for path, value in _walk(response):
        leaf = path.rsplit(".", 1)[-1].lower().strip("[0123456789]")
        if any(a in leaf for a in aliases_lower) and _matches_type(value, type_):
            candidates.append((path.count("."), path, value))
    if not candidates:
        return None
    candidates.sort()
    _, path, value = candidates[0]
    return path, value


def recover(platform: str, field_name: str, response: Any, spec) -> Optional[Any]:
    """If the static path failed, try aliases. If found, persist learning."""
    if not spec.aliases:
        return None
    found = find_by_aliases(response, spec.aliases, spec.type)
    if not found:
        core.warn("recovery_failed", platform=platform, field=field_name, aliases=spec.aliases)
        return None
    path, value = found
    core.info("recovery_success", platform=platform, field=field_name, path=path, value=value)
    core.remember_path(platform, field_name, path)
    return value
