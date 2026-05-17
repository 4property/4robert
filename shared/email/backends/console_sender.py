"""``ConsoleEmailSender`` — dev/test backend that prints the message to stdout.

The prefix ``[email/console]`` makes the output greppable in test logs
and in the local worker process. It returns a :class:`SentEmail` with
``provider_message_id=None`` so the persistence layer can record that
no real provider was involved.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import TextIO

from shared.email.sender import EmailMessage, SentEmail


_CONSOLE_PREFIX = "[email/console]"


class ConsoleEmailSender:
    """Print the email envelope + body to ``stdout`` and return SentEmail.

    The optional ``stream`` constructor argument exists so unit tests can
    inject a :class:`io.StringIO`. Production callers leave it ``None``
    and the sender writes to :data:`sys.stdout`.
    """

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream

    def send(self, message: EmailMessage) -> SentEmail:
        stream = self._stream if self._stream is not None else sys.stdout
        from_field = (
            f"{message.from_name} <{message.from_address}>"
            if message.from_name
            else message.from_address
        )
        lines: list[str] = [
            f"{_CONSOLE_PREFIX} ---- BEGIN MESSAGE ----",
            f"{_CONSOLE_PREFIX} From: {from_field}",
            f"{_CONSOLE_PREFIX} To: {', '.join(message.to)}",
        ]
        if message.reply_to:
            lines.append(f"{_CONSOLE_PREFIX} Reply-To: {message.reply_to}")
        lines.append(f"{_CONSOLE_PREFIX} Subject: {message.subject}")
        if message.headers:
            for header_name, header_value in message.headers.items():
                lines.append(f"{_CONSOLE_PREFIX} {header_name}: {header_value}")
        lines.append(f"{_CONSOLE_PREFIX} ---- BODY (text) ----")
        for body_line in message.body_text.splitlines() or [""]:
            lines.append(f"{_CONSOLE_PREFIX} {body_line}")
        if message.body_html is not None:
            lines.append(f"{_CONSOLE_PREFIX} ---- BODY (html) ----")
            for body_line in message.body_html.splitlines() or [""]:
                lines.append(f"{_CONSOLE_PREFIX} {body_line}")
        lines.append(f"{_CONSOLE_PREFIX} ---- END MESSAGE ----")
        stream.write("\n".join(lines) + "\n")
        stream.flush()
        return SentEmail(
            provider_message_id=None,
            recipients=message.to,
            sent_at=datetime.now(timezone.utc),
        )


__all__ = ["ConsoleEmailSender"]
