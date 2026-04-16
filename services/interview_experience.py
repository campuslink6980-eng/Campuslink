"""
Interview Experience module: invite tokens, CSV parsing.
Business logic only. No DB, no HTTP, no Cloudinary.
"""
import csv
import io
import re
import secrets
from typing import List


def generate_invite_token() -> str:
    """Generate a secure random token for interview invite links."""
    return secrets.token_urlsafe(32)


def parse_csv_emails(csv_content: bytes | str) -> List[str]:
    """
    Parse CSV content and extract unique, valid email addresses.
    Expects first row as header; looks for a column containing 'email' (case-insensitive).
    Returns list of normalized (lowercase, stripped) emails.
    """
    if isinstance(csv_content, bytes):
        try:
            csv_content = csv_content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                csv_content = csv_content.decode("latin-1")
            except Exception:
                return []
    if not csv_content or not isinstance(csv_content, str):
        return []
    emails: List[str] = []
    seen: set = set()
    email_re = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    try:
        reader = csv.DictReader(io.StringIO(csv_content))
        if not reader.fieldnames:
            return []
        email_col = None
        for col in reader.fieldnames:
            if col and "email" in col.lower():
                email_col = col
                break
        if not email_col:
            return []
        for row in reader:
            val = (row.get(email_col) or "").strip()
            if not val:
                continue
            val = val.lower()
            if val in seen:
                continue
            if email_re.match(val):
                seen.add(val)
                emails.append(val)
    except Exception:
        return []
    return emails
