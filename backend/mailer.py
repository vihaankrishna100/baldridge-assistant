"""Sends sign-in codes and invitations by email over SMTP."""

from __future__ import annotations

import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage

from config import settings


class MailError(RuntimeError):
    pass


def _send(to: str, subject: str, body: str) -> None:
    if not settings.email_codes_available:
        raise MailError("Email is not configured.")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg.set_content(body)
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


def send_sign_in_code(to: str, code: str) -> None:
    _send(
        to,
        f"Your {settings.org_name} Assistant sign-in code",
        f"Your sign-in code is {code}\n\n"
        "It works once and expires in 10 minutes. If you didn't just try to sign in "
        f"to the {settings.org_name} Assistant, someone may know your password — "
        "change it and tell an administrator.\n",
    )


def send_invite(to: str, url: str, invited_by: str, expires_at: datetime) -> None:
    """Most invitations that were never accepted were never delivered: the
    admin had to copy the link into an email by hand. With SMTP set up the
    link goes out on its own."""
    _send(
        to,
        f"You're invited to the {settings.org_name} Assistant",
        f"{invited_by} has set up an account for you on the {settings.org_name} "
        "Assistant, which answers questions from the Lodge's own policies and "
        "procedures.\n\n"
        f"Create your password here:\n{url}\n\n"
        f"The link works once and expires on {expires_at:%B %d, %Y}. You'll also be "
        "asked to set up a sign-in code with an authenticator app (Google "
        "Authenticator, Microsoft Authenticator, or similar) on your phone.\n\n"
        "If you weren't expecting this, you can ignore it.\n",
    )
