"""
Placement policy: one job, multiple offer, dream company threshold.
Single active policy per system.
"""
from datetime import datetime
from typing import Any, Optional

from models import (
    PLACEMENT_STATUS_PLACED,
)


def get_active_policy(db) -> Optional[dict]:
    """Return the single active placement policy document, or None."""
    return db["placement_policies"].find_one({"active": True})


def get_default_policy() -> dict:
    return {
        "one_job_policy": False,
        "multiple_offer_allowed": True,
        "dream_company_threshold": None,
        "active": True,
        "updated_at": datetime.utcnow(),
    }


def ensure_default_policy(db) -> dict:
    """Ensure one active policy exists; create default if none."""
    policy = get_active_policy(db)
    if policy:
        return policy
    default = get_default_policy()
    default["created_at"] = datetime.utcnow()
    db["placement_policies"].insert_one(default)
    return db["placement_policies"].find_one({"active": True})


def check_can_apply_given_placement(
    student: dict,
    policy: Optional[dict],
) -> tuple[bool, Optional[str]]:
    """
    Check if student can apply based on placement status and policy.
    Returns (can_apply, rejection_reason).
    """
    if not policy:
        return True, None
    placement_status = (student.get("placement_status") or student.get("profile", {}).get("placement_status") or "").strip().upper()
    if placement_status != "PLACED" and placement_status != PLACEMENT_STATUS_PLACED:
        return True, None
    one_job = policy.get("one_job_policy") is True
    if one_job:
        return False, "You are already placed. One job policy is active."
    return True, None
