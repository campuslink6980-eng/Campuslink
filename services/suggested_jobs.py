"""
Personalized job suggestions: match_score >= threshold (skill-weighted, independent of apply gate).
apply_eligible reflects strict eligibility (CGPA, branch, batch year, open-to, etc.) — separate from score.
Uses placement_predictor.calculate_placement_prediction.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Optional, Tuple

from services.placement_predictor import calculate_placement_prediction

# user_id -> { sig_jobs, sig_profile, computed_at, items }
_SUGGESTED_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL_SEC = 120.0  # safety refresh even if signatures miss an edge case


def _active_jobs_signature(db) -> str:
    try:
        coll = db["job_posts"]
        ct = coll.count_documents({"status": "active"})
        latest = coll.find_one({"status": "active"}, sort=[("created_at", -1)], projection={"created_at": 1})
        ts = 0.0
        if latest and latest.get("created_at"):
            c = latest["created_at"]
            ts = c.timestamp() if hasattr(c, "timestamp") else 0.0
        ac = db["alumni_jobs"].count_documents({})
        alatest = db["alumni_jobs"].find_one({}, sort=[("created_at", -1)], projection={"created_at": 1})
        ats = 0.0
        if alatest and alatest.get("created_at"):
            c2 = alatest["created_at"]
            ats = c2.timestamp() if hasattr(c2, "timestamp") else 0.0
        return f"{ct}:{ts:.6f}|alumni:{ac}:{ats:.6f}"
    except Exception:
        return "0:0"


def _normalize_alumni_job_for_prediction(job: dict) -> dict:
    """Align alumni_jobs documents with fields placement_predictor expects."""
    j = dict(job)
    title = j.get("title") or j.get("role") or "Role"
    j["role"] = title
    j["type"] = j.get("job_type") or j.get("type")
    j["mode"] = j.get("work_mode") or j.get("mode")
    branches = list(j.get("branches_allowed") or j.get("department_allowed") or [])
    j["eligible_branches"] = branches
    j["eligibleBranches"] = branches
    j["branches_allowed"] = branches
    rs = j.get("required_skills")
    if isinstance(rs, list):
        j["requiredSkills"] = rs
    return j


def _profile_signature(student: dict, profile: dict) -> str:
    raw_skills = profile.get("skills") or student.get("skills") or []
    out: List[str] = []
    if isinstance(raw_skills, list):
        for x in raw_skills:
            if isinstance(x, str) and x.strip():
                out.append(x.strip().lower())
            elif isinstance(x, dict):
                nm = (x.get("name") or x.get("skill") or "").strip()
                if nm:
                    out.append(nm.lower())
    out.sort()
    open_to = profile.get("open_to") or []
    if not isinstance(open_to, list):
        open_to = []
    ot = sorted(str(x).strip().lower() for x in open_to if x)
    edu = (profile.get("education") or [])
    cgpa_key = ""
    grad_key = ""
    if edu and isinstance(edu, list) and len(edu) > 0 and isinstance(edu[0], dict):
        e0 = edu[0]
        cgpa_key = str(e0.get("cgpa") or "")
        grad_key = str(e0.get("graduation_year") or e0.get("year") or e0.get("passing_year") or "")
    if not grad_key:
        grad_key = str(student.get("graduation_year") or student.get("passout_year") or "")
    payload = {
        "verification": (student.get("verification_status") or "").strip().upper(),
        "branch": (student.get("branch_code") or student.get("branch") or "").strip().upper(),
        "grad_year": grad_key,
        "cgpa": cgpa_key or str(student.get("cgpa") or profile.get("cgpa") or ""),
        "cgpa_scale": str(student.get("cgpa_scale") or profile.get("cgpa_scale") or ""),
        "skills": out,
        "open_to": ot,
        "completion": str(student.get("profile_completion") or ""),
        "backlogs": str(student.get("activeBacklogs") if student.get("activeBacklogs") is not None else student.get("active_backlogs") or ""),
    }
    h = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return h[:40]


def _applications_signature(db, student: dict) -> str:
    """Invalidate suggested-jobs cache when this student applies or withdraws (coordinator or alumni jobs)."""
    sid = student.get("_id")
    if not sid:
        return "0"
    try:
        ids_c = sorted(
            str(d["job_id"])
            for d in db["applications"].find({"student_id": sid}, projection={"job_id": 1})
            if d.get("job_id")
        )
        ids_a = sorted(
            str(d["job_id"])
            for d in db["alumni_job_applications"].find({"student_id": sid}, projection={"job_id": 1})
            if d.get("job_id")
        )
        hc = hashlib.sha256(",".join(ids_c).encode()).hexdigest()[:16]
        ha = hashlib.sha256(",".join(ids_a).encode()).hexdigest()[:16]
        return f"{len(ids_c)}:{hc}|{len(ids_a)}:{ha}"
    except Exception:
        return "0"


def _match_tier(score: float) -> str:
    if score >= 80:
        return "strong"
    if score >= 60:
        return "good"
    return "moderate"


def _matched_skill_strings(skill_block: dict) -> List[str]:
    lines: List[str] = []
    for m in skill_block.get("matched") or []:
        if isinstance(m, dict) and m.get("skill"):
            lines.append(str(m["skill"]))
    for p in skill_block.get("partial") or []:
        if isinstance(p, dict) and p.get("skill"):
            via = p.get("via") or ""
            lines.append(f"{p['skill']} (related: {via})" if via else str(p["skill"]))
    return lines


def _build_why_hints(pred: dict, job: dict) -> List[str]:
    hints: List[str] = []
    sm = pred.get("skill_match") or {}
    for m in sm.get("matched") or []:
        if isinstance(m, dict) and m.get("skill"):
            hints.append(f"✔ Aligns with your {m['skill']} skill")
    for p in sm.get("partial") or []:
        if isinstance(p, dict) and p.get("skill"):
            hints.append(f"◐ {p['skill']} partially covered via {p.get('via') or 'related skill'}")
    for miss in (sm.get("missing") or [])[:4]:
        if isinstance(miss, str) and miss.strip():
            hints.append(f"⚠ Job asks for {miss.strip()} — consider adding it")
    min_c = job.get("min_cgpa")
    if min_c is not None and pred.get("eligibility", {}).get("pass"):
        hints.append("✔ You meet listed eligibility (CGPA / branch / preferences)")
    ic = pred.get("important_criteria") or {}
    if not ic.get("skipped") and ic.get("details"):
        for d in ic["details"]:
            if isinstance(d, dict):
                label = d.get("label") or d.get("tag") or ""
                if d.get("met"):
                    hints.append(f"✔ {label}")
                elif label:
                    hints.append(f"⚠ {label} — optional boost if you strengthen this area")
    return hints[:8]


def _friendly_apply_reasons(reasons: List[str]) -> List[str]:
    """Short labels for UI popups; keeps unknown messages as-is."""
    friendly: List[str] = []
    seen: set[str] = set()
    for raw in reasons:
        r = (raw or "").strip()
        if not r:
            continue
        low = r.lower()
        if "cgpa" in low and ("below" in low or "minimum" in low or "requirement" in low):
            label = "CGPA requirement not met"
        elif "branch" in low and "eligible" in low:
            label = "Branch not eligible"
        elif "graduation year" in low or ("year" in low and "eligible" in low and "graduation" in low):
            label = "Graduation year mismatch"
        elif "verified" in low:
            label = "Profile verification required"
        elif "open to" in low or "preferences" in low:
            label = "Job type not in your open-to preferences"
        elif "backlog" in low:
            label = "Active backlogs not allowed for this job"
        elif "important criteria" in low:
            label = "Important criteria not satisfied"
        else:
            label = r
        if label not in seen:
            seen.add(label)
            friendly.append(label)
    return friendly


def compute_suggested_jobs(
    db,
    student: dict,
    profile: dict,
    *,
    min_score: float = 50.0,
    limit: Optional[int] = None,
    max_scan: int = 500,
) -> List[Dict[str, Any]]:
    """
    Active coordinator jobs and alumni-posted jobs. Includes rows where match_score >= min_score (weighted match).
    apply_eligible is separate (strict eligibility for applying).
    Sorted by match_score descending. Returns all qualifying rows within max_scan unless limit is set.
    """
    student_f = dict(student)
    student_f["profile"] = profile

    sid = student.get("_id")
    applied_coordinator: set = set()
    applied_alumni: set = set()
    if sid:
        for d in db["applications"].find({"student_id": sid}, projection={"job_id": 1}):
            jid = d.get("job_id")
            if jid:
                applied_coordinator.add(jid)
        for d in db["alumni_job_applications"].find({"student_id": sid}, projection={"job_id": 1}):
            jid = d.get("job_id")
            if jid:
                applied_alumni.add(jid)

    coord_jobs = list(
        db["job_posts"]
        .find({"status": "active"})
        .sort("created_at", -1)
        .limit(max_scan)
    )
    alumni_jobs = list(
        db["alumni_jobs"]
        .find({})
        .sort("created_at", -1)
        .limit(max_scan)
    )
    rows: List[tuple[float, Dict[str, Any]]] = []

    for job in coord_jobs:
        pred = calculate_placement_prediction(student_f, job)
        ms = pred.get("match_score")
        if ms is None:
            ms = float(pred.get("score") or 0)
        else:
            ms = float(ms)
        if ms < min_score:
            continue
        elig = pred.get("eligibility") or {}
        eligibility_pass = bool(elig.get("pass"))
        raw_reasons = list(elig.get("reasons") or [])
        sm = pred.get("skill_match") or {}
        tier_score = ms
        status_lbl = pred.get("status_label") or ""
        if not eligibility_pass:
            status_lbl = "Not eligible to apply"
        jid = job.get("_id")
        already = jid in applied_coordinator if jid else False
        apply_eligible = eligibility_pass and not already
        item = {
            "job_id": str(job.get("_id")),
            "job_source": "coordinator",
            "title": job.get("title") or job.get("role") or "Role",
            "company": job.get("company_name") or "Company",
            "match_score": round(ms, 1),
            "final_score": round(ms, 1),
            "apply_eligible": apply_eligible,
            "already_applied": already,
            "apply_reasons": _friendly_apply_reasons(raw_reasons),
            "apply_reasons_detail": raw_reasons,
            "eligibility": eligibility_pass,
            "matched_skills": _matched_skill_strings(sm),
            "missing_skills": list(sm.get("missing") or []),
            "match_tier": _match_tier(tier_score),
            "tier_label": status_lbl,
            "why": _build_why_hints(pred, job),
        }
        rows.append((ms, item))

    for job in alumni_jobs:
        job_n = _normalize_alumni_job_for_prediction(job)
        pred = calculate_placement_prediction(student_f, job_n)
        ms = pred.get("match_score")
        if ms is None:
            ms = float(pred.get("score") or 0)
        else:
            ms = float(ms)
        if ms < min_score:
            continue
        elig = pred.get("eligibility") or {}
        eligibility_pass = bool(elig.get("pass"))
        raw_reasons = list(elig.get("reasons") or [])
        sm = pred.get("skill_match") or {}
        tier_score = ms
        status_lbl = pred.get("status_label") or ""
        if not eligibility_pass:
            status_lbl = "Not eligible to apply"
        jid = job.get("_id")
        already = jid in applied_alumni if jid else False
        apply_eligible = eligibility_pass and not already
        item = {
            "job_id": str(job.get("_id")),
            "job_source": "alumni",
            "title": job_n.get("title") or job_n.get("role") or "Role",
            "company": job_n.get("company_name") or job_n.get("company") or "Company",
            "match_score": round(ms, 1),
            "final_score": round(ms, 1),
            "apply_eligible": apply_eligible,
            "already_applied": already,
            "apply_reasons": _friendly_apply_reasons(raw_reasons),
            "apply_reasons_detail": raw_reasons,
            "eligibility": eligibility_pass,
            "matched_skills": _matched_skill_strings(sm),
            "missing_skills": list(sm.get("missing") or []),
            "match_tier": _match_tier(tier_score),
            "tier_label": status_lbl,
            "why": _build_why_hints(pred, job_n),
        }
        rows.append((ms, item))

    rows.sort(key=lambda x: -x[0])
    if limit is None or limit <= 0:
        return [r[1] for r in rows]
    return [r[1] for r in rows[:limit]]


def get_suggested_jobs_cached(
    db,
    student: dict,
    profile: dict,
    *,
    min_score: float = 50.0,
    limit: Optional[int] = None,
    max_scan: int = 500,
) -> Tuple[List[Dict[str, Any]], str, str]:
    """
    Returns (items, sig_jobs, sig_profile). Cache invalidates when jobs, profile, or
    this student's applications (coordinator or alumni) change.
    """
    uid = str(student.get("_id") or "")
    sig_jobs = _active_jobs_signature(db)
    sig_profile = _profile_signature(student, profile)
    sig_apps = _applications_signature(db, student)
    now = time.monotonic()

    ent = _SUGGESTED_CACHE.get(uid)
    if ent:
        stale = (now - float(ent.get("computed_at", 0))) > _CACHE_TTL_SEC
        if (
            not stale
            and ent.get("sig_jobs") == sig_jobs
            and ent.get("sig_profile") == sig_profile
            and ent.get("sig_apps") == sig_apps
            and ent.get("min_score") == min_score
            and ent.get("limit") == limit
            and ent.get("max_scan") == max_scan
        ):
            return list(ent.get("items") or []), sig_jobs, sig_profile

    items = compute_suggested_jobs(
        db, student, profile, min_score=min_score, limit=limit, max_scan=max_scan
    )
    _SUGGESTED_CACHE[uid] = {
        "sig_jobs": sig_jobs,
        "sig_profile": sig_profile,
        "sig_apps": sig_apps,
        "min_score": min_score,
        "limit": limit,
        "max_scan": max_scan,
        "items": items,
        "computed_at": now,
    }
    return items, sig_jobs, sig_profile


def invalidate_suggested_jobs_cache_for_user(user_id: Any) -> None:
    _SUGGESTED_CACHE.pop(str(user_id), None)


def invalidate_all_suggested_jobs_cache() -> None:
    _SUGGESTED_CACHE.clear()
