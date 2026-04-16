"""
Master student list validation (MongoDB `student` collection).
Uses field names: First Name, Last Name, RollNo (see imported data / admin uploads).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple


def normalize_roll(value) -> str:
    if value is None:
        return ""
    return "".join(ch for ch in str(value) if ch.isdigit())


def _roll_match_filter(roll_clean: str) -> Dict[str, Any]:
    opts: list = [{"RollNo": roll_clean}]
    if roll_clean.isdigit():
        try:
            opts.append({"RollNo": int(roll_clean)})
        except ValueError:
            pass
    return {"$or": opts} if len(opts) > 1 else opts[0]


def find_master_document_by_roll(db, roll_clean: str) -> Optional[Dict[str, Any]]:
    """Any master row with this roll (ignores names)."""
    if not roll_clean:
        return None
    try:
        coll = db["student"]
    except Exception:
        return None
    return coll.find_one(_roll_match_filter(roll_clean))


def find_master_student_by_identity(
    db, first_name: str, last_name: str, roll_clean: str
) -> Optional[Dict[str, Any]]:
    """Exact roll + case-insensitive whole-string match on First Name and Last Name."""
    if not roll_clean:
        return None
    fn = (first_name or "").strip()
    ln = (last_name or "").strip()
    if not fn or not ln:
        return None
    try:
        coll = db["student"]
    except Exception:
        return None
    roll_part = _roll_match_filter(roll_clean)
    query = {
        "$and": [
            roll_part,
            {"First Name": {"$regex": f"^{re.escape(fn)}$", "$options": "i"}},
            {"Last Name": {"$regex": f"^{re.escape(ln)}$", "$options": "i"}},
        ]
    }
    return coll.find_one(query)


def validate_student_registration_against_master(
    db, first_name: str, last_name: str, roll_raw: str
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Returns (master_doc, None) on success, or (None, error_message).
    """
    roll_clean = normalize_roll(roll_raw)
    if not roll_clean:
        return None, "Incorrect Roll Number"
    fn = (first_name or "").strip()
    ln = (last_name or "").strip()
    if not fn or not ln:
        return None, "Invalid Name or Roll Number. Please check your details."

    master = find_master_student_by_identity(db, fn, ln, roll_clean)
    if master:
        return master, None

    if not find_master_document_by_roll(db, roll_clean):
        return None, "Incorrect Roll Number"
    return None, "Name does not match our records"


def existing_student_user_matches_master(db, user: Dict[str, Any]) -> bool:
    """True if first_name + last_name + roll_number match a master document."""
    roll = normalize_roll(user.get("roll_number"))
    if not roll:
        return False
    fn = (user.get("first_name") or "").strip()
    ln = (user.get("last_name") or "").strip()
    if not fn or not ln:
        return False
    return find_master_student_by_identity(db, fn, ln, roll) is not None
