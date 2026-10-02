"""Sends sign-in codes by email over SMTP."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from config import settings


class MailError(RuntimeError):
    pass


def send_sign_in_code(to: str, code: str) -> None:
    if not settings.email_codes_available:
        raise MailError("Email is not configured.")
    msg = EmailMessage()
    msg["Subject"] = f"Your {settings.org_name} Assistant sign-in code"
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg.set_content(
        f"Your sign-in code is {code}\n\n"
        "It works once and expires in 10 minutes. If you didn't just try to sign in "
        f"to the {settings.org_name} Assistant, someone may know your password — "
        "change it and tell an administrator.\n"
    )
    context = ssl.create_default_context()
    try:
        if settings.smtp_port == 465:
            server = smtplib.SMTP_SSL(settings.smtp_host, 465, timeout=15, context=context)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
            server.starttls(context=context)
        with server:
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(type(exc).__name__) from exc
