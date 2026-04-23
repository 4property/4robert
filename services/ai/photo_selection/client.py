from __future__ import annotations

import base64
import json
import mimetypes
import time
from pathlib import Path
from typing import Any

import httpx

from settings import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_RETRY_ATTEMPTS,
    GEMINI_TIMEOUT_SECONDS,
)
from services.ai.photo_selection.prompting import (
    clamp_int,
    normalize_caption,
    normalize_highlights,
    normalize_reject_reason,
    normalize_space_id,
)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


class GeminiSelectionError(RuntimeError):
    pass


class GeminiConfigurationError(GeminiSelectionError):
    pass


class GeminiQuotaExhaustedError(GeminiSelectionError):
    pass


def guess_mime_type(image_path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(image_path.name)
    return mime_type or "application/octet-stream"


def strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = strip_code_fences(text)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise GeminiSelectionError(f"Could not extract JSON from response: {text}")
        payload = json.loads(cleaned[start : end + 1])

    if not isinstance(payload, dict):
        raise GeminiSelectionError("Gemini returned a non-object JSON payload.")
    return payload


def parse_model_text(response_data: dict[str, Any]) -> str:
    candidates = response_data.get("candidates") or []
    if not candidates:
        raise GeminiSelectionError(
            f"API returned no candidates: {json.dumps(response_data, ensure_ascii=False)}"
        )

    parts = candidates[0].get("content", {}).get("parts", [])
    text_parts = [part.get("text", "") for part in parts if "text" in part]
    text = "".join(text_parts).strip()
    if not text:
        raise GeminiSelectionError(
            f"Response did not contain text: {json.dumps(response_data, ensure_ascii=False)}"
        )
    return text


def parse_quota_error(error_body: str) -> dict[str, Any]:
    retry_after = None
    quota_ids: list[str] = []

    try:
        error_data = json.loads(error_body)
    except json.JSONDecodeError:
        error_data = None

    if error_data:
        details = error_data.get("error", {}).get("details", [])
        for detail in details:
            violations = detail.get("violations", [])
            for violation in violations:
                quota_id = violation.get("quotaId")
                if isinstance(quota_id, str):
                    quota_ids.append(quota_id)

            retry_delay = detail.get("retryDelay")
            if isinstance(retry_delay, str) and retry_delay.endswith("s"):
                try:
                    retry_after = float(retry_delay[:-1])
                except ValueError:
                    retry_after = None

    return {
        "retry_after": retry_after,
        "quota_ids": quota_ids,
    }


def is_daily_quota_exhausted(quota_ids: list[str], error_body: str) -> bool:
    body = error_body.lower()
    return any(
        marker in quota_id.lower()
        for quota_id in quota_ids
        for marker in ("per_day", "perday")
    ) or "daily limit" in body


class GeminiPhotoSelectionClient:
    def __init__(
        self,
        *,
        api_key: str = GEMINI_API_KEY,
        model: str = GEMINI_MODEL,
        timeout_seconds: int = GEMINI_TIMEOUT_SECONDS,
        retry_attempts: int = GEMINI_RETRY_ATTEMPTS,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=GEMINI_BASE_URL,
            follow_redirects=True,
            timeout=self.timeout_seconds,
        )

        if not self.api_key:
            raise GeminiConfigurationError(
                "No Gemini API key found. Set GEMINI_API_KEY or GEMINI_KEY in the environment."
            )
        if not self.model:
            raise GeminiConfigurationError("A Gemini model must be configured.")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def build_request_payload(self, image_path: Path, prompt_text: str) -> dict[str, Any]:
        image_bytes = image_path.read_bytes()
        encoded_image = base64.b64encode(image_bytes).decode("ascii")
        return {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt_text},
                        {
                            "inline_data": {
                                "mime_type": guess_mime_type(image_path),
                                "data": encoded_image,
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }

    def classify_image(self, image_path: Path, prompt_text: str) -> dict[str, Any]:
        payload = self.build_request_payload(image_path, prompt_text)
        last_error: Exception | None = None

        for attempt in range(self.retry_attempts):
            try:
                response = self._client.post(
                    f"/models/{self.model}:generateContent",
                    params={"key": self.api_key},
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=self.timeout_seconds,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self.retry_attempts - 1:
                    time.sleep(min(30, 2**attempt))
                    continue
                raise GeminiSelectionError(
                    f"Could not classify {image_path.name}: {exc}"
                ) from exc

            if response.status_code >= 400:
                error_body = response.text
                quota_error = parse_quota_error(error_body)
                retry_after = quota_error["retry_after"]
                quota_ids = quota_error["quota_ids"]
                last_error = GeminiSelectionError(
                    f"HTTP {response.status_code} error while classifying {image_path.name}: {error_body}"
                )
                if response.status_code == 429 and is_daily_quota_exhausted(
                    quota_ids,
                    error_body,
                ):
                    raise GeminiQuotaExhaustedError(
                        f"Daily quota exhausted for model {self.model}. "
                        "Wait for the quota reset or switch to another model/project."
                    )
                if (
                    response.status_code in _TRANSIENT_STATUS_CODES
                    and attempt < self.retry_attempts - 1
                ):
                    wait_seconds = (
                        retry_after if retry_after is not None else min(60, 2**attempt)
                    )
                    time.sleep(wait_seconds)
                    continue
                raise last_error

            try:
                response_data = response.json()
            except json.JSONDecodeError as exc:
                last_error = exc
                if attempt < self.retry_attempts - 1:
                    time.sleep(min(30, 2**attempt))
                    continue
                raise GeminiSelectionError(
                    f"Could not classify {image_path.name}: {exc}"
                ) from exc

            if not isinstance(response_data, dict):
                raise GeminiSelectionError("Gemini returned a non-object API response.")

            text = parse_model_text(response_data)
            result = extract_json_object(text)
            area = str(result.get("area", "other")).strip() or "other"
            return {
                "area": area,
                "confidence": clamp_int(result.get("confidence"), 0),
                "showcase_score": clamp_int(result.get("showcase_score"), 0),
                "space_id": normalize_space_id(result.get("space_id"), area),
                "highlights": normalize_highlights(result.get("highlights")),
                "caption": normalize_caption(
                    result.get("caption"),
                    "Well-presented interior photo.",
                ),
                "reject_asset": bool(result.get("reject_asset")),
                "reject_reason": normalize_reject_reason(result.get("reject_reason")),
            }

        raise GeminiSelectionError(
            f"Could not classify {image_path.name}: {last_error}"
        )


__all__ = [
    "GEMINI_BASE_URL",
    "GeminiConfigurationError",
    "GeminiPhotoSelectionClient",
    "GeminiQuotaExhaustedError",
    "GeminiSelectionError",
    "extract_json_object",
    "guess_mime_type",
    "is_daily_quota_exhausted",
    "parse_model_text",
    "parse_quota_error",
    "strip_code_fences",
]

