from __future__ import annotations

import streamlit as st

from src.config import APP_TITLE, CREDENTIALS_PATH, TOKEN_PATH, GMAIL_SCOPES
from src.gmail_client import GmailClient
from src.llm import ToolCall, chat, draft_agent_email, draft_summary_email
from src.utils import extract_first_email, is_valid_email, normalise_email


def _send_email(*, to: str, subject: str, body: str, cc: list[str] | None = None) -> str:
    client = GmailClient(
        credentials_path=str(CREDENTIALS_PATH),
        token_path=str(TOKEN_PATH),
        scopes=GMAIL_SCOPES,
    )
    return client.send_email(to=to, subject=subject, body=body, cc=cc)



def _init_state() -> None:
    st.session_state.setdefault("messages", [])

    st.session_state.setdefault("user_email", None)

    st.session_state.setdefault("pending_email", None)


def _add(role: str, content: str) -> None:
    st.session_state.messages.append({"role": role, "content": content})


def _render_history() -> None:
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])


def _extract_email(text: str) -> str | None:
    """Return the first valid normalised email in text, or None."""
    found = extract_first_email(text or "")
    if found and is_valid_email(found):
        return normalise_email(found)
    return None


def _sniff_own_email(text: str) -> str | None:
    """
    Only treat an email address as the *user's own* when they explicitly say so.
    Avoids mis-capturing an agent's email as the user's email.
    """
    cues = [
        "my email is", "my email:", "email me at", "send it to me at",
        "send to me at", "cc me at", "cc me on",
        "you can cc me", "you can email me", "send to",
    ]
    if not any(c in (text or "").lower() for c in cues):
        return None
    return _extract_email(text)



def _run_pending(user_text: str) -> None:
    """
    Advance the pending email job. Adds assistant messages and calls
    st.rerun() internally — caller must NOT rerun again.
    """
    p = st.session_state.pending_email
    found = _extract_email(user_text) if user_text else None


    if p["action"] == "agent" and not p.get("agent_email"):
        if found:
            p["agent_email"] = found
            found = None  
        else:
            _add("assistant", "Sure! What's the estate agent's email address?")
            st.rerun()
            return

    if not st.session_state.user_email:
        if found:
            st.session_state.user_email = found
        else:
            q = (
                "And what email should I CC you on?"
                if p["action"] == "agent"
                else "Sure! What email address should I send it to?"
            )
            _add("assistant", q)
            st.rerun()
            return


    try:
        if p["action"] == "summary":
            subject, body = draft_summary_email(chat_history=st.session_state.messages)
            msg_id = _send_email(to=st.session_state.user_email, subject=subject, body=body)
            _add(
                "assistant",
                f"Done! I've sent the summary to **{st.session_state.user_email}**.\n\n"
                f"`{msg_id}`",
            )

        elif p["action"] == "agent":
            subject, body = draft_agent_email(
                chat_history=st.session_state.messages,
                user_request=p.get("user_request", ""),
            )
            msg_id = _send_email(
                to=p["agent_email"],
                subject=subject,
                body=body,
                cc=[st.session_state.user_email],
            )
            _add(
                "assistant",
                f"Done! Email sent to **{p['agent_email']}**, "
                f"CC'd to you at **{st.session_state.user_email}**.\n\n"
                f"`{msg_id}`",
            )

    except Exception as exc:
        _add("assistant", f"Sorry, something went wrong sending the email: `{exc}`")

    st.session_state.pending_email = None
    st.rerun()



def _handle_message(user_text: str) -> None:

    own_email = _sniff_own_email(user_text)
    if own_email:
        st.session_state.user_email = own_email

 
    if st.session_state.pending_email is not None:
        _run_pending(user_text)
        return


    result = chat(
        chat_history=st.session_state.messages,
        user_text=user_text,
        user_email=st.session_state.user_email,
    )

    if isinstance(result, str):
  
        _add("assistant", result)
        st.rerun()
        return


    if result.name == "send_summary_to_user":
        st.session_state.pending_email = {
            "action": "summary",
            "user_request": "",
            "agent_email": None,
        }

    elif result.name == "send_email_to_agent":

        agent_email = result.args.get("agent_email") or None
        st.session_state.pending_email = {
            "action": "agent",
            "user_request": user_text,
            "agent_email": agent_email,
        }

    _run_pending("")



def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="centered")
    st.title(APP_TITLE)

    _init_state()
    _render_history()

    user_text = st.chat_input("Message LENAH…")
    if user_text:
        _add("user", user_text)
        with st.chat_message("assistant"):
            st.write("Thinking…")
        _handle_message(user_text)


if __name__ == "__main__":
    main()