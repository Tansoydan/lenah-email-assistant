from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class EmailDraft:
    to_email: str
    subject: str
    body: str


def build_subject(message: str) -> str:
    # Tiny heuristic: keep it short and neutral.
    # If you paste a Rightmove link, this still works fine.
    today = date.today().strftime("%d %b %Y")
    return f"Enquiry ({today})"


def build_body(message: str, your_name: str | None) -> str:
    signoff_name = your_name.strip() if your_name and your_name.strip() else "LENAH"

    return (
        "Hello,\n\n"
        f"{message.strip()}\n\n"
        "Many thanks,\n"
        f"{signoff_name}\n"
    )


def build_email_draft(
    to_email: str,
    message: str,
    your_name: str | None = None,
    subject: str | None = None,
) -> EmailDraft:
    clean_to = to_email.strip()
    clean_message = message.strip()
    clean_subject = (subject or "").strip()

    if not clean_subject:
        clean_subject = build_subject(clean_message)

    body = build_body(clean_message, your_name)

    return EmailDraft(to_email=clean_to, subject=clean_subject, body=body)
