from __future__ import annotations

import asyncio
from collections.abc import Iterable

import h11

from core.logging import format_console_block, format_detail_line

try:
    import httptools
except ImportError:  # pragma: no cover
    httptools = None

from uvicorn.protocols.http.h11_impl import H11Protocol

if httptools is not None:  # pragma: no branch
    from uvicorn.protocols.http.httptools_impl import HttpToolsProtocol
else:  # pragma: no cover
    HttpToolsProtocol = asyncio.Protocol  # type: ignore[assignment,misc]


_INVALID_HTTP_REQUEST_RESPONSE_BODY = "Invalid HTTP request received."
_REQUEST_PREVIEW_LIMIT = 120


def format_invalid_http_request_warning(
    *,
    client: tuple[str, int] | None,
    data: bytes,
    parser_name: str,
    error: object | None = None,
) -> str:
    return format_console_block(
        "Invalid HTTP Request Received",
        format_detail_line("Client", _format_client_addr(client)),
        format_detail_line("Parser", parser_name),
        format_detail_line("Reason", str(error) if error not in (None, "") else _INVALID_HTTP_REQUEST_RESPONSE_BODY),
        format_detail_line("Hint", infer_invalid_http_request_hint(data)),
        format_detail_line("Payload preview", build_invalid_http_request_preview(data)),
    )


def infer_invalid_http_request_hint(data: bytes) -> str:
    preview = bytes(data[:32])
    if preview.startswith((b"\x16\x03\x00", b"\x16\x03\x01", b"\x16\x03\x02", b"\x16\x03\x03", b"\x16\x03\x04")):
        return (
            "This looks like a TLS handshake sent to a plain HTTP socket. Check whether HTTPS traffic "
            "or a TLS health check is pointed at the non-TLS Uvicorn port."
        )
    if preview.startswith(b"PRI * HTTP/2.0"):
        return (
            "This looks like an HTTP/2 connection preface. Put an HTTP/2-capable reverse proxy in front "
            "or make sure the upstream talks HTTP/1.1 to Uvicorn."
        )
    if preview and not _looks_like_text_http(preview):
        return (
            "The client sent binary or non-HTTP data. Check proxy wiring, port mappings, and whether a "
            "different protocol is hitting this endpoint."
        )
    return (
        "Check reverse proxy configuration, load balancer health checks, and whether the client is sending "
        "a valid HTTP/1.1 request to the correct port."
    )


def build_invalid_http_request_preview(data: bytes) -> str:
    preview = bytes(data[:_REQUEST_PREVIEW_LIMIT])
    if not preview:
        return "<empty>"
    if _looks_like_text_http(preview):
        text = preview.decode("latin-1", errors="replace")
        text = text.replace("\r", "\\r").replace("\n", "\\n")
        return text
    return preview.hex(" ")


class _VerboseInvalidRequestMixin:
    client: tuple[str, int] | None

    def __init__(self, *args, **kwargs) -> None:
        self._invalid_request_preview = b""
        super().__init__(*args, **kwargs)

    def _remember_invalid_request_data(self, data: bytes) -> None:
        if not data:
            return
        preview = self._invalid_request_preview + bytes(data)
        self._invalid_request_preview = preview[:_REQUEST_PREVIEW_LIMIT]

    def _log_invalid_http_request(self, *, parser_name: str, error: object | None = None) -> None:
        self.logger.warning(
            format_invalid_http_request_warning(
                client=self.client,
                data=self._invalid_request_preview,
                parser_name=parser_name,
                error=error,
            )
        )


