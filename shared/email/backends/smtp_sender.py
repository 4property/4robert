"""``SmtpEmailSender`` — stdlib ``smtplib`` backend with optional TLS+auth.

The locally-generated RFC 5322 ``Message-ID`` is returned as
``SentEmail.provider_message_id`` so the persistence layer (feature 27)
can correlate a job execution with the audit row in
``email_notifications``. Multi-recipient emails get one ``Message-ID``
shared across the N rows that represent each ``To:`` address.
"""

from __future__ import annotations

import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage as StdlibEmailMessage
from email.utils import make_msgid

from shared.email.sender import EmailMessage, SentEmail


class SmtpEmailSender:
    """Send via stdlib :mod:`smtplib`.

    ``use_tls=True`` issues ``STARTTLS`` on the plain SMTP connection
    (no ``smtplib.SMTP_SSL``). Authentication is performed only when
    ``username`` is non-empty; an empty username means "anonymous
    relay" (useful against a local Postfix in dev). The connection is
    always closed in ``finally``, even on errors raised by
    :meth:`smtplib.SMTP.send_message`.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        use_tls: bool,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls

    def send(self, message: EmailMessage) -> SentEmail:
        envelope = StdlibEmailMessage()
        from_field = (
            f"{message.from_name} <{message.from_address}>"
            if message.from_name
            else message.from_address
        )
        envelope["From"] = from_field
        envelope["To"] = ", ".join(message.to)
        envelope["Subject"] = message.subject
        if message.reply_to:
            envelope["Reply-To"] = message.reply_to
        if message.headers:
            for header_name, header_value in message.headers.items():
                envelope[header_name] = header_value

        message_id_domain = message.from_address.split("@", 1)[-1] or "localhost"
        message_id = make_msgid(domain=message_id_domain)
        envelope["Message-ID"] = message_id

        envelope.set_content(message.body_text)
        if message.body_html is not None:
            envelope.add_alternative(message.body_html, subtype="html")

        client = smtplib.SMTP(self._host, self._port)
        try:
            client.ehlo()
            if self._use_tls:
                client.starttls()
                client.ehlo()
            if self._username:
                client.login(self._username, self._password or "")
            client.send_message(envelope)
        finally:
            try:
                client.quit()
            except smtplib.SMTPException:
                client.close()

        return SentEmail(
            provider_message_id=message_id,
            recipients=message.to,
            sent_at=datetime.now(timezone.utc),
        )


__all__ = ["SmtpEmailSender"]
