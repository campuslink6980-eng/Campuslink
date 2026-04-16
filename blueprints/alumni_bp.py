"""
Alumni blueprint: profile, mentorship, referrals, jobs.
"""
from flask import Blueprint

alumni_bp = Blueprint("alumni", __name__, url_prefix="/api/alumni")


@alumni_bp.route("/ping")
def ping():
    return {"ok": True, "role": "alumni"}, 200
