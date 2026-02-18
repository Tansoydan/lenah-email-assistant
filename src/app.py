from __future__ import annotations

import streamlit as st

from src.config import (
    APP_TITLE,
    CREDENTIALS_PATH,
    DEFAULT_FROM_NAME,
    GMAIL_SCOPES,
    TOKEN_PATH,
)
from src.email_template import build_email_draft
from src.gmail_client import GmailClient


st.set_page_config(page_title=APP_TITLE, layout="centered")
st.title(APP_TITLE)
st.caption("Type what you want to ask → create a Gmail draft (draft only, not sent).")


with st.expander("Setup checklist", expanded=False):
    st.markdown(
        f"""
- Put **credentials.json** in the project root: `{CREDENTIALS_PATH}`
- First run will open a browser window for Google login (use the **central mailbox**).
- A **token.json** will be created automatically here: `{TOKEN_PATH}`
"""
    )

st.divider()

to_email = st.text_input("Recipient email *", placeholder="agent@example.com")
your_name = st.text_input("Your name (optional)", value=DEFAULT_FROM_NAME)
subject = st.text_input("Subject (optional)", placeholder="Leave blank to auto-generate")
message = st.text_area(
    "Message / what you want to ask *",
    placeholder="Hi, please can you share availability for a viewing this week?\nAlso, is the property still available?",
    height=160,
)

col1, col2 = st.columns([1, 2])
with col1:
    create = st.button("Create Draft", type="primary")
with col2:
    st.write("")  # spacing


if create:
    try:
        if not to_email.strip():
            st.error("Please enter the recipient email.")
            st.stop()
        if not message.strip():
            st.error("Please enter the message you want to send.")
            st.stop()

        draft = build_email_draft(
            to_email=to_email,
            message=message,
            your_name=your_name,
            subject=subject,
        )

        client = GmailClient(
            credentials_path=CREDENTIALS_PATH,
            token_path=TOKEN_PATH,
            scopes=GMAIL_SCOPES,
        )

        draft_id = client.create_draft(draft.to_email, draft.subject, draft.body)

        st.success(f"Draft created ✅ (Draft ID: {draft_id})")
        st.subheader("Preview")
        st.markdown(f"**To:** {draft.to_email}")
        st.markdown(f"**Subject:** {draft.subject}")
        st.text(draft.body)

    except FileNotFoundError as e:
        st.error(str(e))
    except Exception as e:
        st.error(
            "Something went wrong while creating the draft.\n\n"
            f"Details: {e}"
        )
