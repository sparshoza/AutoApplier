import os
import re
import asyncio
import base64
import logging
from datetime import datetime, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger("job_pilot.email")

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "credentials.json")
TOKEN_PATH = os.path.join(os.path.dirname(__file__), "token.json")


class GmailHandler:
    def __init__(self):
        self._service = None

    def authenticate(self):
        creds = None
        if os.path.exists(TOKEN_PATH):
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(CREDENTIALS_PATH):
                    logger.error(
                        "Gmail credentials.json not found at %s. "
                        "Please set up Google Cloud OAuth credentials.",
                        CREDENTIALS_PATH,
                    )
                    return False
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
                creds = flow.run_local_server(port=0)

            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())

        self._service = build("gmail", "v1", credentials=creds)
        logger.info("Gmail API authenticated successfully.")
        return True

    def _search_messages(self, query: str, max_results: int = 5) -> list:
        if not self._service:
            return []
        try:
            result = self._service.users().messages().list(
                userId="me", q=query, maxResults=max_results
            ).execute()
            return result.get("messages", [])
        except Exception as e:
            logger.error("Gmail search failed: %s", e)
            return []

    def _get_message_body(self, msg_id: str) -> str:
        if not self._service:
            return ""
        try:
            msg = self._service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()
            return self._extract_body(msg.get("payload", {}))
        except Exception as e:
            logger.error("Failed to get message body: %s", e)
            return ""

    def _extract_body(self, payload: dict) -> str:
        """Recursively extract text content from the email payload."""
        body = ""
        if payload.get("body", {}).get("data"):
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

        for part in payload.get("parts", []):
            mime = part.get("mimeType", "")
            if mime in ("text/plain", "text/html"):
                data = part.get("body", {}).get("data", "")
                if data:
                    body += base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            elif part.get("parts"):
                body += self._extract_body(part)

        return body

    def _find_otp_in_text(self, text: str) -> str | None:
        """Find a 4-8 digit OTP code in text."""
        matches = re.findall(r"\b(\d{4,8})\b", text)
        for m in matches:
            if len(m) >= 4:
                return m
        return None

    def _find_verify_link(self, text: str) -> str | None:
        """Find a verification URL in text."""
        urls = re.findall(r'https?://[^\s<>"\']+', text)
        for url in urls:
            if any(kw in url.lower() for kw in ["verify", "confirm", "validate", "token"]):
                return url
        return None

    async def poll_for_otp(
        self,
        sender_address: str,
        timeout_seconds: int = 120,
        poll_interval: float = 3.0,
    ) -> dict | None:
        """
        Poll Gmail for an OTP or verification link from the given sender.
        Returns {"otp": "123456"} or {"link": "https://..."} or None on timeout.
        """
        if not self._service:
            if not self.authenticate():
                return None

        start = asyncio.get_event_loop().time()
        query = f"from:{sender_address} newer_than:2m is:unread"

        while (asyncio.get_event_loop().time() - start) < timeout_seconds:
            messages = await asyncio.to_thread(self._search_messages, query)
            for msg_ref in messages:
                body = await asyncio.to_thread(self._get_message_body, msg_ref["id"])
                if not body:
                    continue

                otp = self._find_otp_in_text(body)
                if otp:
                    logger.info("OTP found: %s", otp)
                    return {"otp": otp}

                link = self._find_verify_link(body)
                if link:
                    logger.info("Verification link found: %s", link[:80])
                    return {"link": link}

            await asyncio.sleep(poll_interval)

        logger.warning("OTP poll timed out after %ds for sender %s", timeout_seconds, sender_address)
        return None
