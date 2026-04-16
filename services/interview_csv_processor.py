"""
Interview CSV processor: validation, year/branch/role normalization.
Business logic only. No DB, no HTTP.
CSV structure: Name | Branch | Year | Email | Role (role optional)
"""
import csv
import io
import re
from typing import Any, Dict, List, Optional

REQUIRED_HEADERS = {"name", "branch", "year", "email"}
OPTIONAL_HEADERS = {"role"}
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

# Branch: lowercase key -> standard code
BRANCH_MAP = {
    "it": "IT",
    "information technology": "IT",
    "informationtechnology": "IT",
    "cst": "CST",
    "computer science": "CST",
    "computer science and technology": "CST",
    "cse": "CST",
    "computerscience": "CST",
    "ce": "CE",
    "civil": "CE",
    "civil engineering": "CE",
    "enc": "ENC",
    "electronics": "ENC",
    "electronics and communication": "ENC",
    "ece": "ENC",
    "ai": "AI",
    "artificial intelligence": "AI",
    "artificialintelligence": "AI",
    "ds": "DS",
    "data science": "DS",
    "datascience": "DS",
}

# Year: lowercase key -> 1,2,3,4
YEAR_MAP = {
    "1": 1, "first": 1, "1st": 1,
    "2": 2, "second": 2, "2nd": 2,
    "3": 3, "third": 3, "3rd": 3,
    "4": 4, "fourth": 4, "4th": 4, "final": 4, "finalyear": 4,
}


def _normalize_header(h: str) -> str:
    return (h or "").strip().lower()


def _normalize_value(v: Any) -> str:
    return (v or "").strip()


def _normalize_branch(value: str) -> tuple[Optional[str], bool]:
    """Return (standard_code or None, is_valid)."""
    v = _normalize_value(value).lower().replace(" ", "")
    if not v:
        return None, False
    code = BRANCH_MAP.get(v)
    return code, code is not None


def _normalize_year(value: str) -> tuple[Optional[int], bool]:
    """Return (1|2|3|4 or None, is_valid)."""
    v = _normalize_value(value).lower().replace(" ", "")
    if not v:
        return None, False
    if v in YEAR_MAP:
        return YEAR_MAP[v], True
    # try numeric
    m = re.match(r"^(\d)", v)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 4:
            return n, True
    return None, False


def process_csv(csv_content: bytes | str) -> Dict[str, Any]:
    """
    Parse and validate CSV. Required headers (case-insensitive): name, branch, year, email. Optional: role.
    - Trim spaces; headers converted to lowercase for validation.
    - Remove empty rows; remove duplicate emails (keep first).
    - Normalize branch to IT/CST/CE/ENC/AI/DS; normalize year to 1,2,3,4.
    Returns:
      ok: bool (False if required headers missing)
      header_error: str | None
      total_rows: int (before dedup/empty)
      duplicates_removed: int
      rows: list of { email, branch_code, year, role, branch_invalid, year_invalid }
    """
    if isinstance(csv_content, bytes):
        try:
            csv_content = csv_content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                csv_content = csv_content.decode("latin-1")
            except Exception:
                return {
                    "ok": False,
                    "header_error": "Could not decode CSV as UTF-8 or Latin-1",
                    "total_rows": 0,
                    "duplicates_removed": 0,
                    "rows": [],
                }
    if not csv_content or not isinstance(csv_content, str):
        return {
            "ok": False,
            "header_error": "Empty or invalid CSV content",
            "total_rows": 0,
            "duplicates_removed": 0,
            "rows": [],
        }

    try:
        reader = csv.DictReader(io.StringIO(csv_content))
        raw_headers = reader.fieldnames or []
        headers_lower = {_normalize_header(h): h for h in raw_headers if _normalize_header(h)}
        # Required headers must be present (case-insensitive)
        missing = REQUIRED_HEADERS - set(headers_lower.keys())
        if missing:
            return {
                "ok": False,
                "header_error": f"Missing required column(s): {', '.join(sorted(missing))}. Required: name, branch, year, email.",
                "total_rows": 0,
                "duplicates_removed": 0,
                "rows": [],
            }

        total_rows = 0
        seen_emails: set = set()
        duplicates_removed = 0
        rows: List[Dict[str, Any]] = []

        for row in reader:
            total_rows += 1
            # Trim all values
            row = {k: _normalize_value(v) for k, v in row.items() if k}
            # Empty row: all values empty
            if not any(row.values()):
                continue
            email_raw = row.get(headers_lower.get("email", "email")) or row.get("email", "")
            email = email_raw.lower().strip()
            if not email or not EMAIL_RE.match(email):
                continue
            if email in seen_emails:
                duplicates_removed += 1
                continue
            seen_emails.add(email)

            branch_raw = row.get(headers_lower.get("branch", "branch"), "")
            branch_code, branch_ok = _normalize_branch(branch_raw)
            year_raw = row.get(headers_lower.get("year", "year"), "")
            year_val, year_ok = _normalize_year(year_raw)
            role_raw = row.get(headers_lower.get("role", "role"), "") or None
            if role_raw is not None:
                role_raw = role_raw.strip() or None

            rows.append({
                "email": email,
                "branch_code": branch_code,
                "year": year_val,
                "role": role_raw,
                "branch_invalid": not branch_ok and bool(_normalize_value(branch_raw)),
                "year_invalid": not year_ok and bool(_normalize_value(year_raw)),
            })
    except Exception as e:
        return {
            "ok": False,
            "header_error": f"CSV parse error: {e!s}",
            "total_rows": 0,
            "duplicates_removed": 0,
            "rows": [],
        }

    return {
        "ok": True,
        "header_error": None,
        "total_rows": total_rows,
        "duplicates_removed": duplicates_removed,
        "rows": rows,
    }
