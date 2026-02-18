from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


PROJECT_ROOT = Path(__file__).resolve().parents[1]

CREDENTIALS_PATH = Path(os.getenv("GMAIL_CREDENTIALS_PATH", PROJECT_ROOT / "credentials.json"))
TOKEN_PATH = Path(os.getenv("GMAIL_TOKEN_PATH", PROJECT_ROOT / "token.json"))

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

APP_TITLE = "LENAH — Property Email Assitant"
DEFAULT_FROM_NAME = "LENAH"
