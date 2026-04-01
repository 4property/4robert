from __future__ import annotations

import json
from typing import Any

import httpx

from core.errors import SocialPublishingError, TransientSocialPublishingError


class GoHighLevelApiError(SocialPublishingError):
    def __init__(
        self,
        *,
        status_code: int,
        message: str,
        response_body: str,
        method: str,
        path: str,
        external_trace_id: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.response_body = response_body
        self.method = method
        self.path = path
        response_preview = response_body[:1000]
        super().__init__(
            f"GoHighLevel API error {status_code}: {message}",
            code=f"GHL_API_{status_code}",
            context={
                "method": method.upper(),
                "path": path,
                "status_code": status_code,
                "response_body": response_preview,
            },
            external_trace_id=external_trace_id,
        )


class GoHighLevelClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_version: str,
        timeout_seconds: int,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_version = api_version
        self.timeout_seconds = timeout_seconds
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            follow_redirects=True,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def request_json(
        self,
        method: str,
        path: str,
        *,
        access_token: str,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "Version": self.api_version,
        }
        try:
            response = self._client.request(
                method=method,
                url=path,
                params=params,
                headers=headers,
                json=json_body,
                data=data,
                files=files,
            )
        except httpx.HTTPError as error:
            raise TransientSocialPublishingError(
                f"GoHighLevel request failed: {error}",
                code="GHL_HTTP_ERROR",
                context={"method": method.upper(), "path": path},
                hint=(
                    "Check outbound network connectivity, DNS resolution, TLS interception, and the configured "
                    "GO_HIGH_LEVEL_BASE_URL for the deployed host."
                ),
                cause=error,
            ) from error

        if response.status_code >= 400:
            raise GoHighLevelApiError(
                status_code=response.status_code,
                message=self._summarise_error_message(response),
                response_body=response.text,
                method=method,
                path=path,
                external_trace_id=self._extract_trace_id(response),
            )

        if not response.content:
            return {}

        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise SocialPublishingError(
                "GoHighLevel returned a non-JSON response.",
                code="GHL_NON_JSON_RESPONSE",
                context={"method": method.upper(), "path": path},
                hint="Inspect the upstream response body and verify the GoHighLevel API is not returning HTML or proxy errors.",
                cause=error,
            ) from error

        return payload if isinstance(payload, dict) else {"results": payload}

    @staticmethod
    def _summarise_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            return response.text[:300] or "Unknown API error"

        if isinstance(payload, dict):
            for key in ("message", "error", "detail"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return response.text[:300] or "Unknown API error"

    @staticmethod
    def _extract_trace_id(response: httpx.Response) -> str | None:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        trace_id = payload.get("traceId")
        if isinstance(trace_id, str) and trace_id.strip():
            return trace_id.strip()
        return None


__all__ = ["GoHighLevelApiError", "GoHighLevelClient"]
