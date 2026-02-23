from __future__ import annotations

import re

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def extract_first_email(text: str | None) -> str | None:
    if not text:
        return None
    m = EMAIL_RE.search(text)
    return m.group(0) if m else None


def normalise_email(email: str) -> str:
    return email.strip().lower()


def is_valid_email(email: str | None) -> bool:
    if not email:
        return False
    return bool(EMAIL_RE.fullmatch(email.strip()))