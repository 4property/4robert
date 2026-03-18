from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import (
    DATABASE_FILENAME,
    DEFAULT_PHOTOS_TO_SELECT,
    HTTP_HEADERS,
    IMAGES_ROOT_DIRNAME,
    RAW_IMAGES_ROOT_DIRNAME,
    REQUEST_TIMEOUT_SECONDS,
    WORDPRESS_LINK,
    WORDPRESS_PER_PAGE,
)
from models.property import Property
from repositories.wordpress_property_repository import WordpressPropertyRepository

RETRYABLE_HTTP_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524}
MAX_FETCH_ATTEMPTS = 4
INITIAL_RETRY_DELAY_SECONDS = 2.0


def _build_request(url: str, *, headers: dict[str, str]) -> Request:
    return Request(url, headers=headers)


def _build_property_list_url(page: int, per_page: int) -> str:
    query_string = urlencode(
        {
            "page": page,
            "per_page": per_page,
            "orderby": "date",
            "order": "desc",
        }
    )
    return f"{WORDPRESS_LINK}?{query_string}"


def _build_property_detail_url(property_id: int) -> str:
    return f"{WORDPRESS_LINK}/{property_id}"


def _should_retry_http_error(error: HTTPError) -> bool:
    return error.code in RETRYABLE_HTTP_STATUS_CODES


def _sleep_before_retry(attempt: int) -> None:
    time.sleep(INITIAL_RETRY_DELAY_SECONDS * (2 ** (attempt - 1)))


def _find_alternative_database_paths(workspace_dir: Path, active_database_path: Path) -> list[Path]:
    return sorted(
        candidate
        for candidate in workspace_dir.glob("*.sqlite3")
        if candidate.resolve() != active_database_path
    )


