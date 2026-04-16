"""
Explainable placement prediction engine: strict eligibility, skill match (with partial/related
skills), important criteria (scoring only, never hard-fail), and weighted final score.

Final score (when eligible) = 60% skills + 20% important criteria + 10% extras + 10% projects.
All validation and scoring run server-side only.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from models import VERIFICATION_VERIFIED, normalize_branch_code

# --- Related skills: partial credit (0.5x weight of a full match) ---
RELATED_SKILLS: Dict[str, List[str]] = {
    "data visualization": ["power bi", "tableau", "looker", "qlik"],
    "pandas": ["data analysis", "numpy", "python", "scipy"],
    "numpy": ["pandas", "python", "scipy", "data analysis"],
    "machine learning": ["deep learning", "tensorflow", "pytorch", "scikit-learn", "sklearn"],
    "deep learning": ["machine learning", "tensorflow", "pytorch", "neural"],
    "react": ["javascript", "typescript", "next.js", "nextjs", "frontend"],
    "node.js": ["javascript", "typescript", "express", "backend"],
    "sql": ["mysql", "postgresql", "postgres", "database", "dbms"],
    "excel": ["spreadsheet", "google sheets", "data analysis"],
    "docker": ["kubernetes", "k8s", "devops", "container"],
    "kubernetes": ["docker", "devops", "k8s"],
    "aws": ["cloud", "azure", "gcp", "amazon web services"],
    "java": ["spring", "spring boot", "kotlin"],
    "c++": ["c", "stl", "algorithms"],
    "communication": ["presentation", "public speaking", "soft skills"],
}

# Important criteria: tag -> phrases that imply the tag in job text
IMPORTANT_TAG_PHRASES: Dict[str, List[str]] = {
    "hackathon": ["hackathon", "hackathons", "hack-a-thon", "hackathon participation"],
    "certification": ["certification", "certificate", "certified", "mscit", "vendor cert"],
    "open_source": ["open source", "github", "gitlab", "oss", "contributions"],
}

_OPEN_TO_MAP = {
    "internship": "Internships",
    "internships": "Internships",
    "full_time": "Full-time",
    "full-time": "Full-time",
    "fulltime": "Full-time",
    "projects": "Projects",
    "project": "Projects",
    "part_time": "Part-time",
    "part-time": "Part-time",
    "part time": "Part-time",
    "freelance": "Freelance",
    "remote": "Freelance",
}
_OPEN_TO_ALLOWED = {"Internships", "Full-time", "Projects", "Part-time", "Freelance"}


def _normalize_skill_token(s: str) -> str:
    return (s or "").strip().lower()


def _compact_skill(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").strip().lower())


def _parse_cgpa_input(raw: Any) -> Tuple[Optional[float], Optional[float]]:
    """
    Parse stored CGPA (number or string like '9.4', '9.4/10', '9.4 / 10.0').
    Returns (value, explicit_max_scale). When explicit_max_scale is set, value is on that scale.
    When explicit_max_scale is None, value is a plain GPA to interpret with profile cgpa_scale.
    """
    if raw is None:
        return None, None
    if isinstance(raw, bool):
        return None, None
    if isinstance(raw, (int, float)):
        return float(raw), None
    s = str(raw).strip()
    if not s:
        return None, None
    m = re.match(
        r"^\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*([0-9]+(?:\.[0-9]+)?)\s*$",
        s,
    )
    if m:
        return float(m.group(1)), float(m.group(2))
    m2 = re.search(r"\b([0-9]+(?:\.[0-9]+)?)\s*/\s*([0-9]+(?:\.[0-9]+)?)\b", s)
    if m2:
        return float(m2.group(1)), float(m2.group(2))
    m3 = re.search(r"([0-9]+(?:\.[0-9]+)?)", s)
    if m3:
        return float(m3.group(1)), None
    return None, None


def _profile_cgpa_scale(student: dict) -> float:
    """Max scale for CGPA (default 10). Handles string '10', '10.0', etc."""
    profile = student.get("profile") or {}
    raw = student.get("cgpa_scale") or profile.get("cgpa_scale")
    if raw is None or raw == "":
        return 10.0
    try:
        s = float(str(raw).strip())
        return s if s > 0 else 10.0
    except (TypeError, ValueError):
        return 10.0


def _get_cgpa_on_10(student: dict) -> Optional[float]:
    profile = student.get("profile") or {}
    edu = profile.get("education") or []
    cgpa_raw = None
    if edu and isinstance(edu, list) and len(edu) > 0:
        first = edu[0] if isinstance(edu[0], dict) else {}
        cgpa_raw = first.get("cgpa")
    if cgpa_raw is None:
        cgpa_raw = student.get("cgpa") or profile.get("cgpa")
    if cgpa_raw is None:
        return None
    val, denom = _parse_cgpa_input(cgpa_raw)
    if val is None or val < 0:
        return None
    if denom is not None and denom > 0:
        return round((val / denom) * 10.0, 2)
    scale = _profile_cgpa_scale(student)
    if abs(scale - 10.0) > 1e-9:
        return round((val / scale) * 10.0, 2)
    return round(val, 2)


def _job_min_cgpa_on_10(min_raw: Any) -> Optional[float]:
    """Parse job minimum CGPA (assumed on 10 unless given as x/y)."""
    if min_raw is None:
        return None
    mv, md = _parse_cgpa_input(min_raw)
    if mv is None:
        try:
            return round(float(min_raw), 2)
        except (TypeError, ValueError):
            return None
    if md is not None and md > 0:
        return round((mv / md) * 10.0, 2)
    return round(mv, 2)


def _get_skills_list(student: dict) -> List[str]:
    profile = student.get("profile") or {}
    raw = profile.get("skills") or student.get("skills") or []
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for s in raw:
        if isinstance(s, str) and s.strip():
            out.append(s.strip())
        elif isinstance(s, dict) and s.get("name"):
            out.append(str(s.get("name", "")).strip())
    return out


def _get_job_required_skills(job: dict) -> List[str]:
    raw = job.get("required_skills") or job.get("requiredSkills") or []
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    out: List[str] = []
    for s in raw:
        if isinstance(s, str) and s.strip():
            k = _compact_skill(s)
            if k and k not in seen:
                seen.add(k)
                out.append(s.strip())
    return out


def _canonical_student_open_to(student: dict) -> List[str]:
    profile = student.get("profile") or {}
    basic = profile.get("basic") or {}
    raw = profile.get("open_to") or basic.get("open_to") or []
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    seen: set[str] = set()
    for v in raw:
        if not isinstance(v, str):
            continue
        vv = v.strip()
        if not vv:
            continue
        key = vv.lower().replace(" ", "_")
        mapped = _OPEN_TO_MAP.get(key) or _OPEN_TO_MAP.get(vv.lower())
        if not mapped:
            mapped = vv if vv in _OPEN_TO_ALLOWED else None
        if mapped and mapped in _OPEN_TO_ALLOWED and mapped not in seen:
            seen.add(mapped)
            out.append(mapped)
    return out


def _job_open_to_requirement(job: dict) -> str:
    t = (job.get("job_type") or job.get("type") or "").strip()
    tl = t.lower()
    if "intern" in tl:
        return "Internships"
    if "part" in tl and "time" in tl:
        return "Part-time"
    if "project" in tl:
        return "Projects"
    if "full" in tl:
        return "Full-time"
    return "Full-time"


def _student_has_active_backlogs(student: dict) -> bool:
    ab = student.get("active_backlogs")
    if ab is None:
        ab = student.get("activeBacklogs")
    try:
        return int(ab or 0) != 0
    except (TypeError, ValueError):
        return False


def _job_blocks_backlogs(job: dict) -> bool:
    crit = (job.get("backlog_criteria") or "").strip().lower()
    if crit == "not allowed":
        return True
    if job.get("no_active_backlogs") or job.get("noActiveBacklogs"):
        return True
    return False


def _strict_eligibility(student: dict, job: dict) -> Tuple[bool, List[str]]:
    reasons: List[str] = []

    verification_status = (student.get("verification_status") or "").strip().upper()
    if verification_status != VERIFICATION_VERIFIED:
        reasons.append("Profile must be verified by faculty.")
        return False, reasons

    allowed = job.get("branches_allowed") or job.get("eligible_branches") or job.get("eligibleBranches") or []
    if not isinstance(allowed, list):
        allowed = []
    allowed = [normalize_branch_code(b) for b in allowed if normalize_branch_code(b)]
    student_branch = normalize_branch_code(student.get("branch_code") or student.get("branch"))
    if allowed and (not student_branch or student_branch not in allowed):
        reasons.append("Your branch is not eligible for this job.")
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
            reasons.append("Your graduation year is not eligible for this job.")
            return False, reasons

    min_cgpa = job.get("min_cgpa") if job.get("min_cgpa") is not None else job.get("minCGPA")
    if min_cgpa is not None:
        min_f = _job_min_cgpa_on_10(min_cgpa)
        if min_f is not None:
            cgpa_10 = _get_cgpa_on_10(student)
            if cgpa_10 is None:
                reasons.append("CGPA not available.")
                return False, reasons
            if cgpa_10 < min_f:
                reasons.append("CGPA is below the job minimum requirement.")
                return False, reasons

    if not important_criteria_passes_strict_apply(job, student):
        reasons.append("Important criteria not satisfied.")
        return False, reasons

    open_labels = _canonical_student_open_to(student)
    if not open_labels:
        reasons.append('Add your work preferences under “Open to” in your profile.')
        return False, reasons
    required_label = _job_open_to_requirement(job)
    if required_label not in open_labels:
        reasons.append(
            f"This job type ({required_label}) is not among your selected preferences."
        )
        return False, reasons

    if _job_blocks_backlogs(job) and _student_has_active_backlogs(student):
        reasons.append("This job does not allow active backlogs.")
        return False, reasons

    return True, []


def _parse_skill_weights(job: dict) -> Optional[List[Tuple[str, float]]]:
    raw = job.get("skill_match_weights") or job.get("skill_weights")
    if not isinstance(raw, list) or not raw:
        return None
    pairs: List[Tuple[str, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or item.get("skill") or "").strip()
        if not name:
            continue
        try:
            w = float(item.get("weight", 0))
        except (TypeError, ValueError):
            continue
        if w > 0:
            pairs.append((name, w))
    if not pairs:
        return None
    return pairs


def _compute_skill_match(job: dict, student_skills_display: List[str]) -> Dict[str, Any]:
    student_tokens = {_normalize_skill_token(s) for s in student_skills_display if s}
    student_compact = {_compact_skill(s) for s in student_skills_display if s}

    weights_spec = _parse_skill_weights(job)
    if weights_spec:
        job_items = [(n, w) for n, w in weights_spec]
        total_w = sum(w for _, w in job_items) or 1.0
    else:
        req = _get_job_required_skills(job)
        if not req:
            return {
                "percent": 100.0,
                "matched": [],
                "partial": [],
                "missing": [],
                "weight_mode": "none",
            }
        w_each = 100.0 / len(req)
        job_items = [(n, w_each) for n in req]
        total_w = 100.0

    matched: List[Dict[str, str]] = []
    partial: List[Dict[str, str]] = []
    missing: List[str] = []
    score = 0.0

    for skill_name, weight in job_items:
        unit = (weight / total_w) * 100.0
        sk_norm = _normalize_skill_token(skill_name)
        sk_c = _compact_skill(skill_name)

        if sk_norm in student_tokens or sk_c in student_compact:
            score += unit
            matched.append({"skill": skill_name, "kind": "full"})
            continue

        related = RELATED_SKILLS.get(sk_norm, [])
        hit = None
        for alt in related:
            an = _normalize_skill_token(alt)
            ac = _compact_skill(alt)
            if an in student_tokens or ac in student_compact:
                hit = alt
                break
        if hit:
            score += unit * 0.5
            partial.append({"skill": skill_name, "via": hit})
        else:
            missing.append(skill_name)

    return {
        "percent": round(min(100.0, max(0.0, score)), 1),
        "matched": matched,
        "partial": partial,
        "missing": missing,
        "weight_mode": "custom" if weights_spec else "equal",
    }


def _extract_important_tags(text: str) -> List[str]:
    if not (text or "").strip():
        return []
    low = text.lower()
    found: List[str] = []
    seen: set[str] = set()
    for tag, phrases in IMPORTANT_TAG_PHRASES.items():
        for ph in phrases:
            if ph in low:
                if tag not in seen:
                    seen.add(tag)
                    found.append(tag)
                break
    return found


def _profile_text_blob(student: dict) -> str:
    parts: List[str] = []
    profile = student.get("profile") or {}
    for key in ("headline", "summary", "bio"):
        v = profile.get(key) or student.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v.lower())
    for exp in profile.get("experience") or []:
        if isinstance(exp, dict):
            for k in ("title", "company", "description"):
                v = exp.get(k)
                if isinstance(v, str):
                    parts.append(v.lower())
    for proj in profile.get("projects") or []:
        if isinstance(proj, dict):
            for k in ("name", "title", "description"):
                v = proj.get(k)
                if isinstance(v, str):
                    parts.append(v.lower())
    for ach in profile.get("achievements") or []:
        if isinstance(ach, dict):
            t = ach.get("title") or ach.get("name")
            if isinstance(t, str):
                parts.append(t.lower())
    return " ".join(parts)


def _student_github_signals(student: dict) -> bool:
    profile = student.get("profile") or {}
    links = profile.get("links") or profile.get("social") or []
    if isinstance(links, list):
        for L in links:
            if isinstance(L, dict):
                u = (L.get("url") or L.get("link") or "").lower()
                if "github.com" in u or "gitlab.com" in u:
                    return True
            elif isinstance(L, str) and "github.com" in L.lower():
                return True
    blob = _profile_text_blob(student)
    return "github.com" in blob or "gitlab.com" in blob


def _student_hackathon_signals(student: dict) -> bool:
    blob = _profile_text_blob(student)
    return "hackathon" in blob


def _student_certification_signals(student: dict) -> bool:
    profile = student.get("profile") or {}
    certs = profile.get("certifications") or []
    if isinstance(certs, list) and len(certs) > 0:
        return True
    blob = _profile_text_blob(student)
    return "certification" in blob or "certificate" in blob


def _compute_important_criteria(job: dict, student: dict) -> Dict[str, Any]:
    enabled = bool(job.get("important_criteria_enabled"))
    raw_text = (job.get("important_criteria_text") or "").strip()
    if not enabled or not raw_text:
        return {
            "percent": 100.0,
            "tags_evaluated": [],
            "details": [],
            "skipped": True,
        }

    tags = _extract_important_tags(raw_text)
    if not tags:
        return {
            "percent": 60.0,
            "tags_evaluated": [],
            "details": [
                {
                    "tag": "general",
                    "met": True,
                    "label": "No recognized tags in the text — moderate neutral score (not a penalty).",
                }
            ],
            "skipped": False,
        }

    details: List[Dict[str, Any]] = []
    met_count = 0
    for tag in tags:
        ok = False
        label = tag.replace("_", " ").title()
        if tag == "hackathon":
            ok = _student_hackathon_signals(student)
            label = "Hackathon participation"
        elif tag == "certification":
            ok = _student_certification_signals(student)
            label = "Certification / credentials"
        elif tag == "open_source":
            ok = _student_github_signals(student)
            label = "Open source / GitHub activity"
        if ok:
            met_count += 1
        details.append({"tag": tag, "met": ok, "label": label})

    pct = round(100.0 * met_count / len(tags), 1)
    return {
        "percent": pct,
        "tags_evaluated": tags,
        "details": details,
        "skipped": False,
    }


def important_criteria_passes_strict_apply(job: dict, student: dict) -> bool:
    """
    When important_criteria_enabled with non-empty text, every inferred criterion must be met
    (same signals as placement predictor). If disabled or skipped, returns True.
    """
    if not bool(job.get("important_criteria_enabled")):
        return True
    raw_text = (job.get("important_criteria_text") or "").strip()
    if not raw_text:
        return True
    block = _compute_important_criteria(job, student)
    if block.get("skipped"):
        return True
    for d in block.get("details") or []:
        if isinstance(d, dict) and not d.get("met"):
            return False
    return True


def _compute_extras_percent(student: dict) -> float:
    profile = student.get("profile") or {}
    certs = profile.get("certifications") or []
    ach = profile.get("achievements") or []
    n_c = len(certs) if isinstance(certs, list) else 0
    n_a = len(ach) if isinstance(ach, list) else 0
    score = 25.0
    score += min(40.0, n_c * 20.0)
    score += min(35.0, n_a * 12.0)
    return round(min(100.0, score), 1)


def _compute_projects_percent(student: dict, job: dict) -> float:
    profile = student.get("profile") or {}
    projects = profile.get("projects") or []
    n = len(projects) if isinstance(projects, list) else 0
    if n >= 3:
        base = 100.0
    elif n == 2:
        base = 80.0
    elif n == 1:
        base = 55.0
    else:
        base = 20.0
    req = _get_job_required_skills(job)
    if n > 0 and req:
        blob = _profile_text_blob(student)
        hits = sum(1 for s in req if _normalize_skill_token(s) in blob or _compact_skill(s) in blob)
        boost = min(15.0, hits * 5.0)
        base = min(100.0, base + boost)
    return round(base, 1)


def _recommendation_label(score: float) -> Tuple[str, str]:
    if score >= 80:
        return "Strong Match", "🔥"
    if score >= 60:
        return "Good Match", "👍"
    if score >= 40:
        return "Moderate", "⚠️"
    return "Weak", "❌"


def calculate_placement_prediction(student: dict, job: dict) -> Dict[str, Any]:
    """
    Full prediction for one job.

    ``match_score`` is the weighted skill / important / extras / projects score (0–100)
    and is computed even when strict eligibility fails — used for suggestions.

    ``score`` is the final placement match shown on the predictor gauge: same as
    ``match_score`` when eligible, otherwise 0.
    """
    eligibility_ok, eligibility_reasons = _strict_eligibility(student, job)
    skills_list = _get_skills_list(student)

    skill_block = _compute_skill_match(job, skills_list)
    important_block = _compute_important_criteria(job, student)
    extras_pct = _compute_extras_percent(student)
    projects_pct = _compute_projects_percent(student, job)

    w_skill, w_imp, w_ex, w_pr = 0.6, 0.2, 0.1, 0.1
    skill_pct = float(skill_block["percent"])
    imp_pct = float(important_block["percent"])

    weighted = (
        w_skill * skill_pct
        + w_imp * imp_pct
        + w_ex * extras_pct
        + w_pr * projects_pct
    )
    match_score = round(min(100.0, max(0.0, weighted)), 1)

    if not eligibility_ok:
        final = 0.0
        status, emoji = "Not Eligible", "⛔"
    else:
        final = match_score
        status, emoji = _recommendation_label(final)

    return {
        "score": final,
        "match_score": match_score,
        "status": f"{emoji} {status}",
        "status_label": status,
        "status_emoji": emoji,
        "eligibility": {
            "pass": eligibility_ok,
            "reasons": eligibility_reasons,
        },
        "skill_match": skill_block,
        "important_criteria": important_block,
        "extras_percent": extras_pct,
        "projects_percent": projects_pct,
        "weights": {
            "skills": w_skill,
            "important_criteria": w_imp,
            "extras": w_ex,
            "projects": w_pr,
        },
        "breakdown": {
            "skills_contribution": round(w_skill * skill_pct, 2) if eligibility_ok else 0,
            "important_contribution": round(w_imp * imp_pct, 2) if eligibility_ok else 0,
            "extras_contribution": round(w_ex * extras_pct, 2) if eligibility_ok else 0,
            "projects_contribution": round(w_pr * projects_pct, 2) if eligibility_ok else 0,
            "skill_match_percent": skill_pct,
            "important_percent": imp_pct,
        },
        "engine_version": 2,
    }


def predict_placement(student: dict, job: Optional[dict] = None) -> Dict[str, Any]:
    """
    Entry point. Requires verified profile. Job required for per-job prediction.
    """
    verification_status = (student.get("verification_status") or "").strip().upper()
    if verification_status != VERIFICATION_VERIFIED:
        return {
            "error": "Your profile is not verified by faculty. Placement prediction will be available after verification."
        }

    if job is None:
        return {"error": "Please select a job to view placement prediction."}

    return calculate_placement_prediction(student, job)
