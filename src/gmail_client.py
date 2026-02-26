from __future__ import annotations

import base64
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Sequence

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


@dataclass
class GmailClient:
    credentials_path: str
    token_path: str
    scopes: Sequence[str]

    # ------------------------------------------------------------------
    # Auth / service
    # ------------------------------------------------------------------

    def _get_creds(self) -> Credentials:
        creds: Credentials | None = None
        token_file = Path(self.token_path)
        if token_file.exists():
            creds = Credentials.from_authorized_user_file(str(token_file), self.scopes)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                from google_auth_oauthlib.flow import InstalledAppFlow

                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, self.scopes
                )
                creds = flow.run_local_server(port=0)
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(creds.to_json(), encoding="utf-8")
        return creds

    def service(self):
        # Cached on the instance so credentials are refreshed at most once.
        if not hasattr(self, "_service"):
            object.__setattr__(
                self, "_service", build("gmail", "v1", credentials=self._get_creds())
            )
        return self._service

    # ------------------------------------------------------------------
    # Encoding helper
    # ------------------------------------------------------------------

    @staticmethod
    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("utf-8")

    # ------------------------------------------------------------------
    # Fetch helpers — metadata
    # ------------------------------------------------------------------

    def get_message(self, message_id: str) -> dict:
        return (
            self.service()
            .users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["Message-Id", "References"],
            )
            .execute()
        )

    def get_thread(self, thread_id: str) -> dict:
        """Returns thread with metadata only (no body). Used for threading headers."""
        return (
            self.service()
            .users()
            .threads()
            .get(
                userId="me",
                id=thread_id,
                format="metadata",
                metadataHeaders=["Message-Id", "References", "From", "To", "Subject"],
            )
            .execute()
        )

    def get_thread_full(self, thread_id: str) -> dict:
        """Returns thread with full message payloads (includes body data)."""
        return (
            self.service()
            .users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )

    # ------------------------------------------------------------------
    # Body extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_plain_text(payload: dict) -> str:
        """
        Recursively extract plain-text content from a Gmail message payload.
        Prefers text/plain; falls back to text/html stripped of tags as a
        last resort (very naive — good enough for summarisation input).
        """
        mime = payload.get("mimeType", "")
        body_data: str = (payload.get("body") or {}).get("data", "")

        if mime == "text/plain" and body_data:
            padded = body_data + "=" * (-len(body_data) % 4)
            return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")

        if mime.startswith("multipart/"):
            # Prefer plain over html — try all parts in order.
            parts = payload.get("parts") or []
            plain_parts = [p for p in parts if p.get("mimeType") == "text/plain"]
            html_parts = [p for p in parts if p.get("mimeType") == "text/html"]
            for part in plain_parts + html_parts:
                text = GmailClient._extract_plain_text(part)
                if text:
                    return text
            # Recurse into nested multipart sections.
            for part in parts:
                text = GmailClient._extract_plain_text(part)
                if text:
                    return text

        if mime == "text/html" and body_data:
            import re
            padded = body_data + "=" * (-len(body_data) % 4)
            html = base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
            return re.sub(r"<[^>]+>", "", html).strip()

        return ""

    # ------------------------------------------------------------------
    # Reply detection
    # ------------------------------------------------------------------

    def get_new_replies(
        self,
        thread_id: str,
        after_message_id: str | None,
    ) -> list[dict]:
        """
        Returns messages in the thread that arrived *after* after_message_id.

        Each returned dict contains:
            id   : str  — Gmail message ID
            from : str  — sender address / display name
            body : str  — plain-text content of the message

        If after_message_id is None, all messages in the thread are returned.
        Only messages *not* sent by "me" are returned — we filter out our own
        outbound messages so we don't summarise our own drafts.
        """
        th = self.get_thread_full(thread_id)
        all_messages: list[dict] = th.get("messages") or []

        # Slice to messages after the reference point.
        if after_message_id:
            ids = [m["id"] for m in all_messages]
            if after_message_id in ids:
                cut = ids.index(after_message_id) + 1
                all_messages = all_messages[cut:]
            # If the reference ID isn't found (e.g. pruned), keep everything.

        result: list[dict] = []
        for msg in all_messages:
            # Skip messages we sent ourselves.
            label_ids = msg.get("labelIds") or []
            if "SENT" in label_ids:
                continue

            payload = msg.get("payload") or {}
            headers = payload.get("headers") or []

            def _header(name: str) -> str:
                return next(
                    (h["value"] for h in headers if h.get("name", "").lower() == name.lower()),
                    "",
                )

            result.append(
                {
                    "id": msg["id"],
                    "from": _header("From") or "Unknown sender",
                    "subject": _header("Subject"),
                    "body": self._extract_plain_text(payload),
                }
            )

        return result

    # ------------------------------------------------------------------
    # Threading helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_header(msg: dict, name: str) -> str | None:
        headers = (msg.get("payload") or {}).get("headers") or []
        for h in headers:
            if (h.get("name") or "").lower() == name.lower():
                v = (h.get("value") or "").strip()
                return v or None
        return None

    def _latest_rfc_ids(self, thread_id: str) -> tuple[str | None, str | None]:
        """
        Returns (in_reply_to, references) based on the latest message in thread.
        Used to correctly set threading headers on outbound replies.
        """
        th = self.get_thread(thread_id)
        messages = th.get("messages") or []
        if not messages:
            return None, None

        latest = messages[-1]
        latest_msgid = self._get_header(latest, "Message-Id")
        refs_existing = self._get_header(latest, "References")

        if not latest_msgid:
            return None, refs_existing

        references = f"{refs_existing} {latest_msgid}" if refs_existing else latest_msgid
        return latest_msgid, references

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def send_email(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        cc: list[str] | None = None,
        reply_to: str | None = None,
        thread_id: str | None = None,
    ) -> tuple[str, str]:
        """
        Send an email from the authenticated account.

        If thread_id is supplied the message is sent as a reply in that thread
        with correct In-Reply-To / References headers.

        Returns (gmail_message_id, thread_id).
        """
        cc = cc or []
        msg = EmailMessage()
        msg["To"] = to
        if cc:
            msg["Cc"] = ", ".join(cc)
        if reply_to:
            msg["Reply-To"] = reply_to

        if thread_id and not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        msg["Subject"] = subject

        if thread_id:
            in_reply_to, references = self._latest_rfc_ids(thread_id)
            if in_reply_to:
                msg["In-Reply-To"] = in_reply_to
            if references:
                msg["References"] = references

        msg.set_content(body)

        payload: dict = {"raw": self._b64url(msg.as_bytes())}
        if thread_id:
            payload["threadId"] = thread_id

        from googleapiclient.errors import HttpError  # noqa: PLC0415

        try:
            sent = self.service().users().messages().send(userId="me", body=payload).execute()
        except HttpError as exc:
            raise RuntimeError(f"Gmail send failed ({exc.status_code}): {exc.reason}") from exc

        return sent["id"], sent["threadId"]