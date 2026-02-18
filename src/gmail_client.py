from __future__ import annotations

import base64
from email.message import EmailMessage
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


class GmailClient:
    def __init__(self, credentials_path: Path, token_path: Path, scopes: list[str]):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.scopes = scopes

    def _load_credentials(self) -> Credentials:
        creds: Credentials | None = None

        # Load existing token if present
        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), self.scopes)

        # If not valid, refresh or do OAuth
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self.credentials_path.exists():
                    raise FileNotFoundError(
                        f"Missing credentials.json at: {self.credentials_path}\n"
                        "Download it from Google Cloud Console (OAuth client) and place it in the project root."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), self.scopes)
                # Opens a browser window for you to login to the CENTRAL mailbox
                creds = flow.run_local_server(port=0)

            # Save token for next time
            self.token_path.write_text(creds.to_json(), encoding="utf-8")

        return creds

    def create_draft(self, to_email: str, subject: str, body: str) -> str:
        """
        Creates a Gmail draft and returns the draft ID.
        """
        creds = self._load_credentials()
        service = build("gmail", "v1", credentials=creds)

        msg = EmailMessage()
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)

        encoded_message = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

        draft_body = {"message": {"raw": encoded_message}}
        draft = service.users().drafts().create(userId="me", body=draft_body).execute()

        return draft["id"]

def get_profile_email(self) -> str:
    profile = self.service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "")
