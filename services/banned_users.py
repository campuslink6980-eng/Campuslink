"""
Permanent email ban list + helpers (rejected students, etc.).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from models import VERIFICATION_REJECTED

COLLECTION = "banned_users"

# Registration, login, and password flows when the email/account is banned.
ACCOUNT_BANNED_AUTH_MESSAGE = (
    "Your account has been rejected and permanently banned. "
    "You cannot register or login with this email again."
)


def normalize_ban_email(email: Optional[str]) -> str:
    return (email or "").strip().lower()


def user_is_banned(user: Optional[dict]) -> bool:
    if not user:
        return False
    if user.get("is_banned") is True:
        return True
    st = (user.get("account_status") or user.get("status") or "").strip().lower()
    return st == "rejected"


def user_hidden_from_campuslink_discovery(user: Optional[dict]) -> bool:
    """
    True for permanently banned or faculty-rejected accounts: exclude from search,
    public profile, connection lists, and feeds (treated as removed from the product).
    """
    if not user:
        return True
    if user_is_banned(user):
        return True
    if (user.get("verification_status") or "").strip().upper() == VERIFICATION_REJECTED:
        return True
    return False


def is_email_banned(db, email: str) -> bool:
    em = normalize_ban_email(email)
    if not em:
        return False
    return db[COLLECTION].find_one({"email": em}) is not None


def record_ban(
    db,
    email: str,
    reason: str,
    *,
    banned_by: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    em = normalize_ban_email(email)
    if not em:
        return
    doc: Dict[str, Any] = {
        "email": em,
        "reason": reason or "Rejected during profile verification",
        "banned_at": datetime.utcnow(),
        "banned_by": banned_by,
    }
    if extra:
        doc.update(extra)
    db[COLLECTION].update_one({"email": em}, {"$set": doc}, upsert=True)


def ensure_banned_users_indexes(db) -> None:
    try:
        db[COLLECTION].create_index("email", unique=True)
    except Exception:
        pass
