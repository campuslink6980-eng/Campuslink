"""
Skill gap analysis: compare student skills with job required skills.
Business logic only. No DB, no HTTP.
"""
from typing import Any, Dict, List


def _normalize_skill(s: str) -> str:
    return s.strip().lower() if s else ""


def _get_student_skills_list(student: dict) -> List[str]:
    """Return list of skill strings from student/profile. Deduplicated, normalized for comparison."""
    profile = student.get("profile") or {}
    raw = profile.get("skills") or student.get("skills") or []
    if not isinstance(raw, list):
        return []
    seen = set()
    out = []
    for s in raw:
        if isinstance(s, str) and s.strip():
            n = _normalize_skill(s)
            if n and n not in seen:
                seen.add(n)
                out.append(s.strip())
        elif isinstance(s, dict) and s.get("name"):
            name = str(s.get("name", "")).strip()
            if name:
                n = _normalize_skill(name)
                if n not in seen:
                    seen.add(n)
                    out.append(name)
    return out


def _get_job_required_skills(job: dict) -> List[str]:
    """Return list of required skill strings. Deduplicated."""
    raw = job.get("required_skills") or job.get("requiredSkills") or []
    if not isinstance(raw, list):
        return []
    seen = set()
    out = []
    for s in raw:
        if isinstance(s, str) and s.strip():
            n = _normalize_skill(s)
            if n not in seen:
                seen.add(n)
                out.append(s.strip())
    return out


def analyze_skill_gap(student: dict, job: dict) -> Dict[str, Any]:
    """
    Compare student skills with job required skills.
    Case-insensitive. Duplicates removed.

    Returns:
        matched_skills: list of required skills the student has
        missing_skills: list of required skills the student does not have
        match_percentage: (len(matched_skills) / total_required) * 100, or 100 if no required skills
    """
    student_skills_norm = {_normalize_skill(s) for s in _get_student_skills_list(student)}
    required = _get_job_required_skills(job)
    if not required:
        return {
            "matched_skills": [],
            "missing_skills": [],
            "match_percentage": 100.0,
        }
    matched_skills: List[str] = []
    missing_skills: List[str] = []
    for r in required:
        rn = _normalize_skill(r)
        if rn in student_skills_norm:
            matched_skills.append(r)
        else:
            missing_skills.append(r)
    total = len(required)
    match_percentage = round((len(matched_skills) / total) * 100, 1) if total else 100.0
    return {
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "match_percentage": match_percentage,
    }
