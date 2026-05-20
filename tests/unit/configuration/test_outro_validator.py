"""Unit tests for the outro upload validator (feature 33).

The validator is the pure side of ``UploadOutroVideoUseCase`` — it
checks the MIME allow-list and rejects empty bodies. Size and duration
limits were removed: the SaaS admin can upload outros of any length
and weight, so the validator no longer enforces a 50 MB cap or a
[1, 10] s window.
"""

from __future__ import annotations

import pytest

from modules.configuration.application.use_cases.upload_outro_video import (
    validate_outro_upload,
)
from shared.errors import ValidationError


def test_validator_accepts_mp4_under_50mb() -> None:
    result = validate_outro_upload(
        content_type="video/mp4",
        body=b"x" * 1024,
    )
    assert result.content_type == "video/mp4"
    assert result.extension == ".mp4"


def test_validator_accepts_mov_under_50mb() -> None:
    result = validate_outro_upload(
        content_type="video/quicktime",
        body=b"x" * 2048,
    )
    assert result.content_type == "video/quicktime"
    assert result.extension == ".mov"


def test_validator_normalizes_case_in_content_type() -> None:
    result = validate_outro_upload(
        content_type=" Video/MP4 ",
        body=b"x" * 4,
    )
    assert result.content_type == "video/mp4"


def test_validator_rejects_text_with_invalid_mime() -> None:
    with pytest.raises(ValidationError) as excinfo:
        validate_outro_upload(content_type="text/plain", body=b"hello world")
    assert excinfo.value.code == "OUTRO_INVALID_MIME"


def test_validator_rejects_empty_body() -> None:
    with pytest.raises(ValidationError) as excinfo:
        validate_outro_upload(content_type="video/mp4", body=b"")
    assert excinfo.value.code == "OUTRO_FILE_EMPTY"


def test_validator_accepts_payload_well_over_50mb() -> None:
    """Size limit was removed — a 60 MB payload must pass validation."""
    oversized = b"x" * (60 * 1024 * 1024)
    result = validate_outro_upload(content_type="video/mp4", body=oversized)
    assert result.content_type == "video/mp4"
    assert result.extension == ".mp4"
