from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

USERS_DIR = Path("data/users")

_STATE_KEYS = (
    "messages",
    "user_email",
    "pending_email",
    "agent_threads",
    "agent_last_message_id",
)

_DEFAULTS: dict[str, Any] = {
    "messages": [],
    "user_email": None,
    "pending_email": None,
    "agent_threads": {},
    "agent_last_message_id": {},
}


def _user_id(email: str) -> str:
    """Deterministic, filesystem-safe identifier derived from the email address."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]


class UserStore:
    """Manages per-user state persistence in data/users/{user_id}.json."""

    def __init__(self, email: str) -> None:
        self.email: str = email.strip().lower()
        self.user_id: str = _user_id(self.email)
        self._path: Path = USERS_DIR / f"{self.user_id}.json"

    @property
    def exists(self) -> bool:
        return self._path.exists()

    def load(self) -> dict[str, Any]:
        """Return persisted state, filling missing keys with defaults."""
        if not self._path.exists():
            return copy.deepcopy(_DEFAULTS)
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return copy.deepcopy(_DEFAULTS)
        return {k: data.get(k, copy.deepcopy(_DEFAULTS[k])) for k in _STATE_KEYS}

    def save(self, state: dict[str, Any]) -> None:
        """Persist the five tracked keys from state to disk."""
        USERS_DIR.mkdir(parents=True, exist_ok=True)
        payload = {k: state.get(k, _DEFAULTS[k]) for k in _STATE_KEYS}
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def delete(self) -> None:
        if self._path.exists():
            self._path.unlink()
