# src/llm.py
from __future__ import annotations

from typing import Literal

from openai import OpenAI

from src.config import OPENAI_API_KEY, OPENAI_MODEL
from src.templates import ensure_signature

Decision = Literal["CHAT", "EMAIL_SUMMARY_TO_USER", "EMAIL_AGENT"]


if not OPENAI_API_KEY:
    raise RuntimeError(
        "OPENAI_API_KEY is missing. Set it in your .env (and ensure load_dotenv() runs) or environment."
    )

_client = OpenAI(api_key=OPENAI_API_KEY)

def decide_next_action(*, user_text: str) -> Decision:
    """
    Routing rules for your intended workflow:

    - Default behaviour: CHAT (normal property assistant conversation).
    - Only email when the user is explicitly asking to send/email something.
      - If user asks to email/send to themselves -> EMAIL_SUMMARY_TO_USER (we send key points of convo)
      - If user asks to email/contact an estate agent / landlord / third party -> EMAIL_AGENT

    This is intentionally simple and robust.
    """
    t = (user_text or "").strip().lower()
    if not t:
        return "CHAT"

    send_words = [
        "email",
        "e-mail",
        "send",
        "inbox",
        "cc",
        "forward",
    ]


    agent_words = [
        "estate agent",
        "letting agent",
        "agent",
        "landlord",
        "broker",
        "realtor",
    ]

    wants_send = any(w in t for w in send_words)
    wants_agent = any(w in t for w in agent_words)


    if wants_send and wants_agent:
        return "EMAIL_AGENT"


    if wants_send:
        return "EMAIL_SUMMARY_TO_USER"

    return "CHAT"


ASSISTANT_SYSTEM = """You are LENAH, a helpful property assistant.

You can chat about areas, budgets, commuting, schools, safety, value-for-money, and next steps.
Be practical and concise.

IMPORTANT:
- Never say you can't email or that you can only draft emails.
- Never claim you sent an email.
- If the user asks to email/send something, acknowledge briefly and continue; the application handles sending.
"""


def chat_reply(*, chat_history: list[dict], user_text: str, user_email: str | None) -> str:
    recent = chat_history[-20:] if chat_history else []
    resp = _client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {"role": "system", "content": ASSISTANT_SYSTEM},
            {"role": "user", "content": f"(Context) Known user email: {user_email or 'NONE'}"},
            *recent,
            {"role": "user", "content": user_text},
        ],
        temperature=0.5,
    )
    return (resp.output_text or "").strip()



EMAIL_SYSTEM = """You are LENAH – AI Assistant. Write a professional email.

Rules:
- No placeholders like "Dear [Name]".
- Keep it short and clear.
- Use bullet points when helpful.
- Always end with: LENAH – AI Assistant

Output format:
SUBJECT: <subject>
BODY:
<body>
"""


def _parse_subject_body(text: str) -> tuple[str, str]:
    out = (text or "").strip()
    subject = "Summary"
    body = out

    lines = out.splitlines()
    for i, line in enumerate(lines):
        if line.upper().startswith("SUBJECT:"):
            subject = line.split(":", 1)[1].strip() or subject
        if line.upper().startswith("BODY:"):
            body = "\n".join(lines[i + 1 :]).strip()
            break

    body = ensure_signature(body)
    return subject, body


def draft_summary_email(*, chat_history: list[dict]) -> tuple[str, str]:
    """
    Email to the user: key points / summary of conversation so far.
    """
    recent = chat_history[-40:] if chat_history else []

    prompt = """Task: Summarise the conversation so far into key points.

Include:
- 5–10 bullet points max
- any concrete constraints mentioned (budget, bedrooms, areas, commute, must-haves)
- clear next steps
- 2–4 short questions if something important is missing
"""

    resp = _client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {"role": "system", "content": EMAIL_SYSTEM},
            {"role": "user", "content": prompt},
            {"role": "user", "content": "Conversation context (most recent last):"},
            *recent,
        ],
        temperature=0.2,
    )

    return _parse_subject_body(resp.output_text or "")


def draft_agent_email(*, chat_history: list[dict], user_request: str) -> tuple[str, str]:
    """
    Email to an estate agent / landlord. The app will CC the user.
    """
    recent = chat_history[-40:] if chat_history else []

    prompt = f"""Task: Write an email to an estate agent about the user's requirement.

Use the user request + any constraints from the chat context.
Ask for:
- whether they have anything suitable
- approximate pricing and location
- any listings/links/details they can share
- next steps for arranging a viewing and required documents

User request: {user_request}
"""

    resp = _client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {"role": "system", "content": EMAIL_SYSTEM},
            {"role": "user", "content": prompt},
            {"role": "user", "content": "Conversation context (most recent last):"},
            *recent,
        ],
        temperature=0.2,
    )

    return _parse_subject_body(resp.output_text or "")