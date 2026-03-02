from __future__ import annotations

import streamlit as st

from src.config import APP_TITLE, CREDENTIALS_PATH, TOKEN_PATH, GMAIL_SCOPES
from src.gmail_client import GmailClient
from src.llm import (
    ToolCall,
    chat,
    classify_draft_response,
    draft_agent_email,
    draft_reply_to_agent,
    draft_summary_email,
    refine_draft,
    summarise_agent_reply,
)
from src.session import UserStore
from src.utils import extract_first_email, is_valid_email, normalise_email


# ---------------------------------------------------------------------------
# Gmail client — cached for the lifetime of the Streamlit server process
# ---------------------------------------------------------------------------

@st.cache_resource
def _get_gmail_client() -> GmailClient:
    return GmailClient(
        credentials_path=str(CREDENTIALS_PATH),
        token_path=str(TOKEN_PATH),
        scopes=GMAIL_SCOPES,
    )


def _send_email(
    *,
    to: str,
    subject: str,
    body: str,
    cc: list[str] | None = None,
    reply_to: str | None = None,
    thread_id: str | None = None,
) -> tuple[str, str]:
    return _get_gmail_client().send_email(
        to=to, subject=subject, body=body,
        cc=cc, reply_to=reply_to, thread_id=thread_id,
    )


# ---------------------------------------------------------------------------
# Session-state helpers
# ---------------------------------------------------------------------------

def _init_state() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("user_email", None)
    st.session_state.setdefault("pending_email", None)
    # agent_email -> Gmail thread_id
    st.session_state.setdefault("agent_threads", {})
    # agent_email -> last Gmail message_id we sent (reply-detection cursor)
    st.session_state.setdefault("agent_last_message_id", {})


def _login_screen() -> bool:
    """Render the login gate. Returns True when the user is identified."""
    if st.session_state.get("_user_store") is not None:
        return True

    st.subheader("Who are you?")
    st.caption("Enter your email address to load your saved conversations.")

    email_input = st.text_input(
        "Your email address",
        key="_login_email_input",
        placeholder="you@example.com",
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        login_clicked = st.button("Continue", use_container_width=True, type="primary")
    with col2:
        clear_clicked = False
        if email_input and is_valid_email(normalise_email(email_input)):
            store_preview = UserStore(email_input)
            if store_preview.exists:
                clear_clicked = st.button("Clear saved data", use_container_width=True)

    if login_clicked:
        if not email_input or not is_valid_email(normalise_email(email_input)):
            st.error("Please enter a valid email address.")
            return False
        store = UserStore(email_input)
        _clear_user_state()            # wipe any stale data before loading
        st.session_state.update(store.load())
        st.session_state.user_email = store.email
        st.session_state["_user_store"] = store
        st.rerun()

    if clear_clicked:
        UserStore(email_input).delete()
        st.success("Saved data cleared. Reload the page to start fresh.")
        return False

    return False


def _clear_user_state() -> None:
    """Wipe all user-specific state keys. Called before loading a different user."""
    st.session_state["_user_store"] = None
    st.session_state.messages = []
    st.session_state.user_email = None
    st.session_state.pending_email = None
    st.session_state.agent_threads = {}
    st.session_state.agent_last_message_id = {}


def _save_state() -> None:
    """Persist current session state to disk for the logged-in user."""
    store: UserStore | None = st.session_state.get("_user_store")
    if isinstance(store, UserStore):
        store.save(st.session_state)


def _add(role: str, content: str) -> None:
    st.session_state.messages.append({"role": role, "content": content})


def _render_history() -> None:
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])


# ---------------------------------------------------------------------------
# Email parsing / detection
# ---------------------------------------------------------------------------

def _extract_email(text: str) -> str | None:
    found = extract_first_email(text or "")
    if found and is_valid_email(found):
        return normalise_email(found)
    return None


def _sniff_own_email(text: str) -> str | None:
    """
    Return an email address only when the user explicitly indicates it is theirs.
    Intentionally strict to avoid capturing an agent's address mid-flow.
    """
    t = (text or "").lower()
    cues = [
        "my email is", "my email:",
        "email me at", "send it to me at", "send it to my email",
        "cc me at", "cc me on",
        "you can cc me at", "you can email me at",
    ]
    if not any(c in t for c in cues):
        return None
    return _extract_email(text)


# ---------------------------------------------------------------------------
# Agent-reply polling
# ---------------------------------------------------------------------------

def _check_agent_replies() -> None:
    """
    Poll every known agent thread for new inbound messages.

    Surfaces one reply at a time to keep the UX manageable:
      1. Summarises the reply for the user.
      2. Drafts a suggested response.
      3. Enters 'review_draft' pending state so the user can approve or refine.

    The last-seen message cursor is advanced *before* LLM processing so a
    processing failure never causes the same message to be surfaced twice.
    """
    agent_threads: dict[str, str] = st.session_state.agent_threads

    if not agent_threads:
        _add("assistant", "I haven't emailed any agents yet — there's nothing to check.")
        return

    client = _get_gmail_client()

    for agent_email, thread_id in agent_threads.items():
        after_id = st.session_state.agent_last_message_id.get(agent_email)

        try:
            replies = client.get_new_replies(thread_id=thread_id, after_message_id=after_id)
        except Exception as exc:  # noqa: BLE001
            _add("assistant", f"Couldn't check replies from **{agent_email}**: `{exc}`")
            continue

        if not replies:
            continue

        latest = replies[-1]
        reply_body: str = latest["body"]
        reply_from: str = latest["from"]

        # Advance cursor before processing — prevents re-surfacing on failure.
        st.session_state.agent_last_message_id[agent_email] = latest["id"]

        try:
            summary = summarise_agent_reply(
                reply_body=reply_body,
                chat_history=st.session_state.messages,
            )
            draft_subject, draft_body = draft_reply_to_agent(
                reply_body=reply_body,
                chat_history=st.session_state.messages,
                user_request="",
            )
        except Exception as exc:  # noqa: BLE001
            _add("assistant", f"Got a reply from **{agent_email}** but couldn't process it: `{exc}`")
            return

        _add(
            "assistant",
            f"**{reply_from}** replied to your enquiry:\n\n"
            f"> {summary}\n\n"
            f"Here's a suggested reply:\n\n"
            f"---\n{draft_body}\n---\n\n"
            "Say **'send it'** to send this as-is, or tell me how to change it "
            "(e.g. *'make it more formal'*, *'ask about parking'*, *'keep it shorter'*).",
        )

        st.session_state.pending_email = {
            "action": "review_draft",
            "agent_email": agent_email,
            "thread_id": thread_id,
            "draft_subject": draft_subject,
            "draft_body": draft_body,
        }
        return  # one reply at a time

    _add("assistant", "No new replies from any agents yet.")


# ---------------------------------------------------------------------------
# Pending-email state machine
# ---------------------------------------------------------------------------

def _run_pending(user_text: str) -> None:
    """
    Advance whichever email flow is currently in st.session_state.pending_email.

    pending_email dict keys:
        action        : "summary" | "agent" | "review_draft"

        review_draft  : agent_email, thread_id, draft_subject, draft_body
        agent         : agent_email (str | None), user_request (str)
        summary       : (no extra keys)
    """
    p = st.session_state.pending_email
    t = (user_text or "").strip()
    found = _extract_email(t) if t else None

    # ------------------------------------------------------------------ #
    # review_draft — user approves or refines the suggested reply         #
    # ------------------------------------------------------------------ #
    if p["action"] == "review_draft":
        if not t:
            # Prompt already shown by _check_agent_replies; wait for input.
            return

        if classify_draft_response(t) == "approve":
            _send_draft_reply(p)
            return

        # Anything else is a refinement instruction.
        try:
            new_subject, new_body = refine_draft(
                draft_subject=p["draft_subject"],
                draft_body=p["draft_body"],
                instruction=t,
            )
        except Exception as exc:  # noqa: BLE001
            _add("assistant", f"Couldn't refine the draft: `{exc}`")
            return

        p["draft_subject"] = new_subject
        p["draft_body"] = new_body
        _add(
            "assistant",
            f"Here's the updated draft:\n\n---\n{new_body}\n---\n\n"
            "Say **'send it'** to send, or keep refining.",
        )
        return

    # ------------------------------------------------------------------ #
    # summary — send chat transcript to the user                          #
    # ------------------------------------------------------------------ #
    if p["action"] == "summary":
        if not st.session_state.user_email:
            if not found:
                _add("assistant", "What email address should I send it to?")
                return
            st.session_state.user_email = found

        try:
            subject, body = draft_summary_email(chat_history=st.session_state.messages)
            _send_email(to=st.session_state.user_email, subject=subject, body=body)
            _add("assistant", f"Done — summary sent to **{st.session_state.user_email}**.")
        except Exception as exc:  # noqa: BLE001
            _add("assistant", f"Sorry — couldn't send the summary: `{exc}`")

        st.session_state.pending_email = None
        return

    # ------------------------------------------------------------------ #
    # agent — send a fresh enquiry email to an estate agent               #
    # ------------------------------------------------------------------ #
    if p["action"] == "agent":
        # Step 1: collect agent email.
        if not p.get("agent_email"):
            if not found:
                _add("assistant", "Sure — what's the estate agent's email address?")
                return
            if st.session_state.user_email and found == st.session_state.user_email:
                _add("assistant", "That looks like your email — what's the estate agent's address?")
                return
            p["agent_email"] = found
            found = None  # don't re-use as the user's own address

        # Step 2: collect user CC address.
        if not st.session_state.user_email:
            if not found:
                _add("assistant", "What email should I CC you on?")
                return
            if found == p["agent_email"]:
                _add("assistant", "That looks like the agent's email — what email should I CC you on?")
                return
            st.session_state.user_email = found

        # Step 3: send.
        try:
            subject, body = draft_agent_email(
                chat_history=st.session_state.messages,
                user_request=p.get("user_request", ""),
            )
            thread_id = st.session_state.agent_threads.get(p["agent_email"])
            _msg_id, new_thread_id = _send_email(
                to=p["agent_email"],
                subject=subject,
                body=body,
                cc=[st.session_state.user_email],
                # No reply_to — agent replies must land in LENAH's Gmail
                # so get_new_replies() can find them. User stays in loop via CC.
                thread_id=thread_id,
            )
            st.session_state.agent_threads[p["agent_email"]] = new_thread_id
            st.session_state.agent_last_message_id[p["agent_email"]] = _msg_id
            _add(
                "assistant",
                f"Done — emailed **{p['agent_email']}** and CC'd you "
                f"at **{st.session_state.user_email}**.",
            )
        except Exception as exc:  # noqa: BLE001
            _add("assistant", f"Sorry — couldn't send the email: `{exc}`")

        st.session_state.pending_email = None
        return

    # Unknown action — clear to avoid getting stuck.
    _add("assistant", "Sorry — I don't recognise that email action.")
    st.session_state.pending_email = None


