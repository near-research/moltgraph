"""Shared Moltbook API client for the overlap pipeline.

Provides authenticated session creation and rate-limited GET requests.
"""

from __future__ import annotations

import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://www.moltbook.com/api/v1"
REQUEST_DELAY = 0.65


def get_api_key() -> str:
    """Load API key from environment, exit if missing."""
    key = os.environ.get("MOLTBOOK_API_KEY", "")
    if not key:
        sys.exit("Error: No API key. Set MOLTBOOK_API_KEY in .env or environment.")
    return key


def create_session() -> requests.Session:
    """Create an authenticated requests session."""
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {get_api_key()}",
        "Accept": "application/json",
    })
    return session


def rate_limited_get(
    session: requests.Session,
    endpoint: str,
    params: dict | None = None,
    timeout: int = 30,
) -> dict:
    """GET with rate limiting and 429 retry. Returns parsed JSON."""
    time.sleep(REQUEST_DELAY)
    while True:
        resp = session.get(
            f"{BASE_URL}{endpoint}",
            params=params,
            timeout=timeout,
        )
        if resp.status_code == 429:
            body = resp.json()
            wait = float(body.get("retry_after_seconds", body.get("retry_after_minutes", 1) * 60))
            print(f"  Rate limited — waiting {wait:.0f}s")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
