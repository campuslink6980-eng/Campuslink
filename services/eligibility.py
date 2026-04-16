"""
Central eligibility check for job application.
Checks: profile verified, application deadline, CGPA, department, placement policy.
"""
import re
from datetime import date, datetime, timezone
from typing import List, Optional

APPLICATION_DEADLINE_PASSED_MSG = "Application deadline has passed."

from models import (
    VERIFICATION_VERIFIED,
    normalize_branch_code,
)
from services.placement_predictor import (
    _get_cgpa_on_10,
    _job_min_cgpa_on_10,
    important_criteria_passes_strict_apply,
)


def _norm_skill_token(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").strip().lower())


def parse_job_application_deadline_date(job: dict) -> Optional[date]:
    """Calendar date of the application deadline, or None if not set / unparsable."""
    raw = job.get("application_deadline") if job.get("application_deadline") is not None else job.get("deadline")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.date()
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    s = str(raw).strip()
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def application_deadline_end_utc(job: dict) -> Optional[datetime]:
    """End of the deadline calendar day in UTC (23:59:59.999999)."""
    d = parse_job_application_deadline_date(job)
    if d is None:
        return None
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999999, tzinfo=timezone.utc)


def application_deadline_end_utc_iso(job: dict) -> Optional[str]:
    end = application_deadline_end_utc(job)
    if end is None:
        return None
    s = end.isoformat()
    if s.endswith("+00:00"):
        return s.replace("+00:00", "Z")
    return s


def is_application_deadline_passed(job: dict, now: Optional[datetime] = None) -> bool:
    """
    True if current UTC time is after the end of the deadline date.
    Jobs with no parsable deadline are never treated as past due.
    """
    end = application_deadline_end_utc(job)
    if end is None:
        return False
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    return now > end


def compute_missing_required_skills_suggestions(student: dict, job: dict) -> List[str]:
    """
    Required job skills missing from the student profile — for UI hints only; never blocks apply.
    """
    req = job.get("required_skills") or job.get("requiredSkills") or []
    if not isinstance(req, list) or not req:
        return []
    profile = student.get("profile") or {}
    st_skills = profile.get("skills") or student.get("skills") or []
    if not isinstance(st_skills, list):
        st_skills = []
    norm_stu: set[str] = set()
    for x in st_skills:
        if isinstance(x, dict):
            nm = (x.get("name") or x.get("skill") or "").strip()
        else:
            nm = str(x).strip()
        if nm:
            norm_stu.add(_norm_skill_token(nm))
    out: List[str] = []
    seen: set[str] = set()
    for s in req:
        label = str(s).strip()
        if not label:
            continue
        token = _norm_skill_token(label)
        if token in seen:
            continue
        seen.add(token)
        if token not in norm_stu:
            out.append(label)
    return out


def check_placement_eligibility(
    student: dict,
    job: dict,
    policy: Optional[dict],
    profile_completion_min: int = 50,
) -> tuple[bool, List[str]]:
    """
    Full eligibility check for a student applying to a job.
    Returns (can_apply, list of rejection reasons).
    """
    reasons: List[str] = []

    verification_status = (student.get("verification_status") or "").strip().upper()
    if verification_status != VERIFICATION_VERIFIED:
        reasons.append("Profile not verified. Get your profile verified by faculty.")
        return False, reasons

    if is_application_deadline_passed(job):
        reasons.append(APPLICATION_DEADLINE_PASSED_MSG)
        return False, reasons

    allowed = (
        job.get("allowed_departments")
        or job.get("eligible_branches")
        or job.get("eligibleBranches")
        or job.get("branches_allowed")
        or []
    )
    allowed = [normalize_branch_code(b) for b in allowed if normalize_branch_code(b)]
    student_branch = normalize_branch_code(student.get("branch_code") or student.get("branch"))
    if allowed and (not student_branch or student_branch not in allowed):
        reasons.append("Branch not eligible")
        return False, reasons

    job_batch = str(job.get("batch_year") or "").strip()
    if job_batch:
        profile = student.get("profile") or {}
        edu = profile.get("education") or []
        grad_year = None
        if edu and isinstance(edu, list) and len(edu) > 0:
            e0 = edu[0] or {}
            grad_year = e0.get("graduation_year") or e0.get("year") or e0.get("passing_year")
        grad_year = grad_year or student.get("graduation_year") or student.get("passout_year")
        if grad_year is not None and str(grad_year).strip() != job_batch:
            reasons.append("Graduation year not eligible")
            return False, reasons

    min_cgpa = job.get("min_cgpa") or job.get("minCGPA")
    if min_cgpa is not None:
        min_cgpa_f = _job_min_cgpa_on_10(min_cgpa)
        if min_cgpa_f is not None:
            cgpa_10 = _get_cgpa_on_10(student)
            if cgpa_10 is None:
                reasons.append("CGPA not available.")
                return False, reasons
            if cgpa_10 < min_cgpa_f:
                reasons.append("CGPA requirement not met")
                return False, reasons

    if not important_criteria_passes_strict_apply(job, student):
        reasons.append("Important criteria not satisfied")
        return False, reasons

    backlog_crit = (job.get("backlog_criteria") or "").strip().lower()
    backlog_block = backlog_crit == "not allowed" or job.get("no_active_backlogs") or job.get("noActiveBacklogs")
    if backlog_block:
        ab = student.get("active_backlogs")
        if ab is None:
            ab = student.get("activeBacklogs")
        try:
            ab_n = int(ab or 0)
        except (TypeError, ValueError):
            ab_n = 0
        if ab_n != 0:
            reasons.append("This job does not allow active backlogs.")
            return False, reasons

    completion = int(student.get("profile_completion") or 0)
    if completion < profile_completion_min:
        reasons.append("Profile incomplete. Complete your profile to apply.")
        return False, reasons

    from services.placement_policy import check_can_apply_given_placement
    can_apply_placement, placement_reason = check_can_apply_given_placement(student, policy)
    if not can_apply_placement and placement_reason:
        reasons.append(placement_reason)
        return False, reasons

    return True, []
