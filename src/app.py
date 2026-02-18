from __future__ import annotations

import streamlit as st

from src.config import (
    CREDENTIALS_PATH,
    TOKEN_PATH,
    GMAIL_SCOPES,
)
from src.gmail_client import GmailClient


CENTRAL_EMAIL = "lenah.test.enquiries@gmail.com"


def get_gmail_client() -> GmailClient:
    if "gmail_client" not in st.session_state:
        st.session_state.gmail_client = GmailClient(
            credentials_path=CREDENTIALS_PATH,
            token_path=TOKEN_PATH,
            scopes=GMAIL_SCOPES,
        )
    return st.session_state.gmail_client


def run_app() -> None:
    st.set_page_config(page_title="LENAH", layout="centered")
    st.title("LENAH")


    get_gmail_client()


    if "messages" not in st.session_state:
        st.session_state.messages = []

    
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

  
    user_input = st.chat_input("Message LENAH…")

    if user_input:
        st.session_state.messages.append(
            {"role": "user", "content": user_input}
        )
        st.rerun()


if __name__ == "__main__":
    run_app()