def _send_draft_reply(p: dict) -> None:
    """Send the approved draft reply and update thread / cursor state."""
    try:
        _msg_id, new_thread_id = _send_email(
            to=p["agent_email"],
            subject=p["draft_subject"],
            body=p["draft_body"],
            cc=[st.session_state.user_email] if st.session_state.user_email else None,
            # No reply_to — keep replies coming back to LENAH's Gmail.
            thread_id=p["thread_id"],
        )
        st.session_state.agent_threads[p["agent_email"]] = new_thread_id
        st.session_state.agent_last_message_id[p["agent_email"]] = _msg_id
        _add("assistant", f"Sent — replied to **{p['agent_email']}**.")
    except Exception as exc:  # noqa: BLE001
        _add("assistant", f"Sorry — couldn't send the reply: `{exc}`")
    finally:
        st.session_state.pending_email = None


# ---------------------------------------------------------------------------
# Main message dispatcher
# ---------------------------------------------------------------------------

def _handle_message(user_text: str) -> None:
    # Only sniff for the user's own email when not mid-flow — inside a pending
    # flow the disambiguation logic in _run_pending takes precedence.
    if st.session_state.pending_email is None:
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
        return

    # ToolCall — set pending state then immediately kick off the flow with an
    # empty string so any first missing-info prompt is shown right away.
    if result.name == "send_summary_to_user":
        st.session_state.pending_email = {
            "action": "summary",
            "agent_email": None,
        }
    elif result.name == "send_email_to_agent":
        st.session_state.pending_email = {
            "action": "agent",
            "user_request": user_text,
            "agent_email": result.args.get("agent_email") or None,
        }

    _run_pending("")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="centered")
    st.title(APP_TITLE)

    _init_state()

    if not _login_screen():
        return

    # -- Sidebar: reply checker + active thread list ------------------------
    with st.sidebar:
        st.header("Agent replies")
        if st.button("🔍 Check for new replies", use_container_width=True):
            with st.spinner("Checking inboxes…"):
                _check_agent_replies()
            _save_state()
            st.rerun()

        if st.session_state.agent_threads:
            st.divider()
            st.caption("Active threads")
            for email in st.session_state.agent_threads:
                st.caption(f"• {email}")

        st.divider()
        if st.button("🆕 New chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.pending_email = None
            _save_state()
            st.rerun()

    # -- Main chat area -----------------------------------------------------
    _render_history()

    user_text = st.chat_input("Message LENAH…")
    if not user_text:
        return

    _add("user", user_text)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        placeholder.write("Thinking…")

    _handle_message(user_text)

    placeholder.empty()
    _save_state()
    st.rerun()


if __name__ == "__main__":
    main()