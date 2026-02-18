from __future__ import annotations

import json
import os
from typing import Any, TypedDict

from openai import OpenAI


class LLMResult(TypedDict):
    assistant_text: str
    action: str  # always "none"
    to: str
    cc: list[str]
    subject: str
    body: str


SYSTEM_RULES = """
You are LENAH. Your job is to DRAFT property enquiry emails.

You NEVER send emails. Always set action="none".

Write in British English. Keep emails short and direct.
Do NOT use placeholders like:
- [Your Name]
- [Recipient's Name]
- [Your Contact Information]

Always sign off as:
LENAH - AI Assistant

If the conversation contains a line like "Recipient email: someone@example.com",
use that address as the "to" field.

If the user provides minimal info (location/budget/bedrooms or a property link),
draft a sensible enquiry anyway. 

Always output ONLY valid JSON with this schema (all keys always present):
{
  "assistant_text": string,
  "action": "none",
  "to": string,
  "cc": [string],
  "subject": string,
  "body": string
}
""".strip()


client = OpenAI()

JSON_SCHEMA: dict[str, Any] = {
    "name": "lenah_draft",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "assistant_text": {"type": "string"},
            "action": {"type": "string", "enum": ["none"]},
            "to": {"type": "string"},
            "cc": {"type": "array", "items": {"type": "string"}},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["assistant_text", "action", "to", "cc", "subject", "body"],
        "additionalProperties": False,
    },
}


def generate_structured(messages: list[dict[str, str]]) -> LLMResult:
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    resp = client.responses.create(
        model=model,
        instructions=SYSTEM_RULES,
        input=messages[-12:],
        text={
            "format": {
                "type": "json_schema",
                "name": JSON_SCHEMA["name"],
                "strict": True,
                "schema": JSON_SCHEMA["schema"],
            }
        },
        temperature=0.2,
    )

    raw = (resp.output_text or "").strip()
    obj = json.loads(raw)

    # tiny safety defaults (should rarely trigger)
    obj.setdefault("assistant_text", "")
    obj.setdefault("action", "none")
    obj.setdefault("to", "")
    obj.setdefault("cc", [])
    obj.setdefault("subject", "")
    obj.setdefault("body", "")

    return obj  # type: ignore[return-value]





