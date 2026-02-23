# storage.py (MongoDB) — conversations, messages, users, pending drafts, outbox
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

# -----------------------
# time
# -----------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

# -----------------------
# ObjectId helpers
# -----------------------

def _oid(value: str | ObjectId) -> ObjectId:
    return value if isinstance(value, ObjectId) else ObjectId(value)

# -----------------------
# client/db (cached)
# -----------------------

_client_singleton: Optional[MongoClient] = None


def _client() -> MongoClient:
    global _client_singleton
    if _client_singleton is not None:
        return _client_singleton

    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise RuntimeError("MONGODB_URI is not set")

    _client_singleton = MongoClient(
        uri,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=20000,
        retryWrites=True,
    )
    return _client_singleton


def _db() -> Database:
    db_name = os.getenv("MONGODB_DB", "lenah")
    return _client()[db_name]


def _col(name: str) -> Collection:
    return _db()[name]


def ping() -> None:
    _client().admin.command("ping")

# -----------------------
# init / indexes
# -----------------------

def init_db() -> None:
    """
    Creates indexes. Safe to call on every run.
    """
    db = _db()

    # Users
    db.users.create_index([("email", ASCENDING)], unique=True)

    # Conversations
    db.conversations.create_index([("user_id", ASCENDING), ("updated_at", DESCENDING)])
    db.conversations.create_index([("user_email", ASCENDING), ("updated_at", DESCENDING)])
    db.conversations.create_index([("created_at", DESCENDING)])
    # Optional: if you search by pending draft existence (rare)
    db.conversations.create_index([("pending_agent_draft.updated_at", DESCENDING)])

    # Messages
    db.messages.create_index([("conversation_id", ASCENDING), ("created_at", ASCENDING)])
    db.messages.create_index([("created_at", DESCENDING)])

    # Outbox
    db.outbox.create_index([("conversation_id", ASCENDING), ("created_at", DESCENDING)])
    db.outbox.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    db.outbox.create_index([("status", ASCENDING), ("created_at", DESCENDING)])
    db.outbox.create_index([("type", ASCENDING), ("created_at", DESCENDING)])

# -----------------------
# users
# -----------------------

def get_or_create_user(email: str) -> str:
    """
    Returns user_id as a string (ObjectId string).
    """
    db = _db()
    email_norm = email.strip().lower()
    if not email_norm:
        raise ValueError("email is empty")

    existing = db.users.find_one({"email": email_norm}, {"_id": 1})
    if existing:
        return str(existing["_id"])

    now = _utcnow()
    doc = {
        "email": email_norm,
        "email_verified": False,
        "created_at": now,
        "last_seen_at": now,
    }
    res = db.users.insert_one(doc)
    return str(res.inserted_id)


def touch_user(user_id: str) -> None:
    db = _db()
    db.users.update_one(
        {"_id": _oid(user_id)},
        {"$set": {"last_seen_at": _utcnow()}},
    )

# -----------------------
# conversations
# -----------------------

def ensure_conversation(conversation_id: str) -> None:
    """
    Creates a conversation document if missing.
    conversation_id is your app-level UUID string.
    """
    db = _db()
    now = _utcnow()

    db.conversations.update_one(
        {"_id": conversation_id},
        {
            "$setOnInsert": {
                "_id": conversation_id,
                "created_at": now,
                "updated_at": now,
                "user_id": None,        # ObjectId or None
                "user_email": None,     # str or None
                "title": None,
                # You can store other per-conversation state here too.
                # "pending_agent_draft": {...}  (added later)
            }
        },
        upsert=True,
    )


def attach_conversation_to_user(conversation_id: str, user_id: str, email: str) -> None:
    """
    Attach an anonymous conversation to a user once you know their email.
    """
    db = _db()
    ensure_conversation(conversation_id)

    email_norm = email.strip().lower()
    now = _utcnow()

    db.conversations.update_one(
        {"_id": conversation_id},
        {
            "$set": {
                "user_id": _oid(user_id),
                "user_email": email_norm,
                "updated_at": now,
            }
        },
        upsert=True,
    )


def set_user_email(conversation_id: str, email: str) -> None:
    """
    Normalises the email, creates/fetches user, and links conversation -> user.
    """
    ensure_conversation(conversation_id)
    user_id = get_or_create_user(email)
    attach_conversation_to_user(conversation_id, user_id=user_id, email=email)


def get_user_email(conversation_id: str) -> str | None:
    db = _db()
    conv = db.conversations.find_one({"_id": conversation_id}, {"user_email": 1})
    return (conv or {}).get("user_email") or None


def get_latest_conversation_for_email(email: str) -> str | None:
    """
    Useful if you want "returning user" behaviour:
    given an email, load their most recent conversation.
    """
    db = _db()
    email_norm = email.strip().lower()
    if not email_norm:
        return None

    conv = db.conversations.find_one(
        {"user_email": email_norm},
        sort=[("updated_at", DESCENDING)],
        projection={"_id": 1},
    )
    return conv["_id"] if conv else None


def touch_conversation(conversation_id: str) -> None:
    db = _db()
    db.conversations.update_one({"_id": conversation_id}, {"$set": {"updated_at": _utcnow()}}, upsert=True)

# -----------------------
# pending agent draft (stored on conversation)
# -----------------------

def set_pending_agent_draft(conversation_id: str, draft: dict[str, str] | None) -> None:
    """
    Stores the pending agent draft on the conversation doc.
    draft should be {"to": "...", "subject": "...", "body": "..."} or None to clear.
    """
    db = _db()
    ensure_conversation(conversation_id)
    now = _utcnow()

    if draft is None:
        db.conversations.update_one(
            {"_id": conversation_id},
            {"$set": {"updated_at": now}, "$unset": {"pending_agent_draft": ""}},
        )
        return

    clean = {
        "to": (draft.get("to") or "").strip(),
        "subject": (draft.get("subject") or "").strip(),
        "body": (draft.get("body") or "").strip(),
        "updated_at": now,
    }

    db.conversations.update_one(
        {"_id": conversation_id},
        {"$set": {"pending_agent_draft": clean, "updated_at": now}},
        upsert=True,
    )


def get_pending_agent_draft(conversation_id: str) -> dict[str, str] | None:
    db = _db()
    conv = db.conversations.find_one({"_id": conversation_id}, {"pending_agent_draft": 1})
    draft = (conv or {}).get("pending_agent_draft")
    if not draft:
        return None

    return {
        "to": draft.get("to", "") or "",
        "subject": draft.get("subject", "") or "",
        "body": draft.get("body", "") or "",
    }

# -----------------------
# messages
# -----------------------

def add_message(conversation_id: str, role: str, content: str) -> None:
    db = _db()
    ensure_conversation(conversation_id)

    now = _utcnow()
    db.messages.insert_one(
        {
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "created_at": now,
        }
    )

    db.conversations.update_one({"_id": conversation_id}, {"$set": {"updated_at": now}})


def load_messages(conversation_id: str, limit: int = 200) -> list[dict[str, str]]:
    db = _db()
    cur = (
        db.messages.find(
            {"conversation_id": conversation_id},
            {"role": 1, "content": 1, "_id": 0},
        )
        .sort("created_at", ASCENDING)
        .limit(limit)
    )
    return [{"role": d["role"], "content": d["content"]} for d in cur]

# -----------------------
# outbox (audit log of sends)
# -----------------------

def log_outbox(
    conversation_id: str,
    kind: str,  # "summary" | "agent_enquiry"
    to: list[str],
    cc: list[str] | None,
    subject: str,
    body: str,
    status: str,  # "sent" | "failed"
    error: str | None = None,
) -> None:
    db = _db()
    conv = db.conversations.find_one({"_id": conversation_id}, {"user_id": 1})

    db.outbox.insert_one(
        {
            "conversation_id": conversation_id,
            "user_id": (conv or {}).get("user_id"),
            "type": kind,
            "to": [x.strip() for x in (to or []) if x and x.strip()],
            "cc": [x.strip() for x in (cc or []) if x and x.strip()],
            "subject": subject,
            "body": body,
            "status": status,
            "error": error,
            "created_at": _utcnow(),
        }
    )