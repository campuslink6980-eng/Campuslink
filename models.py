from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


ROLE_STUDENT = "STUDENT"
ROLE_FACULTY = "FACULTY"
ROLE_COORDINATOR = "COORDINATOR"
ROLE_ADMIN = "ADMIN"
ROLE_ALUMNI = "ALUMNI"

VERIFICATION_PENDING = "PENDING"
VERIFICATION_VERIFIED = "VERIFIED"
VERIFICATION_REJECTED = "REJECTED"
VERIFICATION_NEEDS_CORRECTION = "NEEDS_CORRECTION"

RESUME_PENDING = "PENDING"
RESUME_APPROVED = "APPROVED"
RESUME_REJECTED = "REJECTED"

PLACEMENT_STATUS_NOT_PLACED = "NOT_PLACED"
PLACEMENT_STATUS_PLACED = "PLACED"

APPLICATION_STATUS_APPLIED = "APPLIED"
APPLICATION_STATUS_SHORTLISTED = "SHORTLISTED"
APPLICATION_STATUS_REJECTED = "REJECTED"
APPLICATION_STATUS_SELECTED = "SELECTED"

# 6 departments for placement (CampusLink)
DEPARTMENTS = ["IT", "CST", "CE", "ENC", "AI", "DS"]


@dataclass(frozen=True)
class UserDefaults:
    role: str = ROLE_STUDENT
    branch_code: Optional[str] = None
    verification_status: str = VERIFICATION_PENDING
    profile_completion: int = 0


def derive_role_from_existing_user_type(user_type: Optional[str]) -> str:
    """
    Backward compatible: app.py historically used user_type values like
    'student', 'faculty', 'alumni', 'coordinator'. Maps to normalized roles.
    """
    if not user_type:
        return ROLE_STUDENT
    t = str(user_type).strip().lower()
    if t == "coordinator":
        return ROLE_COORDINATOR
    if t == "admin":
        return ROLE_ADMIN
    if t == "alumni":
        return ROLE_ALUMNI
    if t == "faculty":
        return ROLE_FACULTY
    return ROLE_STUDENT


def normalize_branch_code(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = str(value).strip().upper()
    return v or None


def apply_user_defaults(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Non-destructive: returns a new dict with missing fields filled.
    Does not overwrite existing values.
    """
    d = dict(doc or {})
    defaults = UserDefaults()

    if "role" not in d or not d.get("role"):
        d["role"] = derive_role_from_existing_user_type(d.get("user_type"))

    if "branch_code" not in d:
        # Try to infer from existing 'branch' when present.
        d["branch_code"] = normalize_branch_code(d.get("branch"))
    else:
        d["branch_code"] = normalize_branch_code(d.get("branch_code"))

    if "verification_status" not in d or not d.get("verification_status"):
        d["verification_status"] = defaults.verification_status

    if "profile_completion" not in d or d.get("profile_completion") is None:
        d["profile_completion"] = defaults.profile_completion

    # Ensure integer bounds for profile_completion.
    try:
        d["profile_completion"] = int(d.get("profile_completion", 0))
    except Exception:
        d["profile_completion"] = 0
    d["profile_completion"] = max(0, min(100, d["profile_completion"]))

    return d

