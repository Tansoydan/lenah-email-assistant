from __future__ import annotations


SIGNATURE = "\n\nLENAH – AI Assistant"


def ensure_signature(body: str) -> str:
    body = (body or "").rstrip()
    if "LENAH" in body[-60:]:
        return body
    return body + SIGNATURE