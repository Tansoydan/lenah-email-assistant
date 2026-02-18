from __future__ import annotations

import base64
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Sequence

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


@dataclass
class GmailClient:
    credentials_path: str
    token_path: str
    scopes: Sequence[str]

    def _get_creds(self) -> Credentials:
        creds: Credentials | None = None
        token_file = Path(self.token_path)

        if token_file.exists():
            creds = Credentials.from_authorized_user_file(str(token_file), self.scopes)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path,
                    self.scopes,
                )
                creds = flow.run_local_server(port=0)

            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(creds.to_json(), encoding="utf-8")

        return creds

    def service(self):
        creds = self._get_creds()
        return build("gmail", "v1", credentials=creds)

    @staticmethod
    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("utf-8")

    def send_email(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        cc: list[str] | None = None,
    ) -> str:
        """
        Sends from the authenticated Gmail account (LENAH mailbox).
        Returns Gmail message id.
        """
        cc = cc or []

        msg = EmailMessage()
        msg["To"] = to
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = subject
        msg.set_content(body)

        raw = self._b64url(msg.as_bytes())
        svc = self.service()

        sent = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return sent["id"]

