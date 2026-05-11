"""Unit tests for the byte-range streaming response helper."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from apps.api.range_response import build_range_response


def _build_app(file_path: Path) -> FastAPI:
    app = FastAPI()

    @app.get("/video")
    async def video(request: Request):  # type: ignore[no-untyped-def]
        return build_range_response(request, file_path)

    return app


class BuildRangeResponseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self.file_path = Path(self._tempdir.name) / "video.mp4"
        # 4 KiB of deterministic content.
        self.payload = bytes(range(256)) * 16
        self.file_path.write_bytes(self.payload)

    def test_returns_full_body_when_no_range_header(self) -> None:
        client = TestClient(_build_app(self.file_path))
        response = client.get("/video")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.payload)
        self.assertEqual(response.headers["content-length"], str(len(self.payload)))
        self.assertEqual(response.headers["accept-ranges"], "bytes")

    def test_single_range_returns_206_with_slice(self) -> None:
        client = TestClient(_build_app(self.file_path))
        response = client.get("/video", headers={"Range": "bytes=10-19"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, self.payload[10:20])
        self.assertEqual(
            response.headers["content-range"],
            f"bytes 10-19/{len(self.payload)}",
        )
        self.assertEqual(response.headers["content-length"], "10")
        self.assertEqual(response.headers["accept-ranges"], "bytes")

    def test_open_ended_range_serves_until_end(self) -> None:
        client = TestClient(_build_app(self.file_path))
        response = client.get("/video", headers={"Range": "bytes=4090-"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, self.payload[4090:])

    def test_suffix_range_serves_last_n_bytes(self) -> None:
        client = TestClient(_build_app(self.file_path))
        response = client.get("/video", headers={"Range": "bytes=-100"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, self.payload[-100:])
        self.assertEqual(
            response.headers["content-range"],
            f"bytes {len(self.payload) - 100}-{len(self.payload) - 1}/{len(self.payload)}",
        )

    def test_unsatisfiable_range_returns_416(self) -> None:
        client = TestClient(_build_app(self.file_path))
        response = client.get("/video", headers={"Range": "bytes=999999-"})
        self.assertEqual(response.status_code, 416)
        self.assertEqual(
            response.headers["content-range"],
            f"bytes */{len(self.payload)}",
        )

    def test_malformed_range_returns_416(self) -> None:
        client = TestClient(_build_app(self.file_path))
        response = client.get("/video", headers={"Range": "bytes=abc-def"})
        self.assertEqual(response.status_code, 416)

    def test_multipart_range_returns_206_with_multipart_byteranges(self) -> None:
        client = TestClient(_build_app(self.file_path))
        response = client.get(
            "/video",
            headers={"Range": "bytes=0-9, 100-109, 1000-1019"},
        )
        self.assertEqual(response.status_code, 206)
        content_type = response.headers["content-type"]
        self.assertTrue(content_type.startswith("multipart/byteranges; boundary="))
        boundary = content_type.split("boundary=", 1)[1]
        body = response.content
        # Three parts plus closing boundary.
        boundary_marker = f"--{boundary}".encode("ascii")
        self.assertEqual(body.count(boundary_marker), 4)
        # Each part should carry a Content-Range header.
        self.assertIn(
            f"Content-Range: bytes 0-9/{len(self.payload)}".encode("ascii"),
            body,
        )
        self.assertIn(
            f"Content-Range: bytes 100-109/{len(self.payload)}".encode("ascii"),
            body,
        )
        self.assertIn(
            f"Content-Range: bytes 1000-1019/{len(self.payload)}".encode("ascii"),
            body,
        )
        # Each part's payload bytes must appear in the body.
        self.assertIn(self.payload[0:10], body)
        self.assertIn(self.payload[100:110], body)
        self.assertIn(self.payload[1000:1020], body)

    def test_multipart_content_length_matches_body(self) -> None:
        client = TestClient(_build_app(self.file_path))
        response = client.get(
            "/video",
            headers={"Range": "bytes=0-9, 100-109"},
        )
        self.assertEqual(response.status_code, 206)
        self.assertEqual(
            int(response.headers["content-length"]),
            len(response.content),
        )


if __name__ == "__main__":
    unittest.main()
