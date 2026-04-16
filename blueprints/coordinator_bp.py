"""
Coordinator blueprint: jobs, applications, policies, alumni approval.
"""
from flask import Blueprint

coordinator_bp = Blueprint("coordinator", __name__, url_prefix="/api/coordinator")


@coordinator_bp.route("/ping")
def ping():
    return {"ok": True, "role": "coordinator"}, 200