class VerboseH11Protocol(_VerboseInvalidRequestMixin, H11Protocol):
    def data_received(self, data: bytes) -> None:
        self._remember_invalid_request_data(data)
        self._unset_keepalive_if_required()
        self.conn.receive_data(data)
        self.handle_events()

    def handle_events(self) -> None:
        while True:
            try:
                event = self.conn.next_event()
            except h11.RemoteProtocolError as exc:
                self._log_invalid_http_request(parser_name="h11", error=exc)
                self.send_400_response(_INVALID_HTTP_REQUEST_RESPONSE_BODY)
                return

            if event is h11.NEED_DATA:
                break

            if event is h11.PAUSED:
                self.flow.pause_reading()
                break

            if isinstance(event, h11.Request):
                self.headers = [(key.lower(), value) for key, value in event.headers]
                raw_path, _, query_string = event.target.partition(b"?")
                path = raw_path.decode("ascii")
                from urllib.parse import unquote

                path = unquote(path)
                full_path = self.root_path + path
                full_raw_path = self.root_path.encode("ascii") + raw_path
                self.scope = {
                    "type": "http",
                    "asgi": {"version": self.config.asgi_version, "spec_version": "2.3"},
                    "http_version": event.http_version.decode("ascii"),
                    "server": self.server,
                    "client": self.client,
                    "scheme": self.scheme,
                    "method": event.method.decode("ascii"),
                    "root_path": self.root_path,
                    "path": full_path,
                    "raw_path": full_raw_path,
                    "query_string": query_string,
                    "headers": self.headers,
                    "state": self.app_state.copy(),
                }
                if self._should_upgrade():
                    self.handle_websocket_upgrade(event)
                    return

                if self.limit_concurrency is not None and (
                    len(self.connections) >= self.limit_concurrency or len(self.tasks) >= self.limit_concurrency
                ):
                    app = __import__(
                        "uvicorn.protocols.http.flow_control",
                        fromlist=["service_unavailable"],
                    ).service_unavailable
                    message = "Exceeded concurrency limit."
                    self.logger.warning(message)
                else:
                    app = self.app

                self._unset_keepalive_if_required()

                from uvicorn.protocols.http.h11_impl import RequestResponseCycle

                import contextvars

                self.cycle = RequestResponseCycle(
                    scope=self.scope,
                    conn=self.conn,
                    transport=self.transport,
                    flow=self.flow,
                    logger=self.logger,
                    access_logger=self.access_logger,
                    access_log=self.access_log,
                    default_headers=self.server_state.default_headers,
                    message_event=asyncio.Event(),
                    on_response=self.on_response_complete,
                )
                task = contextvars.Context().run(self.loop.create_task, self.cycle.run_asgi(app))
                task.add_done_callback(self.tasks.discard)
                self.tasks.add(task)
                continue

            if isinstance(event, h11.Data):
                if self.conn.our_state is h11.DONE:
                    continue
                self.cycle.body += event.data
                from uvicorn.protocols.http.flow_control import HIGH_WATER_LIMIT

                if len(self.cycle.body) > HIGH_WATER_LIMIT:
                    self.flow.pause_reading()
                self.cycle.message_event.set()
                continue

            if isinstance(event, h11.EndOfMessage):
                if self.conn.our_state is h11.DONE:
                    self.transport.resume_reading()
                    self.conn.start_next_cycle()
                    continue
                self.cycle.more_body = False
                self.cycle.message_event.set()
                if self.conn.their_state == h11.MUST_CLOSE:
                    break


if httptools is not None:

    class VerboseHttpToolsProtocol(_VerboseInvalidRequestMixin, HttpToolsProtocol):
        def data_received(self, data: bytes) -> None:
            self._remember_invalid_request_data(data)
            self._unset_keepalive_if_required()

            try:
                self.parser.feed_data(data)
            except httptools.HttpParserError as exc:
                self._log_invalid_http_request(parser_name="httptools", error=exc)
                self.send_400_response(_INVALID_HTTP_REQUEST_RESPONSE_BODY)
                return
            except httptools.HttpParserUpgrade:
                if self._should_upgrade():
                    self.handle_websocket_upgrade()
                else:
                    self._unsupported_upgrade_warning()


    class VerboseAutoHTTPProtocol(VerboseHttpToolsProtocol):
        pass

else:  # pragma: no cover

    class VerboseAutoHTTPProtocol(VerboseH11Protocol):
        pass


def _format_client_addr(client: tuple[str, int] | None) -> str:
    if client is None:
        return "<unknown>"
    return f"{client[0]}:{client[1]}"


def _looks_like_text_http(data: bytes) -> bool:
    if not data:
        return True
    allowed_prefixes: Iterable[bytes] = (
        b"GET ",
        b"POST ",
        b"PUT ",
        b"PATCH ",
        b"DELETE ",
        b"HEAD ",
        b"OPTIONS ",
        b"CONNECT ",
        b"TRACE ",
        b"PRI * HTTP/2.0",
    )
    if any(data.startswith(prefix) for prefix in allowed_prefixes):
        return True
    printable = sum(
        1
        for byte in data
        if 32 <= byte <= 126 or byte in (9, 10, 13)
    )
    return printable >= max(1, int(len(data) * 0.85))


__all__ = [
    "VerboseAutoHTTPProtocol",
    "VerboseH11Protocol",
    "build_invalid_http_request_preview",
    "format_invalid_http_request_warning",
    "infer_invalid_http_request_hint",
]
