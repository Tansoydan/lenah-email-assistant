from __future__ import annotations

from pathlib import Path

SESSION_FILE = Path("data/current_conversation_id.txt")


def load_conversation_id() -> str | None:
    if SESSION_FILE.exists():
        cid = SESSION_FILE.read_text().strip()
        return cid or None
    return None


def save_conversation_id(cid: str) -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(cid)