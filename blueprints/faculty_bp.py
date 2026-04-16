"""
Faculty blueprint: department students, verification.
API routes under /api/faculty are in app.py for now; this blueprint is for future migration.
"""
from flask import Blueprint

faculty_bp = Blueprint("faculty", __name__, url_prefix="/api/faculty")


@faculty_bp.route("/ping")
def ping():
    return {"ok": True, "role": "faculty"}, 200
