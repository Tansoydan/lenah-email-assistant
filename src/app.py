from __future__ import annotations

import re
import streamlit as st

APP_TITLE = "LENAH"
CENTRAL_MAILBOX = "lenah.test.enquiries@gmail.com"  # display only (no auth yet)


EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
URL_RE = re.compile(r"https?://\S+")


def extract_first_email(text: str) -> str | None:
    m = EMAIL_RE.search(text)
    return m.group(0) if m else None


def extract_first_url(text: str) -> str | None:
    m = URL_RE.search(text)
    return m.group(0) if m else None


def assistant_reply(user_text: str) -> str:
    """
    Placeholder behaviour only.
    Later: replace this with your LLM + tool calls.
    """
    user_email = st.session_state.get("user_email")
    url = extract_first_url(user_text)
    email_in_msg = extract_first_email(user_text)

    # Allow the user to provide their email at any time
    if email_in_msg:
        st.session_state.user_email = email_in_msg
        return f"Nice — I’ve got your email as **{email_in_msg}**. What would you like to do next?"

    # If they paste a property link but we don't have their email yet, ask for it
    if url and not user_email:
        st.session_state.pending_url = url
        return (
            "I can help with that link — what’s your email address?\n\n"
            "(You’ll be CC’d on messages sent from the central LENAH mailbox.)"
        )

    # If we have both, simulate “ready to draft” without doing anything
    pending_url = st.session_state.get("pending_url")
    if pending_url and user_email:
        st.session_state.pending_url = None
        return (
            "Got it. When the LLM is wired in, I’ll draft an enquiry email from the central mailbox and CC you.\n\n"
            f"**Link:** {pending_url}\n"
            f"**CC:** {user_email}\n\n"
            "For now, this is just the UI — no email will be created or sent."
        )

    # Generic fallback
    return (
        "Noted. For now I’m just the chat interface.\n\n"
        "Later I’ll:\n"
        "- understand your intent,\n"
        "- ask follow-ups if needed (e.g., your email),\n"
        "- draft/send from the central mailbox and CC you."
    )


def run_app() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="centered")
    st.title(APP_TITLE)
    st.caption("Chat UI only (no LLM, no Gmail actions yet).")

    with st.sidebar:
        st.subheader("Central mailbox (display only)")
        st.write(CENTRAL_MAILBOX)

        st.divider()
        st.subheader("Session")
        st.write("User email:", st.session_state.get("user_email") or "—")
        st.write("Pending link:", st.session_state.get("pending_url") or "—")

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Reset chat"):
                st.session_state.messages = []
                st.session_state.user_email = None
                st.session_state.pending_url = None
                st.rerun()
        with col_b:
            if st.button("Forget email"):
                st.session_state.user_email = None
                st.rerun()

    # Initialise chat history
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": (
                    "Hi — paste a Rightmove link or tell me what you want to do.\n\n"
                    "This is UI only for now."
                ),
            }
        ]
        st.session_state.user_email = None
        st.session_state.pending_url = None

    # Render chat
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    # Single input box
    user_text = st.chat_input("Message LENAH…")
    if not user_text:
        return

    # Add user message
    st.session_state.messages.append({"role": "user", "content": user_text})
    with st.chat_message("user"):
        st.markdown(user_text)

    # Assistant response (stub)
    reply = assistant_reply(user_text)
    st.session_state.messages.append({"role": "assistant", "content": reply})
    with st.chat_message("assistant"):
        st.markdown(reply)


if __name__ == "__main__":
    run_app()
