"""Unit tests for the persistent HTTP traffic middleware."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from apps.api.logging_middleware import (
    decode_body_for_logging,
    register_logging_middleware,
    sanitize_headers_for_logging,
)


class SanitizeHeadersTests(unittest.TestCase):
    def test_redacts_known_sensitive_headers(self) -> None:
        sanitized = sanitize_headers_for_logging(
            {"Authorization": "Bearer abc", "X-Custom": "ok"}
        )
        self.assertEqual(sanitized["Authorization"], "<redacted>")
        self.assertEqual(sanitized["X-Custom"], "ok")

    def test_redaction_is_case_insensitive(self) -> None:
        sanitized = sanitize_headers_for_logging({"authorization": "Bearer abc"})
        self.assertEqual(sanitized["authorization"], "<redacted>")


class DecodeBodyTests(unittest.TestCase):
    def test_redacts_json_body_secrets(self) -> None:
        body = b'{"access_token":"secret","name":"Acme"}'
        decoded = decode_body_for_logging(body)
        self.assertIsNotNone(decoded)
        assert decoded is not None  # for type checker
        self.assertIn('"access_token": "<redacted>"', decoded)
        self.assertIn('"name": "Acme"', decoded)

    def test_returns_raw_text_when_not_json(self) -> None:
        body = b"plain text"
        self.assertEqual(decode_body_for_logging(body), "plain text")

    def test_returns_none_for_empty_body(self) -> None:
        self.assertIsNone(decode_body_for_logging(b""))
        self.assertIsNone(decode_body_for_logging(None))


def _build_app() -> FastAPI:
    app = FastAPI()
    register_logging_middleware(app)

    @app.get("/echo")
    async def get_echo(request: Request) -> JSONResponse:
        return JSONResponse(
            status_code=200,
            content={"request_id": getattr(request.state, "request_id", None)},
        )

    @app.post("/echo")
    async def post_echo(request: Request) -> JSONResponse:
        body = await request.body()
        return JSONResponse(
            status_code=200,
            content={
                "request_id": getattr(request.state, "request_id", None),
                "body_size": len(body),
            },
        )

    return app


class RegisterLoggingMiddlewareTests(unittest.TestCase):
    def test_assigns_request_id_to_request_state(self) -> None:
        client = TestClient(_build_app())
        response = client.get("/echo")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json()["request_id"], str)
        self.assertTrue(response.json()["request_id"])

    def test_logs_http_request_and_response_events_with_expected_fields(self) -> None:
        captured: list[tuple[str, dict[str, object]]] = []

        def fake_log_persistent_event(event_type: str, **fields: object) -> None:
            captured.append((event_type, fields))

        with patch(
            "apps.api.logging_middleware.log_persistent_event",
            side_effect=fake_log_persistent_event,
        ):
            client = TestClient(_build_app())
            response = client.post(
                "/echo",
                headers={"Authorization": "Bearer secret-token"},
                json={"name": "Acme", "access_token": "leaked"},
            )

        self.assertEqual(response.status_code, 200)
        event_types = [event for event, _ in captured]
        self.assertIn("http.request", event_types)
        self.assertIn("http.response", event_types)

        request_event = next(fields for event, fields in captured if event == "http.request")
        self.assertEqual(request_event["method"], "POST")
        self.assertEqual(request_event["path"], "/echo")
        self.assertIsInstance(request_event["request_id"], str)
        self.assertGreater(int(request_event["body_size_bytes"]), 0)
        # Authorization header must be redacted in the persisted log.
        sanitized_headers = request_event["headers"]
        assert isinstance(sanitized_headers, dict)
        auth_header = next(
            (value for key, value in sanitized_headers.items() if key.lower() == "authorization"),
            None,
        )
        self.assertEqual(auth_header, "<redacted>")
        # Body must redact known secret fields.
        body_repr = request_event["body"]
        assert isinstance(body_repr, str)
        self.assertIn("<redacted>", body_repr)
        self.assertIn("Acme", body_repr)

        response_event = next(fields for event, fields in captured if event == "http.response")
        self.assertEqual(response_event["status_code"], 200)
        self.assertEqual(response_event["request_id"], request_event["request_id"])
        self.assertIn("duration_ms", response_event)


if __name__ == "__main__":
    unittest.main()
