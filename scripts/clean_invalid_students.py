"""
One-time (or periodic) cleanup: mark or remove student users that do not match the master `student` list.

Usage (from project root, with venv activated):
  python scripts/clean_invalid_students.py

Environment:
  MONGO_URI   — required (same as the app)
  CLEAN_STUDENT_ACTION — optional: "flag" (default) sets is_valid_student=False, "delete" removes users.

Does not modify non-student users.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402
from pymongo import MongoClient  # noqa: E402

from models import ROLE_STUDENT  # noqa: E402
from services.student_master import existing_student_user_matches_master  # noqa: E402


def main() -> None:
    load_dotenv()
    mongo_uri = (os.getenv("MONGO_URI") or "").strip()
    if not mongo_uri:
        print("Set MONGO_URI in .env")
        sys.exit(1)
    action = (os.getenv("CLEAN_STUDENT_ACTION") or "flag").strip().lower()
    if action not in ("flag", "delete"):
        print('CLEAN_STUDENT_ACTION must be "flag" or "delete"')
        sys.exit(1)

    db = MongoClient(mongo_uri).get_default_database()
    q = {"$or": [{"user_type": "student"}, {"role": ROLE_STUDENT}]}
    cursor = db["users"].find(q)
    n_checked = 0
    n_invalid = 0
    for user in cursor:
        n_checked += 1
        if existing_student_user_matches_master(db, user):
            continue
        n_invalid += 1
        uid = user["_id"]
        email = user.get("email", "")
        if action == "delete":
            db["users"].delete_one({"_id": uid})
            print(f"deleted: {email} ({uid})")
        else:
            db["users"].update_one(
                {"_id": uid},
                {"$set": {"is_valid_student": False}},
            )
            print(f"flagged invalid: {email} ({uid})")

    print(f"Done. Checked {n_checked} student users; {n_invalid} did not match master list ({action}).")


if __name__ == "__main__":
    main()
