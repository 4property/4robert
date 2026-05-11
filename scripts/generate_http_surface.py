"""Generate the documented FastAPI HTTP surface artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from fastapi.routing import APIRoute

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.api.app_factory import build_api_app  # noqa: E402

HTTP_METHOD_ORDER = {
    "GET": 0,
    "POST": 1,
    "PUT": 2,
    "PATCH": 3,
    "DELETE": 4,
}
IGNORED_METHODS = {"HEAD", "OPTIONS"}


@dataclass(frozen=True, slots=True)
class HttpRoute:
    method: str
    path: str
    tag: str
    handler_name: str
    module: str


def build_surface_app() -> FastAPI:
    """Build the API app with docs enabled and auth bypassed for introspection."""
    return build_api_app(
        workspace_dir=PROJECT_ROOT,
        admin_api_disable_auth_for_testing=True,
        enable_docs=True,
        security_disabled=True,
        site_secrets={"example-estate.ie": "change-me"},
        gohighlevel_app_shared_secret="surface-generation-secret",
    )


def collect_http_routes(app: FastAPI) -> list[HttpRoute]:
    rows: list[HttpRoute] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = sorted(
            (route.methods or set()) - IGNORED_METHODS,
            key=lambda method: (HTTP_METHOD_ORDER.get(method, 99), method),
        )
        tag = ", ".join(str(tag) for tag in route.tags) if route.tags else "-"
        endpoint = route.endpoint
        for method in methods:
            rows.append(
                HttpRoute(
                    method=method,
                    path=route.path,
                    tag=tag,
                    handler_name=getattr(endpoint, "__name__", "<unknown>"),
                    module=getattr(endpoint, "__module__", "<unknown>"),
                )
            )
    return sorted(rows, key=lambda row: (row.path, row.method, row.handler_name))


def render_http_surface_markdown(rows: list[HttpRoute]) -> str:
    lines = [
        "# HTTP surface",
        "",
        "Generated from the real FastAPI app with:",
        "",
        "```bash",
        "python scripts/generate_http_surface.py --write",
        "```",
        "",
        f"Total routes: {len(rows)}",
        "",
        "| Method | Path | Tag | Handler | Module |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| "
            f"{row.method} | `{row.path}` | {escape_cell(row.tag)} | "
            f"`{row.handler_name}` | `{row.module}` |"
        )
    lines.append("")
    return "\n".join(lines)


def escape_cell(value: str) -> str:
    return value.replace("|", "\\|")


def write_artifacts(*, docs_dir: Path | None = None) -> None:
    resolved_docs_dir = docs_dir or PROJECT_ROOT / "docs"
    app = build_surface_app()
    rows = collect_http_routes(app)
    http_surface_path = resolved_docs_dir / "http_surface.md"
    openapi_path = resolved_docs_dir / "openapi.json"
    http_surface_path.write_text(
        render_http_surface_markdown(rows),
        encoding="utf-8",
    )
    openapi_path.write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write docs/http_surface.md and docs/openapi.json.",
    )
    args = parser.parse_args(argv)
    if args.write:
        write_artifacts()
        return 0
    print(render_http_surface_markdown(collect_http_routes(build_surface_app())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
