from __future__ import annotations

import streamlit as st

from src.config import APP_TITLE, CREDENTIALS_PATH, TOKEN_PATH, GMAIL_SCOPES
from src.gmail_client import GmailClient
from src.llm import decide_next_action, chat_reply, draft_agent_email, draft_summary_email
from src.utils import extract_first_email, is_valid_email, normalise_email


def get_gmail_client() -> GmailClient:
    return GmailClient(
        credentials_path=str(CREDENTIALS_PATH),
        token_path=str(TOKEN_PATH),
        scopes=GMAIL_SCOPES,
    )


def send_email(*, to: str, subject: str, body: str, cc: list[str] | None = None) -> str:
    gmail = get_gmail_client()
    return gmail.send_email(to=to, subject=subject, body=body, cc=cc)


def init_state() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("user_email", None)

    st.session_state.setdefault("pending_email", None)

    st.session_state.setdefault("pending_user_text", None)
    st.session_state.setdefault("awaiting_reply", False)


    st.session_state.setdefault("last_email_intent", None)          
    st.session_state.setdefault("pending_agent_request", None)     


def add_message(role: str, content: str) -> None:
    st.session_state.messages.append({"role": role, "content": content})


def render_chat() -> None:
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])


def extract_email_if_explicit_user_email(text: str) -> str | None:
    t = (text or "").lower()
    cues = [
        "my email is",
        "my email:",
        "email me at",
        "send it to",
        "send to",
        "cc me at",
        "cc me on",
        "you can cc me",
        "you can email me",
    ]
    if not any(c in t for c in cues):
        return None

    e = extract_first_email(text)
    if e and is_valid_email(e):
        return normalise_email(e)
    return None


def ask_for_user_email(prompt: str = "Sure — what email should I send it to?") -> None:
    add_message("assistant", prompt)
    st.rerun()


def ask_for_agent_email() -> None:
    add_message("assistant", "Sure — what’s the estate agent’s email address?")
    st.rerun()


def handle_pending_email(user_text: str) -> None:
    pending = st.session_state.pending_email
    if not pending:
        return

    found = extract_first_email(user_text)
    found_norm = normalise_email(found) if (found and is_valid_email(found)) else None

    if pending.get("missing") == "user_email":
        if found_norm:
            st.session_state.user_email = found_norm
            pending.pop("missing", None)
        else:
            ask_for_user_email()
            return

    if pending.get("missing") == "agent_email":
        if found_norm:
            pending["agent_email"] = found_norm
            pending.pop("missing", None)
        else:
            ask_for_agent_email()
            return

    if pending.get("action") == "AGENT" and not st.session_state.user_email:
        pending["missing"] = "user_email"
        ask_for_user_email("And what email should I CC you on?")
        return

    if pending.get("missing") == "user_email":
        ask_for_user_email()
        return
    if pending.get("missing") == "agent_email":
        ask_for_agent_email()
        return

    try:
        if pending.get("action") == "SUMMARY":
            user_email = st.session_state.user_email
            if not user_email:
                pending["missing"] = "user_email"
                ask_for_user_email()
                return

            subject, body = draft_summary_email(chat_history=st.session_state.messages)
            msg_id = send_email(to=user_email, subject=subject, body=body, cc=None)
            add_message("assistant", f"Sent. Gmail message id: `{msg_id}`")
            st.session_state.pending_email = None
            st.session_state.last_email_intent = "SUMMARY"
            st.rerun()

        if pending.get("action") == "AGENT":
            agent_email = pending.get("agent_email")
            user_email = st.session_state.user_email
            user_request = pending.get("user_request", "")

            if not agent_email:
                pending["missing"] = "agent_email"
                ask_for_agent_email()
                return
            if not user_email:
                pending["missing"] = "user_email"
                ask_for_user_email("And what email should I CC you on?")
                return

            subject, body = draft_agent_email(
                chat_history=st.session_state.messages,
                user_request=user_request,
            )
            msg_id = send_email(to=agent_email, subject=subject, body=body, cc=[user_email])

            add_message(
                "assistant",
                f"Sent. Gmail message id: `{msg_id}`\n\nTo: `{agent_email}`\nCC: `{user_email}`",
            )
            st.session_state.pending_email = None
            st.session_state.last_email_intent = "AGENT"
            st.session_state.pending_agent_request = None
            st.rerun()

        st.session_state.pending_email = None

    except Exception as e:
        st.session_state.pending_email = None
        add_message("assistant", f"I couldn’t send the email due to an error: `{e}`")
        st.rerun()


def process_text(text: str) -> None:
    if st.session_state.pending_email:
        handle_pending_email(text)
        return

    explicit_user_email = extract_email_if_explicit_user_email(text)
    if explicit_user_email:
        st.session_state.user_email = explicit_user_email


    decision = decide_next_action(user_text=text, chat_history=st.session_state.messages)

    if decision == "EMAIL_SUMMARY_TO_USER":
        st.session_state.last_email_intent = "SUMMARY"

        if st.session_state.user_email:
            st.session_state.pending_email = {"action": "SUMMARY"}
            handle_pending_email("")
            return

        st.session_state.pending_email = {"action": "SUMMARY", "missing": "user_email"}
        ask_for_user_email()
        return

    if decision == "EMAIL_AGENT":

        st.session_state.last_email_intent = "AGENT"
        st.session_state.pending_agent_request = st.session_state.pending_agent_request or text

        agent_email = None
        found = extract_first_email(text)
        if found and is_valid_email(found):
            agent_email = normalise_email(found)

        pending = {"action": "AGENT", "user_request": st.session_state.pending_agent_request}

        if agent_email:
            pending["agent_email"] = agent_email
        else:
            pending["missing"] = "agent_email"

        st.session_state.pending_email = pending

        if pending.get("missing") == "agent_email":
            ask_for_agent_email()
            return

        if not st.session_state.user_email:
            st.session_state.pending_email["missing"] = "user_email"
            ask_for_user_email("And what email should I CC you on?")
            return

        handle_pending_email("")
        return

    # CHAT
    reply = chat_reply(
        chat_history=st.session_state.messages,
        user_text=text,
        user_email=st.session_state.user_email,
    )
    add_message("assistant", reply)
    st.rerun()


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="centered")
    st.title(APP_TITLE)

    init_state()
    render_chat()

    user_text = st.chat_input("Message LENAH…")
    if user_text:
        add_message("user", user_text)
        st.session_state.pending_user_text = user_text
        st.session_state.awaiting_reply = True
        st.rerun()

    if st.session_state.awaiting_reply and st.session_state.pending_user_text:
        text = st.session_state.pending_user_text
        st.session_state.pending_user_text = None
        st.session_state.awaiting_reply = False

        with st.chat_message("assistant"):
            st.write("Thinking…")

        process_text(text)


if __name__ == "__main__":
    main()