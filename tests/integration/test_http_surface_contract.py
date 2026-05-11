"""Contract test between frontend apiRequest calls and backend routes."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path

from scripts.generate_http_surface import build_surface_app, collect_http_routes

DEFAULT_FRONTEND_REPO_ROOT = Path("C:/Users/4pm/Desktop/4reels/4reels front")
FRONTEND_REPO_ROOT_ENV = "FRONTEND_REPO_ROOT"

PLACEHOLDER_NAMES = {
    "agencyId": "agency_id",
    "ingestionSourceId": "ingestion_source_id",
    "musicId": "music_id",
    "position": "position",
    "siteId": "site_id",
    "sourcePropertyId": "source_property_id",
    "wordpressSourceId": "ingestion_source_id",
}
ENCODED_PLACEHOLDER = re.compile(
    r"\$\{\s*encodeURIComponent\(\s*([A-Za-z_$][\w$]*)\s*,?\s*\)\s*\}",
    re.DOTALL,
)
RAW_PLACEHOLDER = re.compile(r"\$\{\s*([A-Za-z_$][\w$]*)\s*\}", re.DOTALL)
METHOD_LITERAL = re.compile(r"\bmethod\s*:\s*['\"]([A-Z]+)['\"]")


@dataclass(frozen=True, slots=True)
class FrontendApiCall:
    method: str
    path: str
    file_path: Path
    line_number: int
    expression: str


class UnsupportedApiRequest(ValueError):
    pass


def test_frontend_api_requests_target_existing_backend_routes() -> None:
    frontend_root = _frontend_repo_root()
    backend_routes = {
        (route.method, route.path) for route in collect_http_routes(build_surface_app())
    }
    calls = extract_frontend_api_calls(frontend_root)
    assert calls, f"No frontend apiRequest(...) calls found under {frontend_root / 'src'}."

    mismatches = [
        _format_mismatch(call, backend_routes)
        for call in calls
        if (call.method, call.path) not in backend_routes
    ]

    assert not mismatches, "\n".join(mismatches)


def _frontend_repo_root() -> Path:
    configured = os.environ.get(FRONTEND_REPO_ROOT_ENV)
    root = Path(configured) if configured else DEFAULT_FRONTEND_REPO_ROOT
    root = root.expanduser().resolve()
    if not root.exists():
        raise AssertionError(
            f"Frontend repo root does not exist: {root}. Set {FRONTEND_REPO_ROOT_ENV}."
        )
    if not (root / "src").exists():
        raise AssertionError(f"Frontend repo root has no src/ directory: {root}")
    return root


def extract_frontend_api_calls(frontend_root: Path) -> list[FrontendApiCall]:
    source_files = sorted((frontend_root / "src").rglob("*.js"))
    source_files.extend(sorted((frontend_root / "src").rglob("*.jsx")))
    calls: list[FrontendApiCall] = []
    errors: list[str] = []
    for file_path in source_files:
        text = file_path.read_text(encoding="utf-8-sig")
        for offset in _iter_api_request_offsets(text):
            line_number = text.count("\n", 0, offset) + 1
            try:
                content = _read_parenthesized(text, offset + len("apiRequest"))
                first_arg, rest = _split_first_argument(content)
                calls.append(
                    FrontendApiCall(
                        method=_extract_method(rest),
                        path=_normalize_first_argument(first_arg),
                        file_path=file_path.relative_to(frontend_root),
                        line_number=line_number,
                        expression=first_arg.strip(),
                    )
                )
            except UnsupportedApiRequest as error:
                relative_path = file_path.relative_to(frontend_root)
                errors.append(f"{relative_path}:{line_number}: {error}")
    if errors:
        raise AssertionError("Unsupported apiRequest expressions:\n" + "\n".join(errors))
    return calls


def _iter_api_request_offsets(text: str):
    needle = "apiRequest("
    offset = 0
    while True:
        index = text.find(needle, offset)
        if index < 0:
            return
        line_start = text.rfind("\n", 0, index) + 1
        line_end = text.find("\n", index)
        if line_end < 0:
            line_end = len(text)
        line = text[line_start:line_end]
        if "function apiRequest" not in line:
            yield index
        offset = index + len(needle)


def _read_parenthesized(text: str, open_index: int) -> str:
    if open_index >= len(text) or text[open_index] != "(":
        raise UnsupportedApiRequest("expected apiRequest(...) call")
    depth = 1
    index = open_index + 1
    quote: str | None = None
    in_template = False
    while index < len(text):
        char = text[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif in_template:
            if char == "\\":
                index += 2
                continue
            if char == "`":
                in_template = False
        elif char in {"'", '"'}:
            quote = char
        elif char == "`":
            in_template = True
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                return text[open_index + 1 : index]
        index += 1
    raise UnsupportedApiRequest("unterminated apiRequest(...) call")


def _split_first_argument(content: str) -> tuple[str, str]:
    parts = _split_top_level(content, max_splits=1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _split_top_level(value: str, *, max_splits: int | None = None) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    in_template = False
    index = 0
    while index < len(value):
        char = value[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif in_template:
            if char == "\\":
                index += 2
                continue
            if char == "`":
                in_template = False
        elif char in {"'", '"'}:
            quote = char
        elif char == "`":
            in_template = True
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
            if max_splits is not None and len(parts) >= max_splits:
                break
        index += 1
    parts.append(value[start:].strip())
    return parts


def _extract_method(rest: str) -> str:
    match = METHOD_LITERAL.search(rest)
    return match.group(1) if match else "GET"


def _normalize_first_argument(expression: str) -> str:
    expression = expression.strip()
    if expression.startswith(("'", '"')):
        return _strip_string_literal(expression)
    if expression.startswith("`"):
        return _normalize_template_literal(expression)
    if expression.startswith("musicPath("):
        return _normalize_music_path(expression)
    if expression.startswith("reelPath("):
        return _normalize_reel_path(expression)
    raise UnsupportedApiRequest(f"cannot normalize first argument `{expression}`")


def _strip_string_literal(expression: str) -> str:
    quote = expression[0]
    if not expression.endswith(quote):
        raise UnsupportedApiRequest(f"unterminated string literal `{expression}`")
    return expression[1:-1]


def _normalize_template_literal(expression: str) -> str:
    if not expression.endswith("`"):
        raise UnsupportedApiRequest(f"unterminated template literal `{expression}`")
    return _normalize_template_body(expression[1:-1])


def _normalize_template_body(body: str) -> str:
    body = ENCODED_PLACEHOLDER.sub(_replace_placeholder, body)
    body = RAW_PLACEHOLDER.sub(_replace_placeholder, body)
    if "${" in body:
        raise UnsupportedApiRequest(f"unmapped template interpolation `{body}`")
    return re.sub(r"\s+", "", body)


def _replace_placeholder(match: re.Match[str]) -> str:
    name = match.group(1)
    placeholder = PLACEHOLDER_NAMES.get(name)
    if not placeholder:
        raise UnsupportedApiRequest(f"unmapped placeholder `{name}`")
    return "{" + placeholder + "}"


def _normalize_music_path(expression: str) -> str:
    args = _parse_helper_args(expression, "musicPath")
    base = "/v1/admin/agencies/{agency_id}/music"
    if len(args) == 1:
        return base
    if len(args) == 2 and args[1] == "musicId":
        return f"{base}/{{music_id}}"
    raise UnsupportedApiRequest(f"unsupported musicPath arguments `{expression}`")


def _normalize_reel_path(expression: str) -> str:
    args = _parse_helper_args(expression, "reelPath")
    base = "/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}"
    if len(args) == 3:
        return base
    if len(args) == 4:
        return base + _strip_string_literal(args[3])
    raise UnsupportedApiRequest(f"unsupported reelPath arguments `{expression}`")


def _parse_helper_args(expression: str, helper_name: str) -> list[str]:
    prefix = f"{helper_name}("
    if not expression.startswith(prefix) or not expression.endswith(")"):
        raise UnsupportedApiRequest(f"malformed helper call `{expression}`")
    return _split_top_level(expression[len(prefix) : -1])


def _format_mismatch(
    call: FrontendApiCall,
    backend_routes: set[tuple[str, str]],
) -> str:
    same_path_methods = sorted(
        method for method, path in backend_routes if path == call.path
    )
    if same_path_methods:
        hint = f"back exposes same path with methods: {', '.join(same_path_methods)}"
    else:
        same_method_paths = sorted(
            path for method, path in backend_routes if method == call.method
        )
        closest = get_close_matches(call.path, same_method_paths, n=1, cutoff=0.45)
        hint = (
            f"closest same-method backend route: {closest[0]}"
            if closest
            else "back has no route with that path"
        )
    return (
        f"Front llama a {call.method} {call.path} pero back no expone ese contrato - "
        f"corregir {call.file_path}:{call.line_number}. {hint}."
    )
