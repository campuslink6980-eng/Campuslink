"""
Student blueprint: profile, applications, placement status.
Routes can be moved here from app.py over time.
"""
from flask import Blueprint

student_bp = Blueprint("student", __name__, url_prefix="/api/student")


@student_bp.route("/ping")
def ping():
    return {"ok": True, "role": "student"}, 200
