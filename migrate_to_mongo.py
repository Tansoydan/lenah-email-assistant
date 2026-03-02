#!/usr/bin/env python3
"""
One-off migration: upsert data/users/*.json files into MongoDB.

Usage:
    python migrate_to_mongo.py

Reads MONGO_URI and MONGO_DB_NAME from the environment (or .env file).
Files missing a user_email field are skipped.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Import config after load_dotenv so env overrides are picked up.
from src.config import MONGO_DB_NAME, MONGO_URI  # noqa: E402
from pymongo import MongoClient  # noqa: E402

_STATE_KEYS = (
    "messages",
    "user_email",
    "pending_email",
    "agent_threads",
    "agent_last_message_id",
)

_DEFAULTS: dict = {
    "messages": [],
    "user_email": None,
    "pending_email": None,
    "agent_threads": {},
    "agent_last_message_id": {},
}


def _user_id(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]


def migrate() -> None:
    users_dir = Path("data/users")
    if not users_dir.exists():
        print("No data/users directory found. Nothing to migrate.")
        return

    files = sorted(users_dir.glob("*.json"))
    if not files:
        print("No JSON files found in data/users/. Nothing to migrate.")
        return

    client = MongoClient(MONGO_URI)
    collection = client[MONGO_DB_NAME]["users"]
    collection.create_index("email", unique=True)

    migrated = 0
    skipped = 0
    now = datetime.now(timezone.utc)

    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  SKIP {path.name}: could not read ({exc})")
            skipped += 1
            continue

        email = data.get("user_email")
        if not email:
            print(f"  SKIP {path.name}: missing user_email field")
            skipped += 1
            continue

        uid = _user_id(email)
        payload = {k: data.get(k, _DEFAULTS[k]) for k in _STATE_KEYS}

        collection.update_one(
            {"_id": uid},
            {
                "$set": {
                    **payload,
                    "email": email.strip().lower(),
                    "last_active": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        print(f"  OK   {path.name} → _id={uid} ({email})")
        migrated += 1

    client.close()
    print(f"\nDone. {migrated} migrated, {skipped} skipped.")


if __name__ == "__main__":
    migrate()
