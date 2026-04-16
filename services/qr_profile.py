"""
QR-based public profile: slug generation and QR code creation.
Only for STUDENT and ALUMNI. No DB writes here; callers persist.
"""
import os
import re
from typing import Optional

try:
    import qrcode
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False


def _slugify(text: str) -> str:
    """Lowercase, replace spaces/special with hyphens, collapse multiple hyphens."""
    if not text or not isinstance(text, str):
        return ""
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return text[:80]  # cap length


def generate_public_slug(name: str, branch_or_company: Optional[str] = None) -> str:
    """
    Build SEO-friendly slug from name and optional branch/company.
    Example: "Surabhi Shirsat" + "IT" -> "surabhi-shirsat-it"
    """
    parts = [_slugify(name)]
    if branch_or_company and str(branch_or_company).strip():
        parts.append(_slugify(str(branch_or_company).strip()))
    slug = "-".join(p for p in parts if p)
    return slug or "profile"


def ensure_unique_slug(users_collection, base_slug: str, exclude_user_id=None) -> str:
    """
    Return base_slug if unique; otherwise append -2, -3, ... until unique.
    exclude_user_id: ObjectId to ignore when checking (for updates).
    """
    slug = base_slug
    count = 2
    while True:
        q = {"public_slug": slug}
        if exclude_user_id is not None:
            q["_id"] = {"$ne": exclude_user_id}
        if not users_collection.find_one(q):
            return slug
        slug = f"{base_slug}-{count}"
        count += 1


def generate_qr_for_user(
    user_id,
    public_slug: str,
    base_url: str,
    static_folder: str,
) -> Optional[str]:
    """
    Generate QR image for profile URL and save to static/qr/{user_id}.png.
    Returns relative path like "static/qr/507f1f77bcf86cd799439011.png" or None if failed.
    Only call for STUDENT/ALUMNI; caller must check role.
    """
    if not QR_AVAILABLE or not public_slug or not base_url:
        return None
    base_url = base_url.rstrip("/")
    profile_url = f"{base_url}/profile/{public_slug}"
    try:
        qr = qrcode.make(profile_url)
        qr_dir = os.path.join(static_folder, "qr")
        os.makedirs(qr_dir, exist_ok=True)
        file_name = f"{user_id}.png"
        file_path = os.path.join(qr_dir, file_name)
        qr.save(file_path)
        return f"static/qr/{file_name}"
    except Exception:
        return None
