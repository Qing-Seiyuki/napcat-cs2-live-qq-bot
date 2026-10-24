"""Read a pending binding from the official bot's local database."""
from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _setting(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value or not ENV_PATH.exists():
        return value
    for line in ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
        key, sep, found = line.strip().partition("=")
        if sep and key == name:
            return found.strip().strip("\"'")
    return ""


def link_for_request(request_id: str) -> str | None:
    """Return a link only for a pending request in the configured shared DB."""
    if not re.fullmatch(r"[0-9a-f]{32}", request_id):
        return None
    public_url = _setting("STEAM_VERIFY_PUBLIC_URL")
    parsed = urlsplit(public_url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
            parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        return None
    db_value = _setting("QQ_BINDINGS_DB")
    if not db_value:
        return None
    db_path = Path(db_value).expanduser()
    if not db_path.is_absolute() or not db_path.is_file():
        return None
    try:
        with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as db:
            row = db.execute("SELECT status FROM bindings WHERE request_id=?", (request_id,)).fetchone()
    except sqlite3.Error:
        return None
    return f"{public_url.rstrip('/')}/verify/{request_id}" if row and row[0] == "pending" else None
