from __future__ import annotations

import json
import os
from typing import Any, TypedDict

from openai import OpenAI


class LLMResult(TypedDict):
    assistant_text: str
    action: str  
    to: str
    cc: list[str]
    subject: str
    body: str


SYSTEM_RULES = """
You are LENAH, a helpful conversational assistant for property-related emails.

Only choose action="send_email" when the user clearly wants you to draft an email AND a recipient email address is present.

Always output ONLY valid JSON using this exact schema (all keys always present):
{
  "assistant_text": string,
  "action": "none" | "send_email",
  "to": string,
  "cc": [string],
  "subject": string,
  "body": string
}

Rules:
- If action="none": set to="", cc=[], subject="", body="".
- If action="send_email": include to, subject, body.
- If the user says "hello" or similar, introduce yourself briefly and explain what you can do.
- If the user wants to send an email but has not provided the recipient email address, ask them to paste it.
- If the user requests a property enquiry but gives minimal details, generate a sensible default email draft.
- Never use placeholders like [Recipient's Name], [Your Name], [Your Contact Information], etc.
- If the sender name is unknown, sign off as "LENAH - AI Assitant" only.

""".strip()


client = OpenAI()

JSON_SCHEMA: dict[str, Any] = {
    "name": "lenah_output",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "assistant_text": {"type": "string"},
            "action": {"type": "string", "enum": ["none", "send_email"]},
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
        temperature=0.3,
    )

    obj = json.loads((resp.output_text or "{}").strip())


    if obj.get("action") == "send_email" and not str(obj.get("to") or "").strip():
        obj["action"] = "none"
        obj["to"] = ""
        obj["cc"] = []
        obj["subject"] = ""
        obj["body"] = ""
        if not str(obj.get("assistant_text") or "").strip():
            obj["assistant_text"] = "What’s the recipient email address?"

    return obj 



