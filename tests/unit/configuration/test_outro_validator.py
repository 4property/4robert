"""Unit tests for the outro upload validator (feature 33).

The validator is the pure side of ``UploadOutroVideoUseCase`` — MIME
allow-list, size cap and duration window. We exercise it directly so
the failure paths don't depend on a Postgres or ffprobe round-trip.
"""

from __future__ import annotations

import pytest

from modules.configuration.application.use_cases.upload_outro_video import (
    OUTRO_MAX_DURATION_SECONDS,
    OUTRO_MAX_UPLOAD_BYTES,
    OUTRO_MIN_DURATION_SECONDS,
    validate_outro_duration,
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


def test_validator_rejects_payload_over_50mb() -> None:
    oversized = b"x" * (OUTRO_MAX_UPLOAD_BYTES + 1)
    with pytest.raises(ValidationError) as excinfo:
        validate_outro_upload(content_type="video/mp4", body=oversized)
    assert excinfo.value.code == "OUTRO_FILE_TOO_LARGE"
    # The context reports the actual received_bytes so the client
    # can surface the gap to the user.
    assert int(excinfo.value.context["received_bytes"]) == len(oversized)


def test_validate_duration_accepts_range_extremes() -> None:
    assert validate_outro_duration(OUTRO_MIN_DURATION_SECONDS) == OUTRO_MIN_DURATION_SECONDS
    assert validate_outro_duration(OUTRO_MAX_DURATION_SECONDS) == OUTRO_MAX_DURATION_SECONDS


def test_validate_duration_rejects_zero_seconds() -> None:
    with pytest.raises(ValidationError) as excinfo:
        validate_outro_duration(0)
    assert excinfo.value.code == "OUTRO_INVALID_DURATION"


def test_validate_duration_rejects_above_max() -> None:
    with pytest.raises(ValidationError) as excinfo:
        validate_outro_duration(OUTRO_MAX_DURATION_SECONDS + 1)
    assert excinfo.value.code == "OUTRO_INVALID_DURATION"


def test_validate_duration_rejects_negative_value() -> None:
    with pytest.raises(ValidationError) as excinfo:
        validate_outro_duration(-3)
    assert excinfo.value.code == "OUTRO_INVALID_DURATION"