def _read_json_response(url: str) -> tuple[Any, dict[str, str]]:
    for attempt in range(1, MAX_FETCH_ATTEMPTS + 1):
        try:
            with urlopen(
                _build_request(url, headers=HTTP_HEADERS),
                timeout=REQUEST_TIMEOUT_SECONDS,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
                headers = {key.lower(): value for key, value in response.headers.items()}
            return payload, headers
        except HTTPError as error:
            if not _should_retry_http_error(error) or attempt == MAX_FETCH_ATTEMPTS:
                raise RuntimeError(
                    f"WordPress request failed for {url} with HTTP {error.code}."
                ) from error
            print(
                f"WordPress request returned HTTP {error.code} "
                f"(attempt {attempt}/{MAX_FETCH_ATTEMPTS}). Retrying..."
            )
        except (TimeoutError, URLError) as error:
            if attempt == MAX_FETCH_ATTEMPTS:
                raise RuntimeError(
                    f"WordPress request failed for {url}: {error}."
                ) from error
            print(
                f"WordPress request failed "
                f"(attempt {attempt}/{MAX_FETCH_ATTEMPTS}): {error}. Retrying..."
            )

        _sleep_before_retry(attempt)

    raise RuntimeError(f"WordPress request failed for {url}.")


def _fetch_property_page(
    page: int,
    per_page: int = WORDPRESS_PER_PAGE,
) -> tuple[list[Property], int, int]:
    url = _build_property_list_url(page=page, per_page=per_page)
    payload, headers = _read_json_response(url)

    if not isinstance(payload, list):
        raise ValueError(f"Unexpected response payload for page {page}.")

    total_pages = int(headers.get("x-wp-totalpages", "1"))
    total_items = int(headers.get("x-wp-total", str(len(payload))))
    properties = [
        Property.from_api_payload(item)
        for item in payload
        if isinstance(item, dict)
    ]
    return properties, total_pages, total_items


def _iter_property_pages(
    per_page: int = WORDPRESS_PER_PAGE,
) -> Iterator[tuple[int, int, list[Property]]]:
    page = 1
    total_pages = 1

    while page <= total_pages:
        page_properties, total_pages, _ = _fetch_property_page(page=page, per_page=per_page)
        yield page, total_pages, page_properties
        page += 1


def fetch_all_properties(per_page: int = WORDPRESS_PER_PAGE) -> list[Property]:
    properties: list[Property] = []

    for page, total_pages, page_properties in _iter_property_pages(per_page=per_page):
        properties.extend(page_properties)
        print(f"Fetched page {page}/{total_pages} from WordPress.")

    return properties


def fetch_property_by_id(property_id: int) -> Property:
    payload, _ = _read_json_response(_build_property_detail_url(property_id))

    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected response payload for property {property_id}.")

    return Property.from_api_payload(payload)


def initialize_wordpress_property_database(
    base_dir: str | Path,
    per_page: int = WORDPRESS_PER_PAGE,
) -> tuple[list[Property], Path]:
    return sync_wordpress_property_data(base_dir, per_page=per_page)


def find_new_property_ids(
    base_dir: str | Path,
    per_page: int = WORDPRESS_PER_PAGE,
) -> list[int]:
    workspace_dir = Path(base_dir).expanduser().resolve()
    database_path = workspace_dir / DATABASE_FILENAME

    with WordpressPropertyRepository(database_path, workspace_dir) as repository:
        known_property_ids = repository.get_property_ids()

    new_property_ids: list[int] = []
    seen_property_ids: set[int] = set()

    for page, total_pages, page_properties in _iter_property_pages(per_page=per_page):
        page_new_ids = [
            property_item.id
            for property_item in page_properties
            if property_item.id not in known_property_ids
            and property_item.id not in seen_property_ids
        ]
        new_property_ids.extend(page_new_ids)
        seen_property_ids.update(property_item.id for property_item in page_properties)
        print(
            f"Checked page {page}/{total_pages} for missing properties. "
            f"Found {len(page_new_ids)} on this page."
        )

    return new_property_ids


def refetch_new_property_ids(
    base_dir: str | Path,
    per_page: int = WORDPRESS_PER_PAGE,
) -> list[int]:
    return find_new_property_ids(base_dir, per_page=per_page)


def find_new_property_id(
    base_dir: str | Path,
    per_page: int = WORDPRESS_PER_PAGE,
) -> int | None:
    new_property_ids = find_new_property_ids(base_dir, per_page=per_page)
    if not new_property_ids:
        return None
    return new_property_ids[0]


def refetch_new_property_id(
    base_dir: str | Path,
    per_page: int = WORDPRESS_PER_PAGE,
) -> int | None:
    return find_new_property_id(base_dir, per_page=per_page)


def refetch_wordpress_properties(
    base_dir: str | Path,
    photos_to_select: int = DEFAULT_PHOTOS_TO_SELECT,
    per_page: int = WORDPRESS_PER_PAGE,
) -> list[int]:
    workspace_dir = Path(base_dir).expanduser().resolve()
    database_path = workspace_dir / DATABASE_FILENAME
    filtered_images_root = workspace_dir / IMAGES_ROOT_DIRNAME
    raw_images_root = workspace_dir / RAW_IMAGES_ROOT_DIRNAME

    print(f"Using database: {database_path}")
    alternative_database_paths = _find_alternative_database_paths(workspace_dir, database_path)
    if alternative_database_paths:
        print(
            "Other sqlite databases found in workspace:",
            ", ".join(str(path.name) for path in alternative_database_paths),
        )
    new_property_ids = find_new_property_ids(workspace_dir, per_page=per_page)

    if not new_property_ids:
        print("No new properties found.")
        return []

    print(f"Found {len(new_property_ids)} new properties.")
    from services.wordpress_image_service import download_and_filter_property_images

    with WordpressPropertyRepository(database_path, workspace_dir) as repository:
        for index, property_id in enumerate(new_property_ids, start=1):
            property_item = fetch_property_by_id(property_id)
            print(f"[{index}/{len(new_property_ids)}] Saving {property_item.slug}...")
            repository.save_property_data(property_item)
            print(f"  Downloading raw photos and saving filtered photos for {property_item.slug}...")
            property_dir, property_images = download_and_filter_property_images(
                property_item,
                raw_images_root,
                filtered_images_root,
                photos_to_select=photos_to_select,
            )
            repository.save_property_images(
                property_item,
                property_dir,
                property_images,
            )

    print(f"Database stored in: {database_path}")
    return new_property_ids


def sync_new_wordpress_properties(
    base_dir: str | Path,
    photos_to_select: int = DEFAULT_PHOTOS_TO_SELECT,
    per_page: int = WORDPRESS_PER_PAGE,
) -> tuple[list[int], Path]:
    workspace_dir = Path(base_dir).expanduser().resolve()
    database_path = workspace_dir / DATABASE_FILENAME
    new_property_ids = refetch_wordpress_properties(
        workspace_dir,
        photos_to_select=photos_to_select,
        per_page=per_page,
    )
    return new_property_ids, database_path


def sync_wordpress_property_data(
    base_dir: str | Path,
    per_page: int = WORDPRESS_PER_PAGE,
) -> tuple[list[Property], Path]:
    workspace_dir = Path(base_dir).expanduser().resolve()
    database_path = workspace_dir / DATABASE_FILENAME

    properties = fetch_all_properties(per_page=per_page)
    print(f"Fetched {len(properties)} properties from WordPress.")

    with WordpressPropertyRepository(database_path, workspace_dir) as repository:
        for index, property_item in enumerate(properties, start=1):
            print(f"[{index}/{len(properties)}] Saving {property_item.slug}...")
            repository.save_property_data(property_item)

    print(f"Database stored in: {database_path}")
    return properties, database_path


def sync_wordpress_properties(base_dir: str | Path) -> tuple[list[Property], Path]:
    return sync_wordpress_property_data(base_dir)


__all__ = [
    "DATABASE_FILENAME",
    "WORDPRESS_LINK",
    "fetch_all_properties",
    "fetch_property_by_id",
    "find_new_property_id",
    "find_new_property_ids",
    "initialize_wordpress_property_database",
    "refetch_wordpress_properties",
    "refetch_new_property_id",
    "refetch_new_property_ids",
    "sync_new_wordpress_properties",
    "sync_wordpress_property_data",
    "sync_wordpress_properties",
]
