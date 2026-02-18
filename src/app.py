from __future__ import annotations

import re
import streamlit as st

from src.config import CREDENTIALS_PATH, GMAIL_SCOPES, TOKEN_PATH
from src.gmail_client import GmailClient
from src.llm import generate_structured

CENTRAL_EMAIL = "lenah.test.enquiries@gmail.com"

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def extract_first_email(text: str) -> str | None:
    m = EMAIL_RE.search(text or "")
    return m.group(0) if m else None


def extract_emails(text: str) -> list[str]:
    return [e.strip() for e in EMAIL_RE.findall(text or "")]

def capture_user_email(user_message: str) -> str | None:

    if "user_email" not in st.session_state:
        st.session_state.user_email = None

    email = extract_first_email(user_message)
    if email:
        st.session_state.user_email = email
        return email

    return None


def get_gmail_client() -> GmailClient:
    if "gmail_client" not in st.session_state:
        st.session_state.gmail_client = GmailClient(
            credentials_path=CREDENTIALS_PATH,
            token_path=TOKEN_PATH,
            scopes=GMAIL_SCOPES,
        )
    return st.session_state.gmail_client


def run_app() -> None:
    st.set_page_config(page_title="LENAH - Property Email Assistant", layout="centered")
    st.title("LENAH - Property Email Assistant")

    gmail_client = get_gmail_client()
    gmail_client.service()

    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    if not st.session_state.messages:
        intro = (
            "Hi, I’m LENAH 👋\n\n"
            "I can draft and send property enquiry emails from my own mailbox, and I’ll CC you in.\n\n"
            "What’s your email address?"
        )
        st.session_state.messages.append({"role": "assistant", "content": intro})
    
    if "seen_emails" not in st.session_state:
        st.session_state.seen_emails = set()

    if "user_email" not in st.session_state:
        st.session_state.user_email = None


    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_input = st.chat_input("Message LENAH…")
    if not user_input:
        return


    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)


    if not st.session_state.user_email:
        email = extract_first_email(user_input)
        if not email:
            assistant_text = "Before we start — what’s your email address so I can CC you in on every enquiry?"
            st.session_state.messages.append({"role": "assistant", "content": assistant_text})
            with st.chat_message("assistant"):
                st.markdown(assistant_text)
            return

        st.session_state.user_email = email
        assistant_text = f"Nice one — I’ll CC you in at {email}. Now, what’s the estate agent’s email address?"
        st.session_state.messages.append({"role": "assistant", "content": assistant_text})
        with st.chat_message("assistant"):
            st.markdown(assistant_text)
        return

    for e in extract_emails(user_input):
        st.session_state.seen_emails.add(e)

    context_messages = st.session_state.messages[-12:]
    result = generate_structured(context_messages)

  
    if result.get("action") == "send_email":
        to_email = (result.get("to") or "").strip()
        if not to_email or to_email not in st.session_state.seen_emails:
            result = {
                "assistant_text": "What’s the estate agent’s email address? Please paste it explicitly and I’ll send the message.",
                "action": "none",
                "to": "",
                "cc": [],
                "subject": "",
                "body": "",
            }


    if result.get("action") == "send_email":
        to_email = result["to"].strip()
        subject = (result.get("subject") or "").strip() or "Property enquiry"
        body = (result.get("body") or "").strip()

        try:
            gmail_client.send_email(
                to=to_email,
                subject=subject,
                body=body,
                cc=[st.session_state.user_email], 
            )
            assistant_text = f"Done — I’ve sent that and CC’d you in at {st.session_state.user_email}."
        except Exception as e:
            assistant_text = f"I couldn’t send the email. Details: {e}"
    else:
        assistant_text = (result.get("assistant_text") or "").strip() or "…"

    st.session_state.messages.append({"role": "assistant", "content": assistant_text})
    with st.chat_message("assistant"):
        st.markdown(assistant_text)


if __name__ == "__main__":
    run_app()

