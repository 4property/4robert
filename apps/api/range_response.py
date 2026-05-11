"""HTTP `Range` request handling for streamed file responses."""

from __future__ import annotations

import secrets as _secrets
from collections.abc import Iterator
from pathlib import Path

from fastapi import Request, Response
from fastapi.responses import StreamingResponse

VIDEO_STREAM_CHUNK_SIZE = 1024 * 1024  # 1 MiB per buffered chunk

DEFAULT_VIDEO_MEDIA_TYPE = "video/mp4"
DEFAULT_CACHE_CONTROL = "private, max-age=300"


def _parse_byte_ranges(
    range_header: str,
    *,
    file_size: int,
) -> list[tuple[int, int]] | None:
    """Parse a `Range: bytes=...` header.

    Returns a list of `(start, end)` inclusive ranges, or `None` if the header
    is unsatisfiable / malformed (the caller should reply 416).
    """
    if not range_header.startswith("bytes="):
        return None
    spec = range_header[len("bytes=") :].strip()
    if not spec:
        return None
    parsed: list[tuple[int, int]] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk or "-" not in chunk:
            return None
        start_text, _, end_text = chunk.partition("-")
        start_text = start_text.strip()
        end_text = end_text.strip()
        try:
            if start_text == "" and end_text != "":
                # Suffix range: last N bytes.
                suffix_length = int(end_text)
                if suffix_length <= 0:
                    return None
                start = max(file_size - suffix_length, 0)
                end = file_size - 1
            elif start_text != "":
                start = int(start_text)
                end = int(end_text) if end_text != "" else file_size - 1
            else:
                return None
        except ValueError:
            return None
        if start < 0 or end >= file_size or start > end:
            return None
        parsed.append((start, end))
    if not parsed:
        return None
    return parsed


def _iter_file_range(
    file_path: Path,
    *,
    start: int,
    end: int,
    chunk_size: int = VIDEO_STREAM_CHUNK_SIZE,
) -> Iterator[bytes]:
    length = (end - start) + 1
    with file_path.open("rb") as handle:
        handle.seek(start)
        remaining = length
        while remaining > 0:
            block = handle.read(min(chunk_size, remaining))
            if not block:
                break
            remaining -= len(block)
            yield block


def _iter_full_file(file_path: Path, *, chunk_size: int = VIDEO_STREAM_CHUNK_SIZE) -> Iterator[bytes]:
    with file_path.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            yield block


def _build_multipart_iterator(
    file_path: Path,
    *,
    ranges: list[tuple[int, int]],
    file_size: int,
    media_type: str,
    boundary: str,
    chunk_size: int = VIDEO_STREAM_CHUNK_SIZE,
) -> Iterator[bytes]:
    boundary_marker = f"--{boundary}".encode("ascii")
    closing_marker = f"--{boundary}--".encode("ascii")
    for start, end in ranges:
        yield boundary_marker + b"\r\n"
        yield f"Content-Type: {media_type}\r\n".encode("ascii")
        yield f"Content-Range: bytes {start}-{end}/{file_size}\r\n\r\n".encode("ascii")
        yield from _iter_file_range(file_path, start=start, end=end, chunk_size=chunk_size)
        yield b"\r\n"
    yield closing_marker + b"\r\n"


def _multipart_content_length(
    *,
    ranges: list[tuple[int, int]],
    file_size: int,
    media_type: str,
    boundary: str,
) -> int:
    boundary_marker = f"--{boundary}".encode("ascii")
    closing_marker = f"--{boundary}--".encode("ascii")
    total = 0
    for start, end in ranges:
        body_length = (end - start) + 1
        total += len(boundary_marker) + 2  # \r\n
        total += len(f"Content-Type: {media_type}\r\n".encode("ascii"))
        total += len(f"Content-Range: bytes {start}-{end}/{file_size}\r\n\r\n".encode("ascii"))
        total += body_length
        total += 2  # \r\n after part body
    total += len(closing_marker) + 2
    return total


def build_range_response(
    request: Request,
    file_path: Path,
    *,
    media_type: str = DEFAULT_VIDEO_MEDIA_TYPE,
    cache_control: str = DEFAULT_CACHE_CONTROL,
    chunk_size: int = VIDEO_STREAM_CHUNK_SIZE,
) -> Response:
    """Send `file_path` honouring the `Range` request header.

    HTML5 `<video>` players send a `Range` request to seek and to avoid
    downloading the full file before starting playback. We respond with
    206 Partial Content (single range or multipart for multiple ranges)
    or 200 with the full body if no Range header is present.
    """
    file_size = file_path.stat().st_size
    range_header = request.headers.get("range") or request.headers.get("Range")

    if range_header:
        parsed_ranges = _parse_byte_ranges(range_header, file_size=file_size)
        if parsed_ranges is None:
            return Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{file_size}"},
            )

        if len(parsed_ranges) == 1:
            start, end = parsed_ranges[0]
            chunk_length = (end - start) + 1
            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(chunk_length),
                "Cache-Control": cache_control,
            }
            return StreamingResponse(
                _iter_file_range(file_path, start=start, end=end, chunk_size=chunk_size),
                status_code=206,
                media_type=media_type,
                headers=headers,
            )

        boundary = _secrets.token_hex(16)
        content_length = _multipart_content_length(
            ranges=parsed_ranges,
            file_size=file_size,
            media_type=media_type,
            boundary=boundary,
        )
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(content_length),
            "Cache-Control": cache_control,
        }
        return StreamingResponse(
            _build_multipart_iterator(
                file_path,
                ranges=parsed_ranges,
                file_size=file_size,
                media_type=media_type,
                boundary=boundary,
                chunk_size=chunk_size,
            ),
            status_code=206,
            media_type=f"multipart/byteranges; boundary={boundary}",
            headers=headers,
        )

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Cache-Control": cache_control,
    }
    return StreamingResponse(
        _iter_full_file(file_path, chunk_size=chunk_size),
        status_code=200,
        media_type=media_type,
        headers=headers,
    )


__all__ = [
    "DEFAULT_CACHE_CONTROL",
    "DEFAULT_VIDEO_MEDIA_TYPE",
    "VIDEO_STREAM_CHUNK_SIZE",
    "build_range_response",
]
