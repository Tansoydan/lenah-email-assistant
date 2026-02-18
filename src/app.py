from __future__ import annotations

import re
import streamlit as st

from src.config import CREDENTIALS_PATH, GMAIL_SCOPES, TOKEN_PATH
from src.gmail_client import GmailClient
from src.llm import generate_structured

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def first_email(text: str) -> str | None:
    m = EMAIL_RE.search(text or "")
    return m.group(0) if m else None


def init_state() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("user_email", None)
    st.session_state.setdefault("recipient_email", None)
    st.session_state.setdefault("pending", None)  # {"to","subject","body"}
    st.session_state.setdefault("step", "need_user_email")  # need_user_email|need_recipient|need_details|confirm


def say(role: str, content: str) -> None:
    st.session_state.messages.append({"role": role, "content": content})
    with st.chat_message(role):
        st.markdown(content)


def render_history() -> None:
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])


def preview(draft: dict[str, str], cc_email: str) -> str:
    return (
        "Here’s the draft:\n\n"
        f"**To:** {draft['to']}\n\n"
        f"**CC:** {cc_email}\n\n"
        f"**Subject:** {draft['subject']}\n\n"
        "**Body:**\n\n"
        f"{draft['body']}\n\n"
        "Type **send** to send it, or paste edits to change it."
    )


def get_gmail_client() -> GmailClient:
    return GmailClient(
        credentials_path=CREDENTIALS_PATH,
        token_path=TOKEN_PATH,
        scopes=GMAIL_SCOPES,
    )


def run_app() -> None:
    st.set_page_config(page_title="LENAH - Property Email Assistant", layout="centered")
    st.title("LENAH - Property Email Assistant")

    init_state()
    gmail = get_gmail_client()
    gmail.service()

    # Intro (append only — don't render twice)
    if not st.session_state.messages:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": (
                    "Hi, I’m LENAH 👋\n\n"
                    "I draft property enquiry emails from my own mailbox and CC you in.\n\n"
                    "**What’s your email address?**"
                ),
            }
        )

    render_history()

    text = st.chat_input("Message LENAH…")
    if not text:
        return

    say("user", text)
    t = text.strip()

    if st.session_state.step == "confirm" and t.lower() == "send":
        d = st.session_state.pending
        gmail.send_email(
            to=d["to"],
            subject=d["subject"],
            body=d["body"],
            cc=[st.session_state.user_email],
        )
        st.session_state.pending = None
        st.session_state.step = "need_details"
        say("assistant", f"Sent — CC’d you in at {st.session_state.user_email}.")
        return

    if st.session_state.step == "need_user_email":
        email = first_email(t)
        if not email:
            say("assistant", "Please paste your email address (I’ll CC you on every enquiry).")
            return
        st.session_state.user_email = email
        st.session_state.step = "need_recipient"
        say("assistant", f"Nice one — I’ll CC you in at {email}. Now paste the estate agent’s email address.")
        return

    if st.session_state.step == "need_recipient":
        email = first_email(t)
        if not email:
            say("assistant", "Please paste the estate agent’s email address.")
            return
        st.session_state.recipient_email = email
        st.session_state.step = "need_details"
        say("assistant", "Got it. Now tell me what you’re looking for (or paste a Rightmove link).")
        return

    context = (
        st.session_state.messages
        + [{"role": "system", "content": f"Recipient email: {st.session_state.recipient_email}"}]
    )[-12:]

    result = generate_structured(context)

    subject = (result.get("subject") or "").strip()
    body = (result.get("body") or "").strip()
    to_email = (result.get("to") or "").strip() or st.session_state.recipient_email

    if not subject or not body:
        say("assistant", (result.get("assistant_text") or "Tell me a bit more and I’ll draft the email.").strip())
        return

    st.session_state.pending = {"to": to_email, "subject": subject, "body": body}
    st.session_state.step = "confirm"
    say("assistant", preview(st.session_state.pending, st.session_state.user_email))


if __name__ == "__main__":
    run_app()
