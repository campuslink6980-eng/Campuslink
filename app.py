from datetime import datetime, timedelta
import io
import os
from dotenv import load_dotenv
load_dotenv()
import csv
import secrets
import smtplib
import re
import json
from email.message import EmailMessage
from flask import Flask, request, redirect, url_for, session, flash, send_from_directory, jsonify, abort, Response
from markupsafe import escape as html_escape
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
from functools import wraps
import uuid
from bson import ObjectId
from models import (
    ROLE_STUDENT,
    ROLE_FACULTY,
    ROLE_COORDINATOR,
    ROLE_ADMIN,
    ROLE_ALUMNI,
    VERIFICATION_PENDING,
    VERIFICATION_VERIFIED,
    VERIFICATION_REJECTED,
    VERIFICATION_NEEDS_CORRECTION,
    PLACEMENT_STATUS_NOT_PLACED,
    PLACEMENT_STATUS_PLACED,
    APPLICATION_STATUS_SELECTED,
    DEPARTMENTS,
    derive_role_from_existing_user_type,
    normalize_branch_code,
)
from services.student_master import (
    normalize_roll,
    validate_student_registration_against_master,
)
from services.placement_policy import get_active_policy, ensure_default_policy
from services.eligibility import (
    APPLICATION_DEADLINE_PASSED_MSG,
    application_deadline_end_utc_iso,
    check_placement_eligibility,
    compute_missing_required_skills_suggestions,
    is_application_deadline_passed,
)
from services.placement_predictor import predict_placement
from services.skill_gap import analyze_skill_gap
from services.course_recommender import recommend_courses_grouped_by_skill
from services.interview_experience import generate_invite_token
from services.interview_csv_processor import process_csv
from services.qr_profile import (
    generate_public_slug,
    ensure_unique_slug,
    generate_qr_for_user as qr_profile_generate_qr,
)
from services.resume_generator import build_resume_html, build_resume_pdf, safe_resume_filename
from services.banned_users import (
    ACCOUNT_BANNED_AUTH_MESSAGE,
    ensure_banned_users_indexes,
    is_email_banned,
    record_ban,
    user_is_banned,
    user_hidden_from_campuslink_discovery,
)
try:
    import cloudinary
    import cloudinary.uploader
except Exception:
    cloudinary = None

app = Flask(__name__)
app.secret_key = "campuslink_secret_key"  # change in production

from blueprints.student_bp import student_bp
from blueprints.faculty_bp import faculty_bp
from blueprints.coordinator_bp import coordinator_bp
from blueprints.alumni_bp import alumni_bp
app.register_blueprint(student_bp)
app.register_blueprint(faculty_bp)
app.register_blueprint(coordinator_bp)
app.register_blueprint(alumni_bp)

# JWT configuration (used by coordinator dashboard + future clients)
JWT_SECRET = os.getenv("JWT_SECRET", app.secret_key)
JWT_ALG = "HS256"
JWT_EXPIRES_HOURS = int(os.getenv("JWT_EXPIRES_HOURS", "12"))

# MongoDB connection
# Security/default-safety: never fall back to localhost or hardcoded URIs.
mongo_uri = (os.getenv("MONGO_URI") or "").strip()
if not mongo_uri:
    raise RuntimeError(
        "MongoDB connection string is not configured. "
        "Set MONGO_URI in your .env file before starting the app."
    )
client = MongoClient(mongo_uri)
db = client["campuslink"]

# One-time: student profile verification is faculty-only; reset previously verified students.
MIGRATION_STUDENT_VERIFICATION_FACULTY_ONLY_V1 = "student_verification_faculty_only_reset_v1"
MIGRATION_MEDIA_REFERENCE_CLEANUP_V1 = "media_reference_cleanup_v1"


def _run_student_verification_faculty_only_migration():
    migrations = db["app_migrations"]
    if migrations.find_one({"_id": MIGRATION_STUDENT_VERIFICATION_FACULTY_ONLY_V1}):
        return
    result = db["users"].update_many(
        {
            "user_type": "student",
            "$or": [
                {"verification_status": VERIFICATION_VERIFIED},
                {"is_verified": True},
            ],
        },
        {
            "$set": {
                "verification_status": VERIFICATION_PENDING,
                "is_verified": False,
                "verification_updated_at": datetime.utcnow(),
            },
            "$unset": {"verification_by": "", "verification_remark": ""},
        },
    )
    try:
        migrations.insert_one(
            {
                "_id": MIGRATION_STUDENT_VERIFICATION_FACULTY_ONLY_V1,
                "applied_at": datetime.utcnow(),
                "matched_count": result.matched_count,
                "modified_count": result.modified_count,
            }
        )
    except DuplicateKeyError:
        pass


_run_student_verification_faculty_only_migration()


def _run_media_reference_cleanup_migration():
    migrations = db["app_migrations"]
    if migrations.find_one({"_id": MIGRATION_MEDIA_REFERENCE_CLEANUP_V1}):
        return
    db["users"].update_many(
        {},
        {"$unset": {
            "profile.profile_photo": "",
            "profile.cover_photo": "",
            "profile.certificate_urls": "",
            "profile.project_media": "",
            "profile.post_media": "",
            "profile.resume": "",
            "profile.resume_pdf_url": "",
            "profile.resume_pdf_generated_at": "",
            "profile.video": "",
            "profile.profile_image": "",
        }},
    )
    db["users"].update_many(
        {},
        {"$unset": {"cloudinary_id": "", "cloudinary_public_id": "", "profile_image": "", "resume": "", "video": ""}},
    )
    db["posts"].update_many(
        {},
        {"$unset": {"media_url": "", "media_urls": "", "media": "", "post_media": "", "cloudinary_id": "", "cloudinary_public_id": ""}},
    )
    db["job_posts"].update_many(
        {},
        {"$unset": {"attachment": "", "attachments": "", "cloudinary_id": "", "cloudinary_public_id": ""}},
    )
    try:
        migrations.insert_one(
            {
                "_id": MIGRATION_MEDIA_REFERENCE_CLEANUP_V1,
                "applied_at": datetime.utcnow(),
            }
        )
    except DuplicateKeyError:
        pass


_run_media_reference_cleanup_migration()

# Profile media: allowed types and size limits (abuse prevention)
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}
ALLOWED_VIDEO_EXTENSIONS = {"mp4"}
ALLOWED_DOC_EXTENSIONS = {"pdf", "doc", "docx"}
ANNOUNCEMENT_MEDIA_MAX_FILES = 15
ANNOUNCEMENT_AUDIENCE_ALLOWED = frozenset({"student", "faculty", "alumni"})
MAX_IMAGE_SIZE = 5 * 1024 * 1024   # 5 MB
MAX_VIDEO_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_DOC_SIZE = 10 * 1024 * 1024    # 10 MB

CLOUDINARY_CLOUD_NAME = (os.getenv("CLOUDINARY_CLOUD_NAME") or "").strip()
CLOUDINARY_API_KEY = (os.getenv("CLOUDINARY_API_KEY") or "").strip()
CLOUDINARY_API_SECRET = (os.getenv("CLOUDINARY_API_SECRET") or "").strip()
CLOUDINARY_SECURE = (os.getenv("CLOUDINARY_SECURE") or "true").strip().lower() != "false"
CLOUDINARY_AVAILABLE = bool(
    cloudinary and CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET
)
if CLOUDINARY_AVAILABLE:
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET,
        secure=CLOUDINARY_SECURE,
    )

USER_MEDIA_SUBFOLDERS = {
    "profile_photo",
    "cover_photo",
    "certificates",
    "achievements",
    "internships",
    "projects",
    "posts",
    "notes",
    "other",
}


def _sanitize_folder_segment(value: str, fallback: str = "unknown") -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip()).strip("_")
    return s or fallback


def _extract_file_ext(filename: str) -> str:
    if "." not in (filename or ""):
        return ""
    return filename.rsplit(".", 1)[-1].strip().lower()


def generate_user_folder(user: dict) -> str:
    first = _sanitize_folder_segment(user.get("first_name"), "User")
    last = _sanitize_folder_segment(user.get("last_name"), "Unknown")
    roll = (
        user.get("roll_number")
        or user.get("roll")
        or user.get("student_id")
        or user.get("enrollment_no")
        or str(user.get("_id") or "")
    )
    roll_s = _sanitize_folder_segment(roll, "NA")
    return f"{first}_{last}_{roll_s}"


def _cloudinary_user_folder_path(user: dict, media_type: str) -> str:
    if media_type not in USER_MEDIA_SUBFOLDERS:
        raise ValueError("Invalid user media type.")
    return f"campus/users/{generate_user_folder(user)}/{media_type}"


def upload_to_cloudinary(file, folder_path: str, *, resource_type: str = "auto", public_id_prefix: str | None = None):
    if not CLOUDINARY_AVAILABLE:
        return None, "Cloudinary is not configured."
    if not file or not getattr(file, "filename", None):
        return None, "No file selected."
    folder = (folder_path or "").strip().strip("/")
    if not folder:
        return None, "Cloudinary folder path is required."
    try:
        file.stream.seek(0, os.SEEK_END)
        size = file.stream.tell()
        file.stream.seek(0)
    except Exception:
        size = None
    options = {"folder": folder, "resource_type": resource_type}
    if public_id_prefix:
        options["public_id"] = f"{_sanitize_folder_segment(public_id_prefix)}_{uuid.uuid4().hex[:8]}"
        options["unique_filename"] = False
        options["overwrite"] = False
    try:
        result = cloudinary.uploader.upload(file, **options)
        return {
            "url": result.get("secure_url") or result.get("url"),
            "secure_url": result.get("secure_url") or result.get("url"),
            "public_id": result.get("public_id"),
            "resource_type": result.get("resource_type"),
            "format": result.get("format"),
            "bytes": result.get("bytes") if result.get("bytes") is not None else size,
            "folder": folder,
            "original_filename": file.filename,
        }, None
    except Exception as e:
        return None, f"Upload failed: {e}"


def _max_size_for_ext(ext: str) -> int:
    ext = (ext or "").lower().strip()
    if ext in ALLOWED_VIDEO_EXTENSIONS:
        return MAX_VIDEO_SIZE
    if ext in ALLOWED_DOC_EXTENSIONS:
        return MAX_DOC_SIZE
    return MAX_IMAGE_SIZE


def _upload_user_media(file_storage, user: dict, media_folder: str, *, allow_images=True, allow_videos=False, allow_docs=False, public_id_prefix: str | None = None):
    """
    Upload file to Cloudinary under the user's folder.
    Returns (secure_url, media_kind, error_message).
    media_kind is one of: image, video, document.
    """
    if not file_storage or not getattr(file_storage, "filename", None):
        return None, None, "Media file is required."
    ext = _extract_file_ext(file_storage.filename)

    if allow_images and ext in ALLOWED_IMAGE_EXTENSIONS:
        resource_type = "image"
        media_kind = "image"
    elif allow_videos and ext in ALLOWED_VIDEO_EXTENSIONS:
        resource_type = "video"
        media_kind = "video"
    elif allow_docs and ext in ALLOWED_DOC_EXTENSIONS:
        resource_type = "raw"
        media_kind = "document"
    else:
        allowed = []
        if allow_images:
            allowed += ["JPG", "JPEG", "PNG"]
        if allow_videos:
            allowed += ["MP4"]
        if allow_docs:
            allowed += ["PDF", "DOC", "DOCX"]
        return None, None, "Only " + "/".join(allowed) + " are allowed."

    max_size = _max_size_for_ext(ext)
    try:
        file_storage.stream.seek(0, os.SEEK_END)
        size = file_storage.stream.tell()
        file_storage.stream.seek(0)
    except Exception:
        size = None
    if size and size > max_size:
        return None, None, "File exceeds allowed size."

    uploaded, upload_err = upload_to_cloudinary(
        file_storage,
        _cloudinary_user_folder_path(user, media_folder),
        resource_type=resource_type,
        public_id_prefix=public_id_prefix,
    )
    if upload_err:
        return None, None, upload_err
    return uploaded.get("secure_url"), media_kind, None

# ---------- Activity Types ----------
ACTIVITY_TYPE_POST = "post"
ACTIVITY_TYPE_COMMENT = "comment"
ACTIVITY_TYPE_REACTION = "reaction"
ACTIVITY_TYPE_APPLICATION = "application"

# ---------- Connection Status ----------
CONNECTION_PENDING = "PENDING"
CONNECTION_ACCEPTED = "ACCEPTED"
CONNECTION_REJECTED = "REJECTED"



# ---------- Profile Photo URL Helper ----------
def _profile_photo_url(profile_photo):
    if isinstance(profile_photo, str):
        return profile_photo.strip() or None
    if isinstance(profile_photo, dict):
        return (
            profile_photo.get("secure_url")
            or profile_photo.get("url")
            or profile_photo.get("media_url")
        )
    return None


MEDIA_PROFILE_FIELDS = {
    "profile_photo",
    "cover_photo",
    "certificate_urls",
    "project_media",
    "post_media",
}


def _strip_media_references_from_profile(profile: dict) -> dict:
    return dict(profile or {})


# ---------- DateTime Helper ----------
def to_utc_iso(dt):
    """
    Convert datetime to ISO format with UTC timezone indicator.
    Returns string like '2025-01-28T10:30:00Z' or None if dt is None.
    """
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return None


# ---------- Safe schema migration (MongoDB) ----------
def migrate_users_schema():
    """
    MongoDB has no ALTER TABLE; we safely backfill missing fields.
    This is non-breaking: it ONLY sets defaults when fields are absent/null.
    """
    users = db["users"]

    # role: default STUDENT (or derived from existing user_type if present)
    users.update_many(
        {"$or": [{"role": {"$exists": False}}, {"role": None}, {"role": ""}]},
        [{"$set": {"role": {"$toUpper": {"$ifNull": ["$role", ""]}}}}],
    )
    users.update_many(
        {"$or": [{"role": {"$exists": False}}, {"role": None}, {"role": ""}]},
        {"$set": {"role": ROLE_STUDENT}},
    )

    # If user_type indicates coordinator/admin, set role accordingly.
    # IMPORTANT: older docs may already have role="STUDENT" even when user_type="coordinator".
    users.update_many(
        {"user_type": "coordinator", "$or": [{"role": {"$exists": False}}, {"role": None}, {"role": ""}, {"role": ROLE_STUDENT}]},
        {"$set": {"role": ROLE_COORDINATOR}},
    )
    users.update_many(
        {"user_type": "admin", "$or": [{"role": {"$exists": False}}, {"role": None}, {"role": ""}, {"role": ROLE_STUDENT}]},
        {"$set": {"role": ROLE_ADMIN}},
    )
    users.update_many(
        {"user_type": "alumni", "$or": [{"role": {"$exists": False}}, {"role": None}, {"role": ""}, {"role": ROLE_STUDENT}]},
        {"$set": {"role": ROLE_ALUMNI}},
    )

    # branch_code: default inferred from existing 'branch' if available; otherwise null
    users.update_many(
        {"branch_code": {"$exists": False}},
        [{"$set": {"branch_code": {"$toUpper": {"$ifNull": ["$branch", None]}}}}],
    )

    # verification_status: default PENDING
    users.update_many(
        {"$or": [{"verification_status": {"$exists": False}}, {"verification_status": None}, {"verification_status": ""}]},
        {"$set": {"verification_status": VERIFICATION_PENDING}},
    )

    # profile_completion: default 0
    users.update_many(
        {"$or": [{"profile_completion": {"$exists": False}}, {"profile_completion": None}]},
        {"$set": {"profile_completion": 0}},
    )
    users.update_many(
        {"$or": [{"placement_status": {"$exists": False}}, {"placement_status": None}]},
        {"$set": {"placement_status": PLACEMENT_STATUS_NOT_PLACED}},
    )
    users.update_many(
        {"user_type": "faculty", "$or": [{"role": {"$exists": False}}, {"role": None}, {"role": ""}, {"role": ROLE_STUDENT}]},
        {"$set": {"role": ROLE_FACULTY}},
    )
    # Mentoring: students get mentor_id (nullable), alumni get mentees array
    users.update_many(
        {"user_type": "student", "mentor_id": {"$exists": False}},
        {"$set": {"mentor_id": None}},
    )
    users.update_many(
        {"user_type": "alumni", "mentees": {"$exists": False}},
        {"$set": {"mentees": []}},
    )


def ensure_mentoring_indexes():
    """Create indexes on mentoring_requests for student_id, alumni_id, status."""
    coll = db["mentoring_requests"]
    coll.create_index("student_id")
    coll.create_index("alumni_id")
    coll.create_index("status")
    coll.create_index([("alumni_id", 1), ("status", 1)])
    coll.create_index([("student_id", 1), ("alumni_id", 1)])


def ensure_support_ticket_indexes():
    coll = db["support_tickets"]
    coll.create_index("user_id")
    coll.create_index("status")
    coll.create_index("priority")
    coll.create_index("role")
    coll.create_index([("created_at", -1)])
    coll.create_index([("updated_at", -1)])


def seed_departments():
    """Ensure departments collection has the 6 placement departments."""
    coll = db["departments"]
    for name in DEPARTMENTS:
        if coll.count_documents({"name": name}) == 0:
            coll.insert_one({"name": name, "created_at": datetime.utcnow()})


def _safe_startup_db_init():
    """
    Best-effort startup initialization.
    If MongoDB is temporarily unreachable (network/TLS/DNS),
    don't crash the Flask process at import time.
    """
    try:
        migrate_users_schema()
        seed_departments()
        ensure_default_policy(db)
        ensure_mentoring_indexes()
        ensure_support_ticket_indexes()
        ensure_banned_users_indexes(db)
    except Exception as e:
        print(f"[startup] MongoDB initialization skipped: {e}")


_safe_startup_db_init()


# ---------- Auth helpers & decorators ----------
def is_flagged_invalid_student(user):
  """
  True when a student was marked not matching the master list (cleanup / validation).
  Missing is_valid_student means valid for backward compatibility.
  """
  if not user or user.get("is_valid_student") is not False:
      return False
  ut = (user.get("user_type") or "").strip().lower()
  return ut == "student"


def get_logged_in_user():
  """
  Return the current logged-in user document (from session["email"]),
  or None if no user session is active.
  """
  email = session.get("email")
  if not email:
      return None
  user = db["users"].find_one({"email": email})
  if user and user_is_banned(user):
      session.clear()
      return None
  if user and is_flagged_invalid_student(user):
      session.clear()
      return None
  return user


def get_user_roles(email: str) -> list:
  """
  Get all roles for a user by checking both users and admins collections.
  Returns a list of role strings: ['admin', 'student', 'coordinator']
  """
  roles = []
  email_lower = email.strip().lower() if email else ""
  if not email_lower:
      return roles
  
  # Check if user exists in users collection
  user = db["users"].find_one({"email": email_lower})
  if user:
      user_type = (user.get("user_type") or "").strip().lower()
      role = (user.get("role") or "").strip().upper()
      if user_type == "student" or (role == "STUDENT" and user_type not in ("alumni", "faculty")):
          roles.append("student")
      if user_type == "faculty" or role == "FACULTY":
          roles.append("faculty")
      if user_type == "alumni" or role == "ALUMNI":
          roles.append("alumni")
      if user_type == "coordinator" or role == "COORDINATOR":
          roles.append("coordinator")
      if user_type == "admin" or role == "ADMIN":
          roles.append("admin")
  
  # Check if user exists in admins collection
  admin = db["admins"].find_one({"email": email_lower})
  if admin:
      if "admin" not in roles:
          roles.append("admin")
  
  # Remove duplicates and return
  return list(set(roles))


def login_required(view):
  """
  Ensure a regular user is logged in (session-based).
  Does NOT affect admin session (/admin/login) logic.
  """
  @wraps(view)
  def wrapped(*args, **kwargs):
      user = get_logged_in_user()
      if not user:
          flash("Please sign in to continue.", "warning")
          return redirect(url_for("login_page"))
      return view(*args, **kwargs)
  return wrapped


def role_required(*roles):
  """
  Enforce application role(s) on top of login_required.
  Usage: @role_required("STUDENT"), @role_required("COORDINATOR"), etc.
  """
  allowed = {r.upper() for r in roles}

  def decorator(view):
      @wraps(view)
      def wrapped(*args, **kwargs):
          user = get_logged_in_user()
          if not user:
              flash("Please sign in to continue.", "warning")
              return redirect(url_for("login_page"))
          user_role = (user.get("role") or "").upper() or derive_role_from_existing_user_type(
              user.get("user_type")
          )
          if user_role not in allowed:
              flash("You are not authorized to access that page.", "danger")
              if user_role == ROLE_STUDENT:
                  return redirect(url_for("user_dashboard"))
              if user_role == ROLE_FACULTY:
                  return redirect(url_for("faculty_dashboard"))
              return redirect(url_for("main"))
          return view(*args, **kwargs)
      return wrapped
  return decorator


def faculty_required(view):
  """Require faculty role and department-level access. Faculty can only see their department."""
  @wraps(view)
  def wrapped(*args, **kwargs):
      user = get_logged_in_user()
      if not user:
          flash("Please sign in to continue.", "warning")
          return redirect(url_for("login_page"))
      role = (user.get("role") or "").upper()
      ut = (user.get("user_type") or "").strip().lower()
      if role != ROLE_FACULTY and ut != "faculty":
          flash("Faculty access only.", "danger")
          return redirect(url_for("main"))
      return view(*args, **kwargs)
  return wrapped


# ---------- Password reset helpers ----------
def is_strong_password(password: str) -> tuple[bool, str]:
  """
  Validate password strength.
  Rules:
  - At least 8 characters
  - At least 1 uppercase, 1 lowercase, 1 digit, 1 special character
  """
  if not password or len(password) < 8:
      return False, "Password must be at least 8 characters long."
  if not re.search(r"[A-Z]", password):
      return False, "Password must contain at least one uppercase letter."
  if not re.search(r"[a-z]", password):
      return False, "Password must contain at least one lowercase letter."
  if not re.search(r"\d", password):
      return False, "Password must contain at least one number."
  if not re.search(r"[^\w\s]", password):
      return False, "Password must contain at least one special character."
  return True, ""


def _find_user_by_reset_token(raw_token: str):
  """
  Find a user document by validating the provided raw reset token
  against hashed tokens stored in the users collection, ensuring
  the token is not expired.
  """
  if not raw_token:
      return None
  now = datetime.utcnow()
  users_coll = db["users"]
  candidates = users_coll.find(
      {
          "reset_token": {"$exists": True, "$ne": None},
          "reset_token_expiry": {"$gt": now},
      }
  )
  for doc in candidates:
      try:
          if doc.get("reset_token") and check_password_hash(doc["reset_token"], raw_token):
              return doc
      except Exception:
          continue
  return None


def _find_user_by_setup_token(raw_token: str):
  """Find alumni user by password_setup_token (hashed) and valid expiry."""
  if not raw_token:
      return None
  now = datetime.utcnow()
  users_coll = db["users"]
  candidates = users_coll.find(
      {
          "user_type": "alumni",
          "password_setup_token": {"$exists": True, "$ne": None},
          "password_setup_token_expiry": {"$gt": now},
      }
  )
  for doc in candidates:
      try:
          if doc.get("password_setup_token") and check_password_hash(doc["password_setup_token"], raw_token):
              return doc
      except Exception:
          continue
  return None


def send_reset_email(to_email: str, reset_link: str) -> bool:
  """
  Send a password reset email using Gmail SMTP (TLS).

  Credentials are read from environment variables:
    EMAIL_USER, EMAIL_PASS

  Returns True on success, False on failure.
  """
  if not to_email or not reset_link:
      return False

  smtp_host = "smtp.gmail.com"
  smtp_port = 587
  smtp_user = os.environ.get("EMAIL_USER")
  smtp_password = os.environ.get("EMAIL_PASS")

  if not smtp_user or not smtp_password:
      # SMTP not configured; log and return without raising.
      try:
          app.logger.warning("EMAIL_USER/EMAIL_PASS not configured; skipping password reset email.")
      except Exception:
          pass
      return False

  msg = EmailMessage()
  msg["Subject"] = "CampusLink Password Reset"
  msg["From"] = smtp_user
  msg["To"] = to_email
  msg.set_content(
      f"""Hello,

You requested a password reset for your CampusLink account.

Click the link below to reset your password:
{reset_link}

This link will expire in 15 minutes.

If you did not request this, you can safely ignore this email.

Team CampusLink
"""
  )

  try:
      with smtplib.SMTP(smtp_host, smtp_port) as server:
          server.starttls()
          server.login(smtp_user, smtp_password)
          server.send_message(msg)
      return True
  except Exception as e:
      # Log but do not expose details to the client.
      try:
          app.logger.error(f"Failed to send password reset email: {e}")
      except Exception:
          pass
      return False


def send_password_reset_email(email: str, raw_token: str) -> bool:
  """
  Backwards-compatible helper: build reset link and delegate to send_reset_email.
  """
  if not email or not raw_token:
      return False

  reset_url = url_for("reset_password", token=raw_token, _external=True)
  return send_reset_email(email, reset_url)


def send_alumni_setup_email(to_email: str, setup_link: str) -> bool:
  """Send email to approved alumni with link to set password."""
  if not to_email or not setup_link:
      return False
  smtp_user = os.environ.get("EMAIL_USER")
  smtp_password = os.environ.get("EMAIL_PASS")
  if not smtp_user or not smtp_password:
      try:
          app.logger.warning("EMAIL_USER/EMAIL_PASS not configured; skipping alumni setup email.")
      except Exception:
          pass
      return False
  msg = EmailMessage()
  msg["Subject"] = "CampusLink – Your alumni request has been approved"
  msg["From"] = smtp_user
  msg["To"] = to_email
  msg.set_content(
      f"""Hello,

Your alumni request has been approved.

Click here to create your password:
{setup_link}

This link will expire in 1 hour.

Team CampusLink
"""
  )
  try:
      with smtplib.SMTP("smtp.gmail.com", 587) as server:
          server.starttls()
          server.login(smtp_user, smtp_password)
          server.send_message(msg)
      return True
  except Exception as e:
      try:
          app.logger.error(f"Failed to send alumni setup email: {e}")
      except Exception:
          pass
      return False


def send_interview_invite_email(to_email: str, submit_link: str, company: str, role: str) -> bool:
  """Send email to invited student with link to submit interview experience."""
  if not to_email or not submit_link:
      return False
  smtp_user = os.environ.get("EMAIL_USER")
  smtp_password = os.environ.get("EMAIL_PASS")
  if not smtp_user or not smtp_password:
      try:
          app.logger.warning("EMAIL_USER/EMAIL_PASS not configured; skipping interview invite email.")
      except Exception:
          pass
      return False
  msg = EmailMessage()
  msg["Subject"] = f"CampusLink – Submit your interview experience ({company or 'Company'})"
  msg["From"] = smtp_user
  msg["To"] = to_email
  msg.set_content(
      f"""Hello,

You have been invited to share your interview experience for the role of {role or 'the position'} at {company or 'the company'}.

Click the link below to submit your experience (one-time submission):
{submit_link}

Thank you,
Team CampusLink
"""
  )
  try:
      with smtplib.SMTP("smtp.gmail.com", 587) as server:
          server.starttls()
          server.login(smtp_user, smtp_password)
          server.send_message(msg)
      return True
  except Exception as e:
      try:
          app.logger.error(f"Failed to send interview invite email: {e}")
      except Exception:
          pass
      return False


# ---------- Profile section reverse-chronological sorting ----------
_MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def _parse_date_for_sort(val, default_ym=(0, 0)):
    """
    Parse a date value for sorting. Supports:
    - YYYY-MM-DD, YYYY-MM
    - Year only (int/str)
    - DD-Month-YYYY (e.g. 03-April-2025)
    - DD Mon YYYY (e.g. 23 Nov 2024, 8 Jan 2025)
    - Month YYYY (e.g. March 2025, January 2026)
    Returns (year, month) with (0, 0) for missing/invalid so items sort last.
    """
    if val is None or (isinstance(val, str) and not val.strip()):
        return default_ym
    if isinstance(val, (int, float)):
        y = int(val)
        return (y, 12) if y > 0 else default_ym
    s = str(val).strip()
    if not s or s.lower() in ("present", "current", "now", ""):
        return default_ym

    # Find 4-digit year anywhere in string
    year_match = re.search(r"\b(19|20)\d{2}\b", s)
    year = int(year_match.group(0)) if year_match else 0
    if not year:
        try:
            y = int(s)
            return (y, 12) if y > 0 else default_ym
        except (ValueError, TypeError):
            return default_ym

    # Prefer month name (so "03-April-2025" gives April=4, not 03)
    month = 12
    for name, num in sorted(_MONTH_NAMES.items(), key=lambda x: -len(x[0])):
        if re.search(r"\b" + re.escape(name) + r"\b", s, re.I):
            month = num
            break
    else:
        # YYYY-MM or standalone 1-12 month (avoid DD in DD-Month-YYYY)
        mm = re.search(r"\b(0?[1-9]|1[0-2])\b", s)
        if mm:
            # Prefer part that looks like month after year (e.g. in "2024-11" or "Nov 2024")
            month = int(mm.group(0))

    return (year, month)


def _get_date_from_item(item, date_keys, year_key=None, month_key=None):
    """Get one comparable date value from item: prefer full date, then year+month, then year."""
    for k in date_keys:
        v = item.get(k)
        if v is not None and (str(v).strip() if isinstance(v, str) else v):
            return v
    if year_key and item.get(year_key):
        y = item.get(year_key)
        m = (item.get(month_key) or "") if month_key else ""
        if m:
            try:
                return f"{y}-{int(m):02d}" if str(m).isdigit() else str(y)
            except (ValueError, TypeError):
                return str(y)
        return y
    return None


def _sort_key_end_start(item, end_date_keys, start_date_keys, ongoing_flags, end_year_key=None, end_month_key=None, start_year_key=None, start_month_key=None):
    """
    Sort key for reverse chronological order: ongoing first, then by end date (latest first),
    then by start date; no dates at bottom.
    Returns tuple: (priority, -end_ym, -start_ym) so ascending sort gives desired order.
    """
    end_val = _get_date_from_item(item, end_date_keys, end_year_key, end_month_key)
    start_val = _get_date_from_item(item, start_date_keys, start_year_key, start_month_key)
    is_ongoing = (
        any(item.get(k) in (True, "true", "True", "present", "Present", "current", "Current") for k in ongoing_flags)
        or (start_val and not end_val)
    )
    if is_ongoing:
        return (0, (9999, 12), (9999, 12))
    end_ym = _parse_date_for_sort(end_val)
    start_ym = _parse_date_for_sort(start_val, default_ym=(0, 0))
    if end_ym == (0, 0) and start_ym == (0, 0):
        return (2, (0, 0), (0, 0))
    return (1, (-end_ym[0], -end_ym[1]), (-start_ym[0], -start_ym[1]))


def _sort_key_single_date(item, date_keys):
    """Sort key for items with a single date (e.g. certifications by issue_date, achievements by date). Latest first."""
    vals = [item.get(k) for k in date_keys if item.get(k) is not None and str(item.get(k)).strip()]
    ym = _parse_date_for_sort(vals[0] if vals else None)
    if ym == (0, 0):
        return ((0, 0), (0, 0))
    return ((-ym[0], -ym[1]), (0, 0))


def sort_profile_sections_reverse_chronological(profile: dict) -> dict:
    """
    Sort education, experience, projects, clubs, certifications, achievements in profile
    by reverse chronological order (latest first). Ongoing items (no end / Present) first.
    Modifies profile in place and returns it.
    """
    if not profile or not isinstance(profile, dict):
        return profile

    # Education: present-first + reverse chronological by latest available date,
    # then preferred degree logical order (Btech, Diploma, Intermediate, HSC, SSC).
    # For ongoing entries, we sort by *start date* (latest first).
    edu_degree_order = {"Btech": 0, "Diploma": 1, "Intermediate": 2, "HSC": 3, "SSC": 4}

    def _truthy_current(val) -> bool:
        return val in (True, "true", "True", "current", "Current", "present", "Present", "presently", "Presently")

    def _education_sort_key(it: dict):
        it = it if isinstance(it, dict) else {}
        current = _truthy_current(it.get("current")) or (
            it.get("start_date") and not (it.get("end_date") or it.get("end_year"))
        )
        start_val = it.get("start_date") or it.get("start_year")
        end_val = it.get("end_date") or it.get("end_year")
        start_ym = _parse_date_for_sort(start_val)
        end_ym = _parse_date_for_sort(end_val)

        latest_ym = start_ym if current else end_ym
        degree = _canonical_education_degree(it.get("degree")) or it.get("degree")
        degree_weight = edu_degree_order.get(degree, 99)
        # ascending sort -> lower tuples first; we want latest first so use negatives
        return (
            0 if current else 1,
            -latest_ym[0],
            -latest_ym[1],
            -start_ym[0],
            -start_ym[1],
            degree_weight,
        )

    arr = profile.get("education")
    if isinstance(arr, list) and len(arr) > 0:
        profile["education"] = sorted(arr, key=_education_sort_key)

    # Experience/projects/clubs: existing reverse-chronological sorting (ongoing first when `current` exists).
    for key, end_keys, start_keys, ongoing, end_yr, end_mo, start_yr, start_mo in [
        ("experience", ["end_date", "end_year"], ["start_date", "start_year"], ["current"], "end_year", "end_month", "start_year", "start_month"),
        ("projects", ["end_date", "end_year"], ["start_date", "start_year"], [], "end_year", "end_month", "start_year", "start_month"),
        ("clubs", ["end_date", "end_year"], ["start_date", "start_year"], ["current"], "end_year", "end_month", "start_year", "start_month"),
    ]:
        arr = profile.get(key)
        if isinstance(arr, list) and len(arr) > 0:
            profile[key] = sorted(
                arr,
                key=lambda x: _sort_key_end_start(
                    x if isinstance(x, dict) else {},
                    end_keys,
                    start_keys,
                    ongoing,
                    end_yr, end_mo, start_yr, start_mo,
                ),
            )

    # Certifications: by issue_date (latest first)
    arr = profile.get("certifications")
    if isinstance(arr, list) and len(arr) > 0:
        profile["certifications"] = sorted(
            arr,
            key=lambda x: _sort_key_single_date(x if isinstance(x, dict) else {}, ["issue_date", "date", "issue_year"]),
        )

    # Achievements: by date (latest first)
    arr = profile.get("achievements")
    if isinstance(arr, list) and len(arr) > 0:
        profile["achievements"] = sorted(
            arr,
            key=lambda x: _sort_key_single_date(x if isinstance(x, dict) else {}, ["date"]),
        )

    return profile


# ---------- Student profile normalization/validation helpers ----------
_OPEN_TO_OPTIONS = ["Internships", "Full-time", "Projects", "Part-time", "Freelance"]
_STATUS_OPTIONS = ["Intern", "Placed", "Looking for opportunities"]
_EDUCATION_DEGREE_OPTIONS = ["SSC", "HSC", "Intermediate", "Diploma", "Btech"]
_LANG_PROFICIENCY_OPTIONS = [
    "Elementary proficiency",
    "Limited working proficiency",
    "Professional working proficiency",
    "Full professional proficiency",
    "Native or bilingual proficiency",
]
_INTERNSHIP_EMPLOYMENT_TYPES = [
    "Full-time",
    "Part-time",
    "Self-employed",
    "Freelance",
    "Internship",
    "Apprenticeship",
]
_LOCATION_TYPE_OPTIONS = ["On-site", "Hybrid", "Remote"]
_SKILL_LEVEL_OPTIONS = ["Beginner", "Intermediate", "Advanced"]
_CLUB_TYPE_OPTIONS = ["Clubs", "Councils", "Organisation"]
_COUNCIL_OPTIONS = ["IEEE", "CSI", "TPC", "E-cell", "IIC", "Alumni Committee", "ACM", "Sports Council", "Student Council", "GDG", "Other"]
_CLUB_OPTIONS = ["Writer's Club", "Theatre Club", "Singing Club", "Sports Club", "Dancing Club"]


def _truthy_token_str(val) -> bool:
    return isinstance(val, str) and val.strip().lower() in {"true", "present", "current", "yes", "1"}


def _truthy_bool(val) -> bool:
    return val in (True, "true", "True") or _truthy_token_str(val)


def _clean_str(val, max_len: int | None = None) -> str | None:
    if val is None:
        return None
    if not isinstance(val, str):
        val = str(val)
    s = val.strip()
    if not s:
        return None
    if max_len is not None and len(s) > max_len:
        s = s[:max_len]
    return s


def _clean_multiline_str(val, max_len: int | None = None) -> str | None:
    """
    Keep user formatting (line breaks/spaces) while validating non-empty content.
    """
    if val is None:
        return None
    if not isinstance(val, str):
        val = str(val)
    s = val
    if max_len is not None and len(s) > max_len:
        s = s[:max_len]
    if not s.strip():
        return None
    return s


def _canonical_open_to(values) -> list[str]:
    out: list[str] = []
    if not isinstance(values, list):
        return out
    mapping = {
        "internship": "Internships",
        "internships": "Internships",
        "full_time": "Full-time",
        "full-time": "Full-time",
        "projects": "Projects",
        "project": "Projects",
        "part_time": "Part-time",
        "part-time": "Part-time",
        "part time": "Part-time",
        "freelance": "Freelance",
    }
    for v in values:
        if not isinstance(v, str):
            continue
        vv = v.strip()
        if not vv:
            continue
        vv_can = mapping.get(vv, vv)
        if vv_can in _OPEN_TO_OPTIONS:
            out.append(vv_can)
    # De-dupe while preserving order
    seen = set()
    deduped: list[str] = []
    for v in out:
        if v in seen:
            continue
        seen.add(v)
        deduped.append(v)
    return deduped


def _canonical_status(status: str | None) -> str | None:
    s = _clean_str(status, 60)
    if not s:
        return None
    s_norm = s.strip()
    legacy_map = {
        "Looking for Opportunities": "Looking for opportunities",
        "looking for opportunities": "Looking for opportunities",
        "Student": "Looking for opportunities",
        "student": "Looking for opportunities",
    }
    if s_norm in legacy_map:
        s_norm = legacy_map[s_norm]
    if s_norm not in _STATUS_OPTIONS:
        return None
    return s_norm


def _parse_iso_ym(date_str: str | None) -> tuple[int | None, int | None]:
    if not date_str or not isinstance(date_str, str):
        return (None, None)
    m = re.match(r"^(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})$", date_str.strip())
    if not m:
        return (None, None)
    y = int(m.group("y"))
    mo = int(m.group("m"))
    return (y, mo)


def _ym_to_iso(month: int | str | None, year: int | str | None) -> str | None:
    if year is None or month is None:
        return None
    try:
        y = int(year)
        mo = int(month)
    except (TypeError, ValueError):
        return None
    if y < 1900 or y > 3000 or mo < 1 or mo > 12:
        return None
    return f"{y:04d}-{mo:02d}-01"


def _parse_month_year_parts(month_val, year_val) -> tuple[str | None, str | None, str | None]:
    """
    Returns (month_str_01_12, year_str_YYYY, iso_date).
    """
    month_s = None
    year_s = None
    iso = None
    if year_val is not None and str(year_val).strip():
        try:
            y = int(str(year_val).strip())
            year_s = f"{y:04d}"
        except (TypeError, ValueError):
            year_s = None
    if month_val is not None and str(month_val).strip():
        try:
            mo = int(str(month_val).strip())
            if 1 <= mo <= 12:
                month_s = f"{mo:02d}"
        except (TypeError, ValueError):
            month_s = None
    if year_s and month_s:
        iso = _ym_to_iso(month_s, year_s)
    return (month_s, year_s, iso)


def _canonical_education_degree(degree_raw: str | None) -> str | None:
    d = _clean_str(degree_raw, 40)
    if not d:
        return None
    dl = d.lower()
    if "ssc" in dl:
        return "SSC"
    if "hsc" in dl:
        return "HSC"
    if "intermediate" in dl:
        return "Intermediate"
    if "diploma" in dl:
        return "Diploma"
    if "b.tech" in dl or "b.e" in dl or "btech" in dl or "b.e" in dl or "btech" in dl:
        return "Btech"
    if "m.tech" in dl or "m.e" in dl:
        # legacy: treat higher degree as Btech for dropdown compatibility
        return "Btech"
    if d in _EDUCATION_DEGREE_OPTIONS:
        return d
    return None


def _normalize_education_item(item: dict) -> dict:
    item = dict(item or {})
    school = _clean_str(item.get("school") or item.get("college_name") or item.get("university") or item.get("name"), 200)
    degree = _canonical_education_degree(item.get("degree"))
    # Legacy: some UIs store "field" even for board; we keep both keys.
    board = _clean_str(item.get("board") or item.get("board_name") or item.get("boardText"), 200)
    field_of_study = _clean_str(item.get("field_of_study") or item.get("field") or item.get("field_ofstudy"), 200)
    cgpa = _clean_str(item.get("cgpa") or item.get("percentage") or item.get("score"), 20)

    # Dates: accept either month/year parts or iso start_date/end_date, and set `current`.
    current = _truthy_bool(item.get("current")) or False
    start_month = item.get("start_month")
    start_year = item.get("start_year")
    end_month = item.get("end_month")
    end_year = item.get("end_year")

    start_date = _clean_str(item.get("start_date"))
    end_date = _clean_str(item.get("end_date"))

    # Back-compat: older payloads use start_year/end_year + iso date strings.
    if not start_date and item.get("start_year") and str(item.get("start_year")).strip():
        # ISO not guaranteed; default month=01
        start_year = item.get("start_year")
        start_month = start_month or "01"
        start_date = _ym_to_iso(start_month, start_year)
    if not end_date and item.get("end_year") and str(item.get("end_year")).strip():
        end_year = item.get("end_year")
        end_month = end_month or "01"
        end_date = _ym_to_iso(end_month, end_year)

    # If current was not explicitly provided, infer from missing end_date/end_year.
    if not current:
        if not (end_date or (item.get("end_year") or "").strip()):
            # present / currently studying
            current = True

    # Normalize month/year + iso for sorting.
    # Prefer explicit start_month/start_year; else derive from start_date.
    if not start_year or not start_month:
        y, mo = _parse_iso_ym(start_date)
        start_year = start_year or y
        start_month = start_month or (f"{mo:02d}" if mo else None)
    if not end_year or not end_month:
        y, mo = _parse_iso_ym(end_date)
        end_year = end_year or y
        end_month = end_month or (f"{mo:02d}" if mo else None)

    start_month_s, start_year_s, start_iso = _parse_month_year_parts(start_month, start_year)
    # If start_iso still missing, try parse from whatever we have.
    start_iso = start_iso or _clean_str(item.get("start_date"))

    if current:
        end_month_s = None
        end_year_s = None
        end_iso = None
        # remove end date fields for ongoing entries
        end_date = None
        end_month = None
        end_year = None
    else:
        end_month_s, end_year_s, end_iso = _parse_month_year_parts(end_month, end_year)
        end_iso = end_iso or _clean_str(item.get("end_date"))

    # Ensure compatibility with existing UI code that uses `field`.
    if degree in {"SSC", "HSC", "Intermediate"}:
        # board-centric
        field_legacy = board
    else:
        field_legacy = field_of_study

    # If degree is missing, keep whatever was provided (but still normalize dates).
    return {
        "school": school,
        "degree": degree,
        "board": board if board else None,
        "field_of_study": field_of_study if field_of_study else None,
        "field": field_legacy if field_legacy else None,  # legacy/display fallback
        "cgpa": cgpa,
        "current": bool(current),
        "start_month": start_month_s,
        "start_year": start_year_s,
        "start_date": start_iso,
        "end_month": (end_month_s if end_month_s else None),
        "end_year": (end_year_s if end_year_s else None),
        "end_date": end_iso if end_iso else None,
        "description": _clean_str(item.get("description"), 1000),
    }


def _normalize_skill_item(item: dict) -> dict:
    item = dict(item or {})
    name = _clean_str(item.get("name"), 80)
    level_raw = _clean_str(item.get("level"), 40) or None
    level = None
    if level_raw:
        for opt in _SKILL_LEVEL_OPTIONS:
            if level_raw.lower() == opt.lower():
                level = opt
                break
    return {"name": name, "level": level}


def _normalize_languages_payload(languages):
    out = []
    if not isinstance(languages, list):
        return out
    for x in languages:
        if isinstance(x, str):
            lang = _clean_str(x, 60)
            if lang:
                out.append({"language": lang, "proficiency": None})
            continue
        if isinstance(x, dict):
            lang = _clean_str(x.get("language") or x.get("name") or x.get("lang"), 60)
            prof_raw = _clean_str(x.get("proficiency") or x.get("level") or x.get("proficiency_level"), 80)
            prof = None
            if prof_raw:
                for opt in _LANG_PROFICIENCY_OPTIONS:
                    if prof_raw.lower() == opt.lower():
                        prof = opt
                        break
            if lang:
                out.append({"language": lang, "proficiency": prof})
            continue
    return out


def _canonical_internship_employment_type(v: str | None) -> str | None:
    s = _clean_str(v, 60)
    if not s:
        return None
    for opt in _INTERNSHIP_EMPLOYMENT_TYPES:
        if s.lower() == opt.lower():
            return opt
    return None


def _canonical_location_type(v: str | None) -> str | None:
    s = _clean_str(v, 20)
    if not s:
        return None
    for opt in _LOCATION_TYPE_OPTIONS:
        if s.lower() == opt.lower():
            return opt
    return None


def _normalize_month_year_fields_for_item(item: dict, prefix: str) -> tuple[str | None, str | None, str | None]:
    month_val = item.get(f"{prefix}_month") or item.get(f"{prefix}Month")
    year_val = item.get(f"{prefix}_year") or item.get(f"{prefix}Year")
    date_val = item.get(f"{prefix}_date") or item.get(f"{prefix}Date")
    # If iso date provided, override year/month when month/year missing
    if (not month_val or not year_val) and date_val:
        y, mo = _parse_iso_ym(str(date_val))
        year_val = year_val or y
        month_val = month_val or (f"{mo:02d}" if mo else None)
    m_s, y_s, iso = _parse_month_year_parts(month_val, year_val)
    # If iso still missing but we have date_val, try to keep it.
    iso = iso or _clean_str(date_val)
    return (m_s, y_s, iso)


def _normalize_experience_item(item: dict) -> dict:
    """
    Normalize internship/experience items for both:
    - legacy: {company, role, location, duration, description}
    - new:    {company, role, employment_type, current, start/end month+year, location_type, skills[], description, offer_letter_url, completion_certificate_url}
    """
    item = dict(item or {})
    company = _clean_str(item.get("company") or item.get("company_name"), 200)
    role = _clean_str(item.get("role") or item.get("internship_role"), 200)
    location = _clean_str(item.get("location"), 200)
    employment_type = _canonical_internship_employment_type(item.get("employment_type"))

    location_type = _canonical_location_type(item.get("location_type") or item.get("mode"))
    # Legacy mismatch: old /api/profile edit stored On-site/Remote/Hybrid inside employment_type.
    if not location_type and item.get("employment_type") in _LOCATION_TYPE_OPTIONS:
        location_type = _canonical_location_type(item.get("employment_type"))
        employment_type = employment_type  # likely None

    description = _clean_str(item.get("description"), 1000)

    current = _truthy_bool(item.get("current")) or False
    start_month_s, start_year_s, start_iso = _normalize_month_year_fields_for_item(item, "start")
    end_month_s, end_year_s, end_iso = _normalize_month_year_fields_for_item(item, "end")

    # Legacy: some entries only have duration string; infer `current` when duration contains "Present"
    if not current and isinstance(item.get("duration"), str) and "present" in item.get("duration").lower():
        current = True

    # If current not explicitly set, infer from missing end_date/end_year.
    if not current:
        if not (item.get("end_date") or item.get("end_year") or end_iso or end_year_s):
            current = True

    if current:
        end_month_s = None
        end_year_s = None
        end_iso = None
        end_date = None
    # Skills: list[str]
    skills = item.get("skills")
    skills_out: list[str] = []
    if isinstance(skills, list):
        for s in skills:
            cs = _clean_str(s, 80)
            if cs:
                skills_out.append(cs)
    elif isinstance(skills, str):
        # allow comma-separated fallback
        for s in skills.split(","):
            cs = _clean_str(s, 80)
            if cs:
                skills_out.append(cs)

    # Compatibility: compute a duration string if possible
    def _format_month_year(month_s, year_s):
        if not month_s and not year_s:
            return ""
        if month_s and year_s:
            # month_s is 01..12
            try:
                mo = int(month_s)
            except Exception:
                mo = None
            if mo:
                month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
                return f"{month_names[mo-1]} {year_s}"
        return str(year_s or "").strip()

    duration = item.get("duration") or None
    if not duration:
        start_label = _format_month_year(start_month_s, start_year_s)
        if current:
            duration = f"{start_label} - Present" if start_label else "Present"
        else:
            end_label = _format_month_year(end_month_s, end_year_s)
            if start_label and end_label:
                duration = f"{start_label} - {end_label}"

    out = {
        "company": company,
        "role": role,
        "employment_type": employment_type,
        "location": location,
        "location_type": location_type,
        "skills": skills_out,
        "description": description,
        "current": bool(current),
        "start_month": start_month_s,
        "start_year": start_year_s,
        "start_date": start_iso,
        "end_month": end_month_s,
        "end_year": end_year_s,
        "end_date": end_iso,
        "duration": duration,
    }

    # Preserve existing media URLs on PUT:
    # only include these keys if the incoming payload had them.
    if "offer_letter_url" in item or "offer_letter_media_url" in item:
        out["offer_letter_url"] = _clean_str(item.get("offer_letter_url") or item.get("offer_letter_media_url"))
    if "completion_certificate_url" in item or "completion_certificate_media_url" in item:
        out["completion_certificate_url"] = _clean_str(item.get("completion_certificate_url") or item.get("completion_certificate_media_url"))
    if "media_url" in item:
        # legacy media_url field
        out["media_url"] = _clean_str(item.get("media_url"))

    return out


def _normalize_club_item(item: dict) -> dict:
    item = dict(item or {})
    # New schema may send `type` + subtype fields; we normalize into the existing-friendly keys:
    # - name, role, description
    # - duration dates: start/end month+year + `current`
    club_type = _clean_str(item.get("type"), 50)
    name = _clean_str(item.get("name") or item.get("organization_name") or item.get("organisation_name"), 200)
    role = _clean_str(item.get("role"), 200)
    description = _clean_str(item.get("description"), 1000)

    current = _truthy_bool(item.get("current")) or False
    start_month_s, start_year_s, start_iso = _normalize_month_year_fields_for_item(item, "start")
    end_month_s, end_year_s, end_iso = _normalize_month_year_fields_for_item(item, "end")

    if not current and isinstance(item.get("duration"), str) and "present" in item.get("duration").lower():
        current = True
    if not current:
        if not (item.get("end_date") or item.get("end_year") or end_iso or end_year_s):
            current = True
    if current:
        end_month_s, end_year_s, end_iso = None, None, None

    duration = item.get("duration")
    if not duration:
        def _format_month_year(month_s, year_s):
            if not month_s and not year_s:
                return ""
            if month_s and year_s:
                try:
                    mo = int(month_s)
                except Exception:
                    mo = None
                if mo:
                    month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
                    return f"{month_names[mo-1]} {year_s}"
            return str(year_s or "").strip()
        start_label = _format_month_year(start_month_s, start_year_s)
        if current:
            duration = f"{start_label} - Present" if start_label else "Present"
        else:
            end_label = _format_month_year(end_month_s, end_year_s)
            duration = f"{start_label} - {end_label}" if start_label and end_label else None

    return {
        "name": name,
        "role": role,
        "type": club_type,
        "sport_name": _clean_str(item.get("sport_name"), 60),
        "current": bool(current),
        "start_month": start_month_s,
        "start_year": start_year_s,
        "start_date": start_iso,
        "end_month": end_month_s,
        "end_year": end_year_s,
        "end_date": end_iso,
        "duration": duration,
        "description": description,
        # legacy compatibility
        "notes": _clean_str(item.get("notes"), 500),
    }


def _normalize_alumni_council_item(item: dict) -> dict:
    """
    Councils for alumni: same storage key as student `clubs`, but no open-ended "current" term;
    start and end dates should both be supplied (UI enforced).
    """
    item = dict(item or {})
    club_type = _clean_str(item.get("type"), 50)
    name = _clean_str(item.get("name") or item.get("organization_name") or item.get("organisation_name"), 200)
    role = _clean_str(item.get("role"), 200)
    description = _clean_str(item.get("description"), 1000)
    start_month_s, start_year_s, start_iso = _normalize_month_year_fields_for_item(item, "start")
    end_month_s, end_year_s, end_iso = _normalize_month_year_fields_for_item(item, "end")

    def _format_month_year(month_s, year_s):
        if not month_s and not year_s:
            return ""
        if month_s and year_s:
            try:
                mo = int(month_s)
            except Exception:
                mo = None
            if mo:
                month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                return f"{month_names[mo - 1]} {year_s}"
        return str(year_s or "").strip()

    start_label = _format_month_year(start_month_s, start_year_s)
    end_label = _format_month_year(end_month_s, end_year_s)
    duration = None
    if start_label and end_label:
        duration = f"{start_label} - {end_label}"
    elif start_label:
        duration = start_label

    return {
        "name": name,
        "role": role,
        "type": club_type,
        "sport_name": _clean_str(item.get("sport_name"), 60),
        "current": False,
        "start_month": start_month_s,
        "start_year": start_year_s,
        "start_date": start_iso,
        "end_month": end_month_s,
        "end_year": end_year_s,
        "end_date": end_iso,
        "duration": duration,
        "description": description,
        "notes": _clean_str(item.get("notes"), 500),
    }


def _normalize_certification_item(item: dict) -> dict:
    item = dict(item or {})
    name = _clean_str(item.get("name"), 120)
    issuer = _clean_str(item.get("issuer"), 120)
    credential_url = _clean_str(item.get("credential_url"), 500)
    description = _clean_str(item.get("description"), 1000)  # optional, not required

    # issue
    issue_month_s, issue_year_s, issue_iso = _normalize_month_year_fields_for_item(item, "issue")
    # expiry optional
    expiry_month_s, expiry_year_s, expiry_iso = _normalize_month_year_fields_for_item(item, "expiry")

    # Legacy: older UI used `issue_date`/`expiry_date` directly.
    if not issue_iso and item.get("issue_date"):
        issue_iso = _clean_str(item.get("issue_date"))
        y, mo = _parse_iso_ym(issue_iso)
        issue_year_s = issue_year_s or (f"{y:04d}" if y else None)
        issue_month_s = issue_month_s or (f"{mo:02d}" if mo else None)
    if not expiry_iso and item.get("expiry_date"):
        expiry_iso = _clean_str(item.get("expiry_date"))
        y, mo = _parse_iso_ym(expiry_iso)
        expiry_year_s = expiry_year_s or (f"{y:04d}" if y else None)
        expiry_month_s = expiry_month_s or (f"{mo:02d}" if mo else None)

    out = {
        "name": name,
        "issuer": issuer,
        "credential_url": credential_url,
        "description": description,
        "issue_month": issue_month_s,
        "issue_year": issue_year_s,
        "issue_date": issue_iso,
        "expiry_month": expiry_month_s,
        "expiry_year": expiry_year_s,
        "expiry_date": expiry_iso,
    }
    if "media_url" in item:
        out["media_url"] = _clean_str(item.get("media_url"))
    return out


def _normalize_achievement_item(item: dict) -> dict:
    item = dict(item or {})
    title = _clean_str(item.get("title"), 160)
    associated_with = _clean_str(item.get("associated_with") or item.get("issuer"), 200)
    issuer = associated_with  # keep legacy key for existing views/posts
    description = _clean_str(item.get("description"), 2000)

    # issue date (new) / date (legacy)
    issue_month_s, issue_year_s, issue_iso = _normalize_month_year_fields_for_item(item, "issue")
    if not issue_iso and item.get("date"):
        issue_iso = _clean_str(item.get("date"))
        y, mo = _parse_iso_ym(issue_iso)
        issue_year_s = issue_year_s or (f"{y:04d}" if y else None)
        issue_month_s = issue_month_s or (f"{mo:02d}" if mo else None)

    # keep legacy key `date` for sorting and posts
    out = {
        "title": title,
        "associated_with": associated_with,
        "issuer": issuer,
        "issue_month": issue_month_s,
        "issue_year": issue_year_s,
        "date": issue_iso,
        "description": description,
    }
    if "media_url" in item:
        out["media_url"] = _clean_str(item.get("media_url"))
    return out


# ---------- Student profile completion ----------
def _truthy_str(val) -> bool:
    return isinstance(val, str) and val.strip() != ""


def calculate_profile_completion(profile: dict) -> int:
    """
    Compute completion 0-100 based on presence of sections.
    This is deterministic and safe for partial/incomplete profiles.
    """
    p = profile or {}

    # Weights must sum to 100
    weights = {
        "basic": 15,
        "education": 15,
        "internships": 15,  # stored as profile.experience
        "projects": 20,
        "skills": 15,
        "clubs": 10,
    }

    basic = p.get("basic") or {}
    basic_done = any([_truthy_str(basic.get("headline")), _truthy_str(basic.get("location"))]) or bool(p.get("open_to"))

    education_done = bool(p.get("education")) and isinstance(p.get("education"), list) and len(p.get("education")) > 0
    internships_done = bool(p.get("experience")) and isinstance(p.get("experience"), list) and len(p.get("experience")) > 0
    projects_done = bool(p.get("projects")) and isinstance(p.get("projects"), list) and len(p.get("projects")) > 0
    skills_done = bool(p.get("skills")) and isinstance(p.get("skills"), list) and len(p.get("skills")) > 0
    clubs_done = bool(p.get("clubs")) and isinstance(p.get("clubs"), list) and len(p.get("clubs")) > 0

    score = 0
    score += weights["basic"] if basic_done else 0
    score += weights["education"] if education_done else 0
    score += weights["internships"] if internships_done else 0
    score += weights["projects"] if projects_done else 0
    score += weights["skills"] if skills_done else 0
    score += weights["clubs"] if clubs_done else 0

    return max(0, min(100, int(score)))


def calculate_alumni_profile_completion(profile: dict, user_doc: dict) -> int:
    """
    Alumni profile completion 0-100: professional basics, work profile, student-like sections,
    councils, and notes/resources for students.
    """
    p = profile or {}
    u = user_doc or {}
    w = {
        "name": 5,
        "headline": 5,
        "phone": 3,
        "photos": 5,
        "company": 7,
        "designation": 7,
        "location": 3,
        "industry": 1,
        "pass_branch": 5,
        "work_profile": 10,
        "experience": 7,
        "education": 7,
        "skills": 6,
        "projects": 4,
        "certifications": 4,
        "achievements": 4,
        "councils": 4,
        "resources": 4,
        "bio": 4,
        "linkedin": 2,
        "portfolio": 2,
    }
    first = (u.get("first_name") or "").strip()
    last = (u.get("last_name") or "").strip()
    name_done = bool(first or last)
    headline_done = _truthy_str(p.get("headline"))
    phone_done = _truthy_str(p.get("phone"))
    photo = p.get("profile_photo") or {}
    cover = p.get("cover_photo") or {}
    photos_done = bool((isinstance(photo, dict) and photo.get("secure_url")) or (isinstance(photo, str) and photo.strip())) or bool(
        (isinstance(cover, dict) and cover.get("secure_url")) or (isinstance(cover, str) and str(cover).strip())
    )
    company_done = _truthy_str(p.get("current_company"))
    designation_done = _truthy_str(p.get("designation"))
    location_done = _truthy_str(p.get("location"))
    industry_done = _truthy_str(p.get("industry"))
    pass_branch_done = (
        _truthy_str(p.get("branch") or u.get("branch") or u.get("branch_code"))
        and _truthy_str(str(p.get("passing_year") or p.get("passout_year") or u.get("passout_year") or ""))
        and _truthy_str(p.get("degree"))
    )
    wp = p.get("work_profile") if isinstance(p.get("work_profile"), dict) else {}
    work_profile_done = (
        _truthy_str(wp.get("organization") or wp.get("current_organization"))
        and _truthy_str(wp.get("work_domain"))
        and (
            _truthy_str(wp.get("department") or wp.get("team"))
            or (isinstance(wp.get("responsibilities"), list) and len(wp.get("responsibilities")) > 0)
            or _truthy_str(wp.get("technologies_used") or wp.get("technologies"))
        )
    )
    exp_done = (
        (bool(p.get("experience_timeline")) and isinstance(p.get("experience_timeline"), list) and len(p.get("experience_timeline")) > 0)
        or (bool(p.get("experience")) and isinstance(p.get("experience"), list) and len(p.get("experience")) > 0)
    )
    edu_done = bool(p.get("education")) and isinstance(p.get("education"), list) and len(p.get("education")) > 0
    skills_done = bool(p.get("skills")) and isinstance(p.get("skills"), list) and len(p.get("skills")) > 0
    proj_done = bool(p.get("projects")) and isinstance(p.get("projects"), list) and len(p.get("projects")) > 0
    cert_done = bool(p.get("certifications")) and isinstance(p.get("certifications"), list) and len(p.get("certifications")) > 0
    ach_done = bool(p.get("achievements")) and isinstance(p.get("achievements"), list) and len(p.get("achievements")) > 0
    council_done = bool(p.get("clubs")) and isinstance(p.get("clubs"), list) and len(p.get("clubs")) > 0
    res_items = p.get("student_resources") or p.get("notes_for_students") or []
    resources_done = isinstance(res_items, list) and len(res_items) > 0
    bio_done = _truthy_str(p.get("bio"))
    linkedin_done = _truthy_str(p.get("linkedin_url"))
    portfolio_done = _truthy_str(p.get("portfolio_url"))
    score = (
        (w["name"] if name_done else 0)
        + (w["headline"] if headline_done else 0)
        + (w["phone"] if phone_done else 0)
        + (w["photos"] if photos_done else 0)
        + (w["company"] if company_done else 0)
        + (w["designation"] if designation_done else 0)
        + (w["location"] if location_done else 0)
        + (w["industry"] if industry_done else 0)
        + (w["pass_branch"] if pass_branch_done else 0)
        + (w["work_profile"] if work_profile_done else 0)
        + (w["experience"] if exp_done else 0)
        + (w["education"] if edu_done else 0)
        + (w["skills"] if skills_done else 0)
        + (w["projects"] if proj_done else 0)
        + (w["certifications"] if cert_done else 0)
        + (w["achievements"] if ach_done else 0)
        + (w["councils"] if council_done else 0)
        + (w["resources"] if resources_done else 0)
        + (w["bio"] if bio_done else 0)
        + (w["linkedin"] if linkedin_done else 0)
        + (w["portfolio"] if portfolio_done else 0)
    )
    return max(0, min(100, int(score)))


# ---------- Notifications ----------
def create_notification(user_id: ObjectId, message: str, notification_type: str = None, 
                        reference_id: ObjectId = None, reference_type: str = None,
                        metadata: dict = None, post_id: ObjectId = None, sender_id: ObjectId = None):
    """
    Store a notification document for the target user.
    notification_type: job, connection, message, application, etc.
    reference_type: job, profile, conversation, etc.
    reference_id: ObjectId of the referenced document
    metadata: Additional data for special notification types (e.g., connection_id for pending requests)
    """
    try:
        doc = {
            "user_id": user_id,
            "message": str(message or ""),
            "is_read": False,
            "created_at": datetime.utcnow(),
        }
        if notification_type:
            doc["notification_type"] = notification_type
        if reference_id:
            doc["reference_id"] = reference_id
        if reference_type:
            doc["reference_type"] = reference_type
        if metadata:
            doc["metadata"] = metadata
        if post_id:
            doc["post_id"] = post_id
        if sender_id:
            doc["sender_id"] = sender_id
        db["notifications"].insert_one(doc)
    except Exception:
        # Notification failure must never break main flows.
        pass


def _default_post_settings() -> dict:
    return {
        "comments_enabled": True,
        "show_like_count": True,
        "show_comment_count": True,
    }


def _normalized_post_settings(raw) -> dict:
    d = _default_post_settings()
    if isinstance(raw, dict):
        for k in d:
            if k in raw and raw[k] is not None:
                d[k] = bool(raw[k])
    return d


def _parse_post_settings_from_payload(data: dict) -> dict:
    """Merge settings from JSON body (create/edit post)."""
    if not isinstance(data, dict):
        return _default_post_settings()
    raw = data.get("settings")
    if isinstance(raw, dict):
        return _normalized_post_settings(raw)
    out = _default_post_settings()
    for key in ("comments_enabled", "show_like_count", "show_comment_count"):
        if key in data:
            out[key] = bool(data[key])
    return out


def _parse_post_settings_from_form() -> dict:
    """Checkbox-style fields on multipart post create."""
    out = _default_post_settings()
    for key in ("comments_enabled", "show_like_count", "show_comment_count"):
        v = request.form.get(key)
        if v is None:
            continue
        s = str(v).strip().lower()
        out[key] = s in ("1", "true", "yes", "on")
    return out


def _recompute_post_comments_count(post_oid: ObjectId) -> int:
    """Total comments including replies."""
    n = int(db["comments"].count_documents({"post_id": post_oid}))
    db["posts"].update_one({"_id": post_oid}, {"$set": {"comments_count": n}})
    return n


def _sync_likes_collection_with_post(post_oid: ObjectId, user_id: ObjectId, liked: bool) -> None:
    """Keep legacy `likes` collection aligned with post.likes array."""
    try:
        if liked:
            if not db["likes"].find_one({"post_id": post_oid, "user_id": user_id}):
                db["likes"].insert_one({
                    "post_id": post_oid,
                    "user_id": user_id,
                    "created_at": datetime.utcnow(),
                })
        else:
            db["likes"].delete_many({"post_id": post_oid, "user_id": user_id})
    except Exception:
        pass


def _serialize_post_interaction_fields(doc: dict, viewer: dict) -> dict:
    """
    Per-post privacy: hide counts from API for non-authors when settings say so.
    Author always sees true counts.
    """
    settings = _normalized_post_settings(doc.get("settings"))
    viewer_id = viewer.get("_id") if viewer else None
    author_id = doc.get("author_id")
    is_author = bool(viewer_id and author_id and viewer_id == author_id)

    likes_arr = doc.get("likes") or []
    likes_n = len(likes_arr) if likes_arr else int(doc.get("likes_count") or 0)
    comments_n = int(doc.get("comments_count") or 0)
    liked = bool(viewer_id and viewer_id in likes_arr) if likes_arr else bool(
        viewer_id and db["likes"].find_one({"post_id": doc.get("_id"), "user_id": viewer_id})
    )

    out = {
        "settings": settings,
        "liked": liked,
        "likes_count": likes_n if (is_author or settings["show_like_count"]) else None,
        "comments_count": comments_n if (is_author or settings["show_comment_count"]) else None,
        "likes_count_hidden": not (is_author or settings["show_like_count"]),
        "comments_count_hidden": not (is_author or settings["show_comment_count"]),
    }
    return out


def create_post_notification(receiver_id: ObjectId, sender_id: ObjectId, notif_type: str, post_id: ObjectId, message: str):
    """
    Create a post interaction notification with dedupe + self-notify prevention.
    notif_type: like | comment | mention
    """
    try:
        if not receiver_id or not sender_id or not post_id:
            return
        if str(receiver_id) == str(sender_id):
            return
        coll = db["notifications"]
        # Prevent duplicates for same sender/type/post/receiver while unread.
        existing = coll.find_one({
            "user_id": receiver_id,
            "sender_id": sender_id,
            "type": notif_type,
            "post_id": post_id,
            "is_read": False,
        })
        if existing:
            return
        coll.insert_one({
            "user_id": receiver_id,
            "sender_id": sender_id,
            "type": notif_type,
            "post_id": post_id,
            "message": str(message or ""),
            "is_read": False,
            "created_at": datetime.utcnow(),
            # Keep compatibility with existing notification renderer.
            "notification_type": notif_type,
            "reference_type": "post",
            "reference_id": post_id,
            "metadata": {"sender_id": str(sender_id)},
        })
    except Exception:
        pass


def _find_user_id_by_mention_token(key: str) -> ObjectId | None:
    """Resolve @Display Name to a student/alumni user id (exact name match)."""
    key = (key or "").strip().lower()
    if len(key) < 2:
        return None
    role_filter = {"role": {"$in": ["STUDENT", "ALUMNI", "student", "alumni"]}}
    try:
        for u in db["users"].find(role_filter).limit(8000):
            if user_hidden_from_campuslink_discovery(u):
                continue
            nm = _user_display_name(u).strip().lower()
            if not nm:
                continue
            if nm == key or nm.replace(" ", "") == key.replace(" ", ""):
                return u.get("_id")
    except Exception:
        return None
    return None


def _notify_comment_mentions_in_text(post_oid: ObjectId, sender: dict, text: str) -> None:
    """Notify users @mentioned in a comment body (student/alumni)."""
    if not text or not sender or not post_oid:
        return
    try:
        tokens = re.findall(r"\B@([A-Za-z][A-Za-z0-9_ ]{0,48})", text)
        seen: set[str] = set()
        for raw in tokens:
            key = raw.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            uid = _find_user_id_by_mention_token(key)
            if not uid or uid == sender.get("_id"):
                continue
            create_post_notification(
                uid,
                sender["_id"],
                "mention",
                post_oid,
                f"{_user_display_name(sender)} mentioned you in a comment",
            )
    except Exception:
        pass


def _mongo_query_users_for_announcement_audience(audience: list[str]) -> dict | None:
    """Match users who should receive an announcement (student / faculty+staff / alumni)."""
    aud = {str(x).lower().strip() for x in (audience or []) if x}
    clauses: list[dict] = []
    if "student" in aud:
        clauses.append({"$or": [{"user_type": "student"}, {"role": ROLE_STUDENT}]})
    if "faculty" in aud:
        clauses.append({"$or": [
            {"user_type": "faculty"}, {"role": ROLE_FACULTY},
            {"user_type": "coordinator"}, {"role": ROLE_COORDINATOR},
            {"user_type": "admin"}, {"role": ROLE_ADMIN},
        ]})
    if "alumni" in aud:
        clauses.append({"$or": [{"user_type": "alumni"}, {"role": ROLE_ALUMNI}]})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$or": clauses}


def _user_accepts_announcement_notifications(user_doc: dict) -> bool:
    """Alumni can disable platform announcements in alumni_settings."""
    if (user_doc.get("user_type") or "").strip().lower() != "alumni":
        return True
    st = user_doc.get("alumni_settings") or {}
    notif = st.get("notifications") or {}
    if notif.get("announcements") is False:
        return False
    return True


def fan_out_announcement_notifications(
    announcement_id: ObjectId,
    audience: list[str],
    title: str,
    creator_email: str | None,
) -> None:
    """
    Create in-app bell notifications for users matching the announcement audience.
    Skips creator, banned/hidden users, and alumni who opted out.
    """
    try:
        q = _mongo_query_users_for_announcement_audience(audience)
        if not q:
            return
        creator = (creator_email or "").strip().lower()
        raw_title = (title or "Campus update").strip()
        msg = f"New announcement: {raw_title}"
        if len(msg) > 500:
            msg = msg[:497] + "..."
        meta_title = raw_title[:200]
        now = datetime.utcnow()
        batch: list[dict] = []
        proj = {
            "_id": 1,
            "email": 1,
            "user_type": 1,
            "role": 1,
            "is_banned": 1,
            "account_status": 1,
            "status": 1,
            "verification_status": 1,
            "alumni_settings": 1,
        }
        for u in db["users"].find(q, projection=proj):
            if user_hidden_from_campuslink_discovery(u):
                continue
            uem = (u.get("email") or "").strip().lower()
            if creator and uem == creator:
                continue
            if not _user_accepts_announcement_notifications(u):
                continue
            batch.append({
                "user_id": u["_id"],
                "message": msg,
                "notification_type": "announcement",
                "type": "announcement",
                "reference_id": announcement_id,
                "reference_type": "announcement",
                "is_read": False,
                "created_at": now,
                "metadata": {"title": meta_title},
            })
            if len(batch) >= 500:
                db["notifications"].insert_many(batch, ordered=False)
                batch = []
        if batch:
            db["notifications"].insert_many(batch, ordered=False)
    except Exception:
        pass


def _user_profile_photo_url(user_doc: dict):
    profile = (user_doc or {}).get("profile") or {}
    return _profile_photo_url(profile.get("profile_photo"))


# ---------- Activity Tracking ----------
def create_activity(user_id: ObjectId, activity_type: str, reference_id: ObjectId, 
                   reference_type: str, metadata: dict = None):
    """
    Track user activity for the Activity section on profile.
    activity_type: post, comment, reaction, application
    reference_type: job, post, announcement
    """
    try:
        db["activities"].insert_one({
            "user_id": user_id,
            "activity_type": activity_type,
            "reference_id": reference_id,
            "reference_type": reference_type,
            "metadata": metadata or {},
            "created_at": datetime.utcnow(),
        })
    except Exception:
        # Activity tracking failure must never break main flows.
        pass


def get_user_activities(user_id: ObjectId, activity_type: str = None, limit: int = 10):
    """
    Get activities for a user, optionally filtered by type.
    """
    query = {"user_id": user_id}
    if activity_type:
        query["activity_type"] = activity_type
    
    activities = []
    for doc in db["activities"].find(query).sort("created_at", -1).limit(limit):
        activities.append({
            "id": str(doc.get("_id")),
            "activity_type": doc.get("activity_type"),
            "reference_id": str(doc.get("reference_id")),
            "reference_type": doc.get("reference_type"),
            "metadata": doc.get("metadata") or {},
            "created_at": to_utc_iso(doc.get("created_at")),
        })
    return activities


# ---------- Jobs / Internships Module ----------
def _parse_branches(value):
    """
    Accept list or comma-separated string, return list of upper branch codes.
    """
    if value is None:
        return []
    if isinstance(value, list):
        raw = value
    else:
        raw = str(value).split(",")
    out = []
    for b in raw:
        bc = normalize_branch_code(b)
        if bc:
            out.append(bc)
    # de-duplicate while preserving order
    seen = set()
    uniq = []
    for b in out:
        if b in seen:
            continue
        seen.add(b)
        uniq.append(b)
    return uniq


# --- Structured job post (coordinator/admin form v2) ---
ALLOWED_JOB_TYPES_V2 = {"Full-time", "Internship", "Part-time", "Project"}
ALLOWED_WORK_MODES_V2 = {"On-site", "Remote", "Hybrid"}
JOB_FORM_BRANCH_OPTIONS = ("CST", "IT", "ENC", "DS", "AI", "CE")
JOB_FORM_BATCH_YEARS = ("2024", "2025", "2026", "2027")
JOB_FORM_BACKLOG_OPTIONS = ("Allowed", "Not Allowed", "Other")
JOB_FORM_PERK_OPTIONS = ("Certificate", "PPO (Pre-Placement Offer)", "Flexible hours", "Learning opportunities")
MAX_JOB_PDF_ATTACHMENTS = 10


def _canonical_job_type_v2(raw: str) -> str | None:
    t = (raw or "").strip()
    if t == "Full-Time":
        t = "Full-time"
    if t in ALLOWED_JOB_TYPES_V2:
        return t
    return None


def _canonical_work_mode_v2(raw: str) -> str | None:
    m = (raw or "").strip()
    if m == "Onsite":
        m = "On-site"
    if m in ALLOWED_WORK_MODES_V2:
        return m
    return None


def _lines_to_responsibilities(text: str) -> list[str]:
    out: list[str] = []
    for line in (text or "").splitlines():
        s = line.strip().lstrip("-•*\t ").strip()
        if s:
            out.append(s)
    return out


def _parse_skills_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw = [str(x).strip() for x in value if str(x).strip()]
    else:
        raw = re.split(r"[,;\n]+", str(value))
    seen: set[str] = set()
    out: list[str] = []
    for x in raw:
        s = (x or "").strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out


def _parse_rounds_payload(raw: str) -> list[str]:
    if not (raw or "").strip():
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for item in data:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            name = (item.get("name") or item.get("title") or "").strip()
            if name:
                out.append(name)
    return out


def _validate_application_deadline(deadline_str: str, must_be_future: bool) -> tuple[str | None, str | None]:
    s = (deadline_str or "").strip()
    if not s:
        return None, "Application deadline is required."
    try:
        if len(s) >= 10:
            s = s[:10]
        d = datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None, "Application deadline must be a valid date (YYYY-MM-DD)."
    if must_be_future and d <= datetime.utcnow().date():
        return None, "Application deadline must be a future date."
    return s, None


def _optional_iso_date(s: str) -> str | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        datetime.strptime(s[:10], "%Y-%m-%d")
        return s[:10]
    except ValueError:
        return None


def _save_job_pdf_files(file_list) -> list[dict]:
    out = []
    for file in (file_list or []):
        if not file or not getattr(file, "filename", None):
            continue
        ext = _extract_file_ext(file.filename)
        if ext != "pdf":
            continue
        try:
            file.stream.seek(0, os.SEEK_END)
            size = file.stream.tell()
            file.stream.seek(0)
        except Exception:
            size = None
        if size and size > MAX_DOC_SIZE:
            continue
        uploaded, err = upload_to_cloudinary(
            file,
            "campus/jobs",
            resource_type="raw",
            public_id_prefix="job_attachment",
        )
        if err or not uploaded:
            continue
        out.append(
            {
                "original_name": file.filename,
                "stored_name": uploaded.get("public_id") or file.filename,
                "url": uploaded.get("secure_url"),
                "secure_url": uploaded.get("secure_url"),
                "public_id": uploaded.get("public_id"),
                "size": uploaded.get("bytes") if uploaded.get("bytes") is not None else size,
                "mime_type": "application/pdf",
                "uploaded_at": datetime.utcnow(),
                "folder": uploaded.get("folder") or "campus/jobs",
            }
        )
    return out


def _job_attachment_list(job: dict) -> list[dict]:
    atts = job.get("attachments")
    if isinstance(atts, list) and atts:
        return [a for a in atts if isinstance(a, dict) and a.get("stored_name")]
    legacy = job.get("attachment")
    if isinstance(legacy, dict) and legacy.get("stored_name"):
        return [legacy]
    return []


def _compose_legacy_description(about: str, responsibilities: list[str]) -> str | None:
    parts: list[str] = []
    a = (about or "").strip()
    if a:
        parts.append(a)
    if responsibilities:
        parts.append("Key responsibilities:\n" + "\n".join(f"• {r}" for r in responsibilities))
    if not parts:
        return None
    return "\n\n".join(parts)


def _compose_legacy_requirements(
    required_skills: list[str],
    preferred_skills: list[str],
    min_cgpa,
    batch_year: str | None,
    experience: str | None,
    backlog_criteria: str | None,
    other_requirements: str | None,
    selection_process: str | None,
    rounds: list[str],
    perks: list[str],
    important_criteria_enabled: bool = False,
    important_criteria_text: str | None = None,
) -> str | None:
    chunks: list[str] = []
    if important_criteria_enabled and (important_criteria_text or "").strip():
        chunks.append("Important criteria: " + (important_criteria_text or "").strip())
    if required_skills:
        chunks.append("Required skills: " + ", ".join(required_skills))
    if preferred_skills:
        chunks.append("Preferred skills: " + ", ".join(preferred_skills))
    if min_cgpa is not None:
        chunks.append(f"Minimum CGPA (on 10): {min_cgpa}")
    if batch_year:
        chunks.append(f"Target batch / graduation year: {batch_year}")
    if experience:
        chunks.append(f"Experience: {experience}")
    if backlog_criteria:
        chunks.append(f"Backlog criteria: {backlog_criteria}")
    if other_requirements:
        chunks.append(other_requirements)
    if selection_process:
        chunks.append("Selection process: " + selection_process)
    if rounds:
        chunks.append("Rounds: " + " → ".join(rounds))
    if perks:
        chunks.append("Perks: " + ", ".join(perks))
    if not chunks:
        return None
    return "\n".join(chunks)


def _parse_structured_job_from_request(request, deadline_must_be_future: bool = True) -> tuple[dict | None, list, str | None]:
    """
    Parse form_version=2 job post. Returns (job_fields dict, pdf_file_list, error_message).
    """
    ct = request.content_type or ""
    pdf_files = []
    if "multipart/form-data" in ct:
        form = request.form
        title = (form.get("title") or form.get("role") or "").strip()
        company_name = (form.get("company_name") or "").strip()
        job_type = _canonical_job_type_v2(form.get("job_type") or form.get("type") or "")
        work_mode = _canonical_work_mode_v2(form.get("work_mode") or form.get("mode") or "")
        location = (form.get("location") or "").strip()
        about = (form.get("about") or "").strip()
        responsibilities = _lines_to_responsibilities(form.get("responsibilities") or "")
        required_skills = _parse_skills_list(form.get("required_skills") or "")
        if not required_skills:
            required_skills = _parse_skills_list(form.getlist("required_skills_multi"))
        preferred_skills = _parse_skills_list(form.get("preferred_skills") or "")
        if not preferred_skills:
            preferred_skills = _parse_skills_list(form.getlist("preferred_skills_multi"))

        branches_raw = form.getlist("branches_allowed")
        branches_allowed = [normalize_branch_code(b) for b in branches_raw if normalize_branch_code(b)]
        if not branches_allowed:
            branches_allowed = _parse_branches(form.get("eligible_branches"))

        min_cgpa_raw = (form.get("min_cgpa") or "").strip()
        min_cgpa = None
        if min_cgpa_raw:
            try:
                min_cgpa = float(min_cgpa_raw)
            except ValueError:
                return None, [], "Minimum CGPA must be a number."
            if min_cgpa < 0 or min_cgpa > 10:
                return None, [], "Minimum CGPA must be between 0 and 10."

        batch_year = (form.get("batch_year") or "").strip() or None
        if batch_year and batch_year not in JOB_FORM_BATCH_YEARS:
            return None, [], "Select a valid graduation year."

        experience = (form.get("experience") or "").strip() or None
        backlog_criteria = (form.get("backlog_criteria") or "").strip() or None
        if backlog_criteria and backlog_criteria not in JOB_FORM_BACKLOG_OPTIONS:
            return None, [], "Invalid backlog criteria."

        other_requirements = (form.get("other_requirements") or "").strip() or None
        _ic_raw = form.get("important_criteria_enabled")
        important_criteria_enabled = _ic_raw in ("1", "on", "true", "yes", "True") or _ic_raw is True
        important_criteria_text = (form.get("important_criteria_text") or "").strip()
        if important_criteria_enabled:
            if not important_criteria_text:
                return None, [], "Important criteria text is required when “Mark as Important Job Criteria” is checked."
        else:
            important_criteria_text = None
        salary = (form.get("salary") or "").strip() or None
        perks = [p for p in form.getlist("perks") if p in JOB_FORM_PERK_OPTIONS]
        application_deadline, derr = _validate_application_deadline(
            form.get("application_deadline") or form.get("deadline") or "",
            deadline_must_be_future,
        )
        if derr:
            return None, [], derr
        selection_process = (form.get("selection_process") or "").strip() or None
        rounds = _parse_rounds_payload(form.get("rounds_json") or "")
        joining_date = _optional_iso_date(form.get("joining_date") or "")

        pdf_files = []
        for key in ("attachments", "attachments[]", "pdf_files", "pdf_files[]"):
            pdf_files.extend(request.files.getlist(key))
    else:
        data = request.get_json(silent=True) or {}
        title = (data.get("title") or data.get("role") or "").strip()
        company_name = (data.get("company_name") or "").strip()
        job_type = _canonical_job_type_v2(str(data.get("job_type") or data.get("type") or ""))
        work_mode = _canonical_work_mode_v2(str(data.get("work_mode") or data.get("mode") or ""))
        location = (data.get("location") or "").strip()
        about = (data.get("about") or "").strip()
        responsibilities = data.get("responsibilities") if isinstance(data.get("responsibilities"), list) else _lines_to_responsibilities(str(data.get("responsibilities") or ""))
        required_skills = data.get("required_skills") if isinstance(data.get("required_skills"), list) else _parse_skills_list(data.get("required_skills"))
        preferred_skills = data.get("preferred_skills") if isinstance(data.get("preferred_skills"), list) else _parse_skills_list(data.get("preferred_skills"))
        branches_allowed = [normalize_branch_code(b) for b in (data.get("branches_allowed") or data.get("eligible_branches") or []) if normalize_branch_code(str(b))]
        min_cgpa = data.get("min_cgpa")
        if min_cgpa is not None and min_cgpa != "":
            try:
                min_cgpa = float(min_cgpa)
            except (TypeError, ValueError):
                return None, [], "Minimum CGPA must be a number."
            if min_cgpa < 0 or min_cgpa > 10:
                return None, [], "Minimum CGPA must be between 0 and 10."
        else:
            min_cgpa = None
        batch_year = (str(data.get("batch_year") or "").strip() or None)
        if batch_year and batch_year not in JOB_FORM_BATCH_YEARS:
            return None, [], "Select a valid graduation year."
        experience = (str(data.get("experience") or "").strip() or None)
        backlog_criteria = (str(data.get("backlog_criteria") or "").strip() or None)
        if backlog_criteria and backlog_criteria not in JOB_FORM_BACKLOG_OPTIONS:
            return None, [], "Invalid backlog criteria."
        other_requirements = (str(data.get("other_requirements") or "").strip() or None)
        important_criteria_enabled = bool(data.get("important_criteria_enabled"))
        important_criteria_text = (str(data.get("important_criteria_text") or "").strip())
        if important_criteria_enabled:
            if not important_criteria_text:
                return None, [], "Important criteria text is required when “Mark as Important Job Criteria” is checked."
        else:
            important_criteria_text = None
        salary = (str(data.get("salary") or "").strip() or None)
        perks = [p for p in (data.get("perks") or []) if p in JOB_FORM_PERK_OPTIONS]
        application_deadline, derr = _validate_application_deadline(
            str(data.get("application_deadline") or data.get("deadline") or ""),
            deadline_must_be_future,
        )
        if derr:
            return None, [], derr
        selection_process = (str(data.get("selection_process") or "").strip() or None)
        rounds_val = data.get("rounds")
        if isinstance(rounds_val, list):
            rounds = []
            for item in rounds_val:
                if isinstance(item, str) and item.strip():
                    rounds.append(item.strip())
                elif isinstance(item, dict):
                    nm = (item.get("name") or item.get("title") or "").strip()
                    if nm:
                        rounds.append(nm)
        else:
            rounds = _parse_rounds_payload(str(rounds_val or ""))
        joining_date = _optional_iso_date(str(data.get("joining_date") or ""))

    if not title:
        return None, [], "Job title is required."
    if not company_name:
        return None, [], "Company name is required."
    if not job_type:
        return None, [], "Job type is invalid. Use Full-time, Internship, Part-time, or Project."
    if not work_mode:
        return None, [], "Work mode is invalid. Use On-site, Remote, or Hybrid."
    if not location:
        return None, [], "Location is required (e.g. city and country, or \"Remote\")."
    if not about:
        return None, [], "About the role is required."
    if not responsibilities:
        return None, [], "Add at least one key responsibility (one per line)."
    if not required_skills:
        return None, [], "At least one required skill is needed."
    if not branches_allowed:
        return None, [], "Select at least one eligible branch."

    no_active_backlogs = backlog_criteria == "Not Allowed"

    fields = {
        "title": title,
        "company_name": company_name,
        "job_type": job_type,
        "work_mode": work_mode,
        "location": location,
        "about": about,
        "responsibilities": responsibilities,
        "required_skills": required_skills,
        "preferred_skills": preferred_skills,
        "min_cgpa": min_cgpa,
        "branches_allowed": branches_allowed,
        "batch_year": batch_year,
        "experience": experience,
        "backlog_criteria": backlog_criteria,
        "other_requirements": other_requirements,
        "important_criteria_enabled": important_criteria_enabled,
        "important_criteria_text": important_criteria_text,
        "salary": salary,
        "perks": perks,
        "application_deadline": application_deadline,
        "selection_process": selection_process,
        "rounds": rounds,
        "joining_date": joining_date,
        "no_active_backlogs": no_active_backlogs,
    }
    return fields, pdf_files, None


def _job_doc_from_structured(fields: dict, user: dict, user_role: str, attachments_meta: list[dict]) -> dict:
    title = fields["title"]
    eligible = fields["branches_allowed"]
    deadline = fields["application_deadline"]
    description = _compose_legacy_description(fields["about"], fields["responsibilities"])
    requirements = _compose_legacy_requirements(
        fields["required_skills"],
        fields["preferred_skills"],
        fields["min_cgpa"],
        fields.get("batch_year"),
        fields.get("experience"),
        fields.get("backlog_criteria"),
        fields.get("other_requirements"),
        fields.get("selection_process"),
        fields.get("rounds") or [],
        fields.get("perks") or [],
        bool(fields.get("important_criteria_enabled")),
        fields.get("important_criteria_text"),
    )
    job_doc: dict = {
        "title": title,
        "company_name": fields["company_name"],
        "job_type": fields["job_type"],
        "work_mode": fields["work_mode"],
        "location": fields["location"],
        "about": fields["about"],
        "responsibilities": fields["responsibilities"],
        "required_skills": fields["required_skills"],
        "preferred_skills": fields["preferred_skills"],
        "min_cgpa": fields["min_cgpa"],
        "branches_allowed": eligible,
        "batch_year": fields.get("batch_year"),
        "experience": fields.get("experience"),
        "backlog_criteria": fields.get("backlog_criteria"),
        "other_requirements": fields.get("other_requirements"),
        "important_criteria_enabled": bool(fields.get("important_criteria_enabled")),
        "important_criteria_text": fields.get("important_criteria_text"),
        "salary": fields.get("salary"),
        "perks": fields.get("perks") or [],
        "application_deadline": deadline,
        "selection_process": fields.get("selection_process"),
        "rounds": fields.get("rounds") or [],
        "joining_date": fields.get("joining_date"),
        "attachments": attachments_meta,
        "role": title,
        "type": fields["job_type"],
        "mode": fields["work_mode"],
        "eligible_branches": eligible,
        "deadline": deadline,
        "description": description,
        "requirements": requirements,
        "requiredSkills": fields["required_skills"],
        "no_active_backlogs": bool(fields.get("no_active_backlogs")),
        "noActiveBacklogs": bool(fields.get("no_active_backlogs")),
        "status": "active",
        "created_by_email": user.get("email"),
        "created_by_role": user_role,
        "created_at": datetime.utcnow(),
        "form_version": 2,
    }
    if attachments_meta:
        job_doc["attachment"] = attachments_meta[0]
    return job_doc


def _alumni_job_doc_from_structured(fields: dict, alumni: dict, attachments_meta: list[dict]) -> dict:
    """Persist coordinator-style structured fields on alumni_jobs."""
    description = _compose_legacy_description(fields["about"], fields["responsibilities"])
    requirements = _compose_legacy_requirements(
        fields["required_skills"],
        fields["preferred_skills"],
        fields["min_cgpa"],
        fields.get("batch_year"),
        fields.get("experience"),
        fields.get("backlog_criteria"),
        fields.get("other_requirements"),
        fields.get("selection_process"),
        fields.get("rounds") or [],
        fields.get("perks") or [],
        bool(fields.get("important_criteria_enabled")),
        fields.get("important_criteria_text"),
    )
    eligible = fields["branches_allowed"]
    deadline = fields["application_deadline"]
    doc: dict = {
        "posted_by": alumni["_id"],
        "form_version": 2,
        "title": fields["title"],
        "company": fields["company_name"],
        "company_name": fields["company_name"],
        "location": fields["location"],
        "job_type": fields["job_type"],
        "work_mode": fields["work_mode"],
        "about": fields["about"],
        "responsibilities": fields["responsibilities"],
        "required_skills": fields["required_skills"],
        "preferred_skills": fields["preferred_skills"],
        "min_cgpa": fields["min_cgpa"],
        "branches_allowed": eligible,
        "department_allowed": list(eligible),
        "batch_year": fields.get("batch_year"),
        "experience": fields.get("experience"),
        "backlog_criteria": fields.get("backlog_criteria"),
        "other_requirements": fields.get("other_requirements"),
        "important_criteria_enabled": bool(fields.get("important_criteria_enabled")),
        "important_criteria_text": fields.get("important_criteria_text"),
        "salary": fields.get("salary"),
        "perks": fields.get("perks") or [],
        "application_deadline": deadline,
        "deadline": deadline,
        "selection_process": fields.get("selection_process"),
        "rounds": fields.get("rounds") or [],
        "joining_date": fields.get("joining_date"),
        "attachments": attachments_meta,
        "description": description,
        "eligibility": requirements,
        "no_active_backlogs": bool(fields.get("no_active_backlogs")),
        "created_at": datetime.utcnow(),
    }
    if attachments_meta:
        doc["attachment"] = attachments_meta[0]
    return doc


def _alumni_job_date_input(val) -> str | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date().isoformat()
    s = str(val).strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return s or None


def _alumni_job_to_api_payload(job: dict) -> dict:
    """API shape for alumni job editor (prefill matches coordinator / job-post-form.js)."""
    att_list = _job_attachment_list(job)
    ad = job.get("application_deadline") or job.get("deadline")
    jd = job.get("joining_date")
    branches = list(job.get("branches_allowed") or job.get("department_allowed") or [])
    resp = job.get("responsibilities")
    if not isinstance(resp, list):
        resp = None
    rs = job.get("required_skills")
    if not isinstance(rs, list):
        rs = None
    ps = job.get("preferred_skills")
    if not isinstance(ps, list):
        ps = None
    rounds = job.get("rounds")
    if not isinstance(rounds, list):
        rounds = []
    perks = job.get("perks")
    if not isinstance(perks, list):
        perks = []
    about_val = job.get("about")
    if not (about_val or "").strip():
        about_val = job.get("description")
    return {
        "id": str(job.get("_id")),
        "title": job.get("title") or job.get("role"),
        "role": job.get("title") or job.get("role"),
        "company": job.get("company"),
        "company_name": job.get("company_name") or job.get("company"),
        "location": job.get("location"),
        "job_type": job.get("job_type") or job.get("type"),
        "work_mode": job.get("work_mode") or job.get("mode"),
        "description": job.get("description"),
        "about": about_val,
        "eligibility": job.get("eligibility"),
        "requirements": job.get("eligibility"),
        "department_allowed": list(job.get("department_allowed") or []),
        "created_at": to_utc_iso(job.get("created_at")),
        "form_version": job.get("form_version"),
        "responsibilities": resp,
        "required_skills": rs,
        "preferred_skills": ps,
        "min_cgpa": job.get("min_cgpa"),
        "branches_allowed": branches,
        "batch_year": job.get("batch_year"),
        "experience": job.get("experience"),
        "backlog_criteria": job.get("backlog_criteria"),
        "other_requirements": job.get("other_requirements"),
        "important_criteria_enabled": bool(job.get("important_criteria_enabled")),
        "important_criteria_text": job.get("important_criteria_text"),
        "salary": job.get("salary"),
        "perks": perks,
        "application_deadline": _alumni_job_date_input(ad),
        "deadline": _alumni_job_date_input(ad),
        "selection_process": job.get("selection_process"),
        "rounds": rounds,
        "joining_date": _alumni_job_date_input(jd) if jd else None,
        "attachments": [{"filename": a.get("filename"), "index": i} for i, a in enumerate(att_list)],
        "no_active_backlogs": bool(job.get("no_active_backlogs")),
    }


def _alumni_job_doc_for_placement_engine(job: dict) -> dict:
    """Normalize alumni_jobs Mongo doc for placement_predictor / eligibility (same signals as coordinator posts)."""
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


def _alumni_job_for_student_view(job: dict, viewer: dict | None) -> tuple[dict, dict]:
    """Public-ish job card + apply flags for student alumni job detail page."""
    p = _alumni_job_to_api_payload(job)
    job_view = {
        **p,
        "role": p.get("title"),
        "company_name": p.get("company_name"),
        "type": p.get("job_type"),
        "mode": p.get("work_mode"),
        "deadline": p.get("application_deadline") or p.get("deadline"),
        "application_deadline": p.get("application_deadline") or p.get("deadline"),
        "eligible_branches": list(p.get("branches_allowed") or p.get("department_allowed") or []),
        "description": job.get("description"),
        "requirements": job.get("eligibility"),
    }
    is_student = bool(
        viewer
        and (
            (viewer.get("user_type") or "").lower() == "student"
            or (viewer.get("role") or "").upper() == ROLE_STUDENT
        )
    )
    already = False
    if is_student:
        existing = db["alumni_job_applications"].find_one({"job_id": job["_id"], "student_id": viewer["_id"]})
        already = bool(existing)
    deadline_passed = is_application_deadline_passed(job)
    can_apply = bool(is_student and not already and not deadline_passed)
    reasons: list[str] = []
    if deadline_passed:
        reasons.append(APPLICATION_DEADLINE_PASSED_MSG)
    apply: dict = {
        "can_apply": can_apply,
        "already_applied": already,
        "deadline_passed": deadline_passed,
        "reasons": reasons,
        "application_status": None,
    }
    if already and is_student:
        doc = db["alumni_job_applications"].find_one({"job_id": job["_id"], "student_id": viewer["_id"]})
        apply["application_status"] = (doc.get("status") or "applied").upper() if doc else "APPLIED"
    return job_view, apply


def _normalize_cgpa_to_10(cgpa: float | int | None, scale: int | None) -> float | None:
    if cgpa is None:
        return None
    try:
        value = float(cgpa)
    except Exception:
        return None
    if not scale or scale == 10:
        return value
    if scale == 4:
        return (value / 4.0) * 10.0
    return value


def _normalize_skill_name(name: str) -> str:
    # Lowercase, strip, remove non-alphanumeric so "React.js" ~= "reactjs"
    import re
    s = (name or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def evaluate_job_application_eligibility(job: dict, student: dict, profile_threshold: int = 70, admin_override: bool = False) -> dict:
    """
    Implements strict job eligibility rules. Returns:
    { "canApply": bool, "rejectionReason": str | None }
    """
    if admin_override:
        return {"canApply": True, "rejectionReason": None}

    # 1) Branch eligibility (mandatory)
    eligible_branches = job.get("eligibleBranches") or job.get("eligible_branches") or []
    eligible_branches = [normalize_branch_code(b) for b in eligible_branches if normalize_branch_code(b)]
    student_branch = normalize_branch_code(
        student.get("branch") or student.get("branch_code")
    )
    if eligible_branches and (not student_branch or student_branch not in eligible_branches):
        return {"canApply": False, "rejectionReason": "Branch not eligible"}

    # 2) Backlog rule
    no_active_backlogs = job.get("noActiveBacklogs")
    if no_active_backlogs is True:
        active_backlogs = student.get("activeBacklogs")
        try:
            active_backlogs = int(active_backlogs or 0)
        except Exception:
            active_backlogs = 0
        if active_backlogs != 0:
            return {"canApply": False, "rejectionReason": "Active backlogs present"}

    # 3) CGPA normalization and rule
    min_cgpa = job.get("minCGPA")
    cgpa = student.get("cgpa")
    cgpa_scale = student.get("cgpaScale") or 10
    cgpa_10 = _normalize_cgpa_to_10(cgpa, cgpa_scale)

    if isinstance(min_cgpa, (int, float)):
        # If CGPA is required but missing or below threshold -> reject
        if cgpa_10 is None or cgpa_10 < float(min_cgpa):
            return {"canApply": False, "rejectionReason": "CGPA below requirement"}
    elif isinstance(min_cgpa, str) and min_cgpa.upper() == "NA":
        # Any CGPA acceptable – no CGPA-based rejection
        pass
    else:
        # Skills do not block application (guidance only elsewhere).
        pass

    # 5) Profile completion rule
    try:
        completion = int(
            student.get("profileCompletionPercent")
            if student.get("profileCompletionPercent") is not None
            else student.get("profile_completion") or 0
        )
    except Exception:
        completion = 0
    if completion < int(profile_threshold):
        return {"canApply": False, "rejectionReason": "Profile incomplete"}

    return {"canApply": True, "rejectionReason": None}


def _student_apply_eligibility(student: dict, job: dict):
    """
    Placement eligibility: profile verified, CGPA, department, placement policy.
    Returns (can_apply: bool, reasons: list[str])
    """
    policy = get_active_policy(db)
    st = dict(student)
    st["profile"] = _profile_for_user(student)
    return check_placement_eligibility(st, job, policy)


# ---------- Applications (job applications) ----------
APPLICATION_STATUS_APPLIED = "APPLIED"
APPLICATION_STATUS_SHORTLISTED = "SHORTLISTED"
APPLICATION_STATUS_REJECTED = "REJECTED"


@app.route("/jobs")
@login_required
def jobs_page():
    return send_from_directory(app.static_folder, "jobs.html")


@app.route("/jobs/past")
@login_required
def jobs_past_page():
    """Past (deadline passed) jobs — same shell as /jobs, detected via pathname in jobs.html."""
    return send_from_directory(app.static_folder, "jobs.html")


@app.route("/job-applicants")
def job_applicants_standalone_page():
    """Alumni/coordinator: applicants list in a new tab (JWT in localStorage)."""
    return send_from_directory(app.static_folder, "job_applicants.html")


@app.route("/applications")
@login_required
@role_required("STUDENT")
def student_applications_page():
    """Student: jobs they have applied to (coordinator job_posts applications)."""
    return send_from_directory(app.static_folder, "student_applications.html")


@app.route("/jobs/create")
@login_required
@role_required("ADMIN", "COORDINATOR")
def jobs_create_page():
    # Redirect coordinators to their specific page with proper navigation
    user = get_logged_in_user()
    if user and (user.get("role") or "").upper() == ROLE_COORDINATOR:
        edit_id = request.args.get("edit")
        if edit_id:
            return redirect(f"/coordinator/jobs/create?edit={edit_id}")
        return redirect("/coordinator/jobs/create")
    return send_from_directory(app.static_folder, "job_create.html")


@app.route("/jobs/<job_id>")
@login_required
def job_detail_page(job_id):
    return send_from_directory(app.static_folder, "job_detail.html")


@app.route("/alumni-jobs/<job_id>")
@login_required
def alumni_job_detail_page(job_id):
    return send_from_directory(app.static_folder, "alumni_job_detail.html")


@app.route("/alumni-jobs/<job_id>/attachment")
@login_required
def alumni_job_attachment_download(job_id):
    return jsonify({"error": "Job attachments are temporarily disabled."}), 400


@app.route("/jobs/<job_id>/edit")
@login_required
@role_required("ADMIN", "COORDINATOR")
def job_edit_page(job_id):
    # Redirect to create page with edit parameter
    return redirect(f"/jobs/create?edit={job_id}")


@app.route("/jobs/<job_id>/attachment")
@login_required
def job_attachment(job_id):
    return jsonify({"error": "Job attachments are temporarily disabled."}), 400


@app.route("/api/jobs", methods=["GET", "POST"])
@login_required
def api_jobs():
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    if request.method == "GET":
        items = []
        for doc in db["job_posts"].find({"status": "active"}).sort("created_at", -1):
            items.append({
                "id": str(doc.get("_id")),
                "source": "coordinator",
                "company_name": doc.get("company_name"),
                "role": doc.get("role"),
                "type": doc.get("type"),
                "mode": doc.get("mode"),
                "eligible_branches": doc.get("eligible_branches") or [],
                "deadline": doc.get("deadline"),
                "application_deadline": doc.get("application_deadline") or doc.get("deadline"),
                "deadline_ends_at": application_deadline_end_utc_iso(doc),
                "deadline_passed": is_application_deadline_passed(doc),
                "created_at": doc.get("created_at").isoformat() if isinstance(doc.get("created_at"), datetime) else None,
            })
        alumni_items = []
        for doc in db["alumni_jobs"].find().sort("created_at", -1):
            alumni_items.append({
                "id": str(doc.get("_id")),
                "source": "alumni",
                "company_name": doc.get("company_name") or doc.get("company"),
                "role": doc.get("title") or doc.get("role"),
                "type": doc.get("job_type") or doc.get("type"),
                "mode": doc.get("work_mode") or doc.get("mode"),
                "location": doc.get("location"),
                "eligible_branches": list(doc.get("branches_allowed") or doc.get("department_allowed") or []),
                "deadline": doc.get("deadline") or doc.get("application_deadline"),
                "application_deadline": doc.get("application_deadline") or doc.get("deadline"),
                "deadline_ends_at": application_deadline_end_utc_iso(doc),
                "deadline_passed": is_application_deadline_passed(doc),
                "created_at": doc.get("created_at").isoformat() if isinstance(doc.get("created_at"), datetime) else None,
            })
        return jsonify({"items": items, "alumni_items": alumni_items}), 200

    # POST create job (ADMIN/COORDINATOR only)
    user_role = (user.get("role") or "").upper() or derive_role_from_existing_user_type(user.get("user_type"))
    if user_role not in {ROLE_ADMIN, ROLE_COORDINATOR}:
        return jsonify({"error": "Forbidden"}), 403

    content_type = request.content_type or ""
    if "multipart/form-data" in content_type:
        is_structured_v2 = request.form.get("form_version") == "2"
    else:
        _fj = request.get_json(silent=True) or {}
        is_structured_v2 = _fj.get("form_version") == 2

    if is_structured_v2:
        fields, pdf_files, parse_err = _parse_structured_job_from_request(request)
        if parse_err:
            return jsonify({"error": parse_err}), 400
        attachments_meta = _save_job_pdf_files(pdf_files)
        job_doc = _job_doc_from_structured(fields, user, user_role, attachments_meta)
        ins = db["job_posts"].insert_one(job_doc)
        try:
            job_nid = ins.inserted_id
            eligible = set(fields["branches_allowed"])
            role_line = fields["title"]
            comp = fields["company_name"]
            student_query: dict = {"user_type": "student"}
            if eligible:
                student_query["$or"] = [{"branch_code": {"$in": list(eligible)}}, {"branch": {"$in": list(eligible)}}]
            for st in db["users"].find(student_query, projection={"_id": 1, "first_name": 1, "branch_code": 1}):
                create_notification(
                    st["_id"],
                    f"New job posted: {role_line} at {comp}.",
                    notification_type="job",
                    reference_id=job_nid,
                    reference_type="job"
                )
        except Exception:
            pass
        return jsonify({"message": "Job created.", "id": str(ins.inserted_id)}), 201

    # Legacy: JSON or multipart without form_version=2
    if "multipart/form-data" in content_type:
        form = request.form
        company_name = (form.get("company_name") or "").strip()
        role = (form.get("role") or "").strip()
        job_type = (form.get("type") or "").strip()
        mode = (form.get("mode") or "").strip()
        location = (form.get("location") or "").strip()
        description = (form.get("description") or "").strip()
        requirements = (form.get("requirements") or "").strip()
        salary = (form.get("salary") or "").strip()
        deadline = (form.get("deadline") or "").strip()
        eligible_branches = _parse_branches(form.get("eligible_branches"))
        attachment_file = None
    else:
        data = request.get_json(silent=True) or {}
        company_name = (data.get("company_name") or "").strip()
        role = (data.get("role") or "").strip()
        job_type = (data.get("type") or "").strip()
        mode = (data.get("mode") or "").strip()
        location = (data.get("location") or "").strip()
        description = (data.get("description") or "").strip()
        requirements = (data.get("requirements") or "").strip()
        salary = (data.get("salary") or "").strip()
        deadline = (data.get("deadline") or "").strip()
        eligible_branches = _parse_branches(data.get("eligible_branches"))
        attachment_file = None

    if not company_name or not role or not job_type or not mode or not deadline:
        return jsonify({"error": "company_name, role, type, mode, and deadline are required."}), 400

    if job_type not in {"Internship", "Full-Time"}:
        return jsonify({"error": "type must be Internship or Full-Time."}), 400

    job_doc = {
        "company_name": company_name,
        "role": role,
        "type": job_type,
        "mode": mode,
        "location": location or None,
        "eligible_branches": eligible_branches,
        "description": description or None,
        "requirements": requirements or None,
        "salary": salary or None,
        "deadline": deadline,
        "status": "active",
        "created_by_email": user.get("email"),
        "created_by_role": user_role,
        "created_at": datetime.utcnow(),
    }

    if attachment_file and attachment_file.filename:
        return jsonify({"error": "Job attachment uploads are temporarily disabled."}), 400

    ins = db["job_posts"].insert_one(job_doc)

    try:
        job_id = ins.inserted_id
        eligible = set(eligible_branches)
        student_query: dict = {"user_type": "student"}
        if eligible:
            student_query["$or"] = [{"branch_code": {"$in": list(eligible)}}, {"branch": {"$in": list(eligible)}}]
        for st in db["users"].find(student_query, projection={"_id": 1, "first_name": 1, "branch_code": 1}):
            create_notification(
                st["_id"],
                f"New job posted: {role} at {company_name}.",
                notification_type="job",
                reference_id=job_id,
                reference_type="job"
            )
    except Exception:
        pass

    return jsonify({"message": "Job created.", "id": str(ins.inserted_id)}), 201


@app.route("/api/jobs/<job_id>", methods=["GET", "PUT", "DELETE"])
@login_required
def api_job_detail(job_id):
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    try:
        oid = ObjectId(job_id)
    except Exception:
        return jsonify({"error": "Invalid job id"}), 400

    coll = db["job_posts"]
    doc = coll.find_one({"_id": oid})
    if not doc:
        return jsonify({"error": "Job not found"}), 404

    user_role = (user.get("role") or "").upper() or derive_role_from_existing_user_type(user.get("user_type"))
    can_manage = user_role in {ROLE_ADMIN, ROLE_COORDINATOR} and (
        user_role == ROLE_ADMIN or user.get("email") == doc.get("created_by_email")
    )

    if request.method == "PUT":
        if not can_manage:
            return jsonify({"error": "Forbidden"}), 403
        content_type = request.content_type or ""
        if "multipart/form-data" in content_type:
            is_structured_v2 = request.form.get("form_version") == "2"
        else:
            _fj = request.get_json(silent=True) or {}
            is_structured_v2 = _fj.get("form_version") == 2

        if is_structured_v2:
            fields, pdf_files, parse_err = _parse_structured_job_from_request(request, deadline_must_be_future=False)
            if parse_err:
                return jsonify({"error": parse_err}), 400
            existing_atts = _job_attachment_list(doc)
            new_saved = _save_job_pdf_files(pdf_files)
            attachments_meta = (existing_atts + new_saved) if new_saved else existing_atts
            if len(attachments_meta) > MAX_JOB_PDF_ATTACHMENTS:
                attachments_meta = attachments_meta[:MAX_JOB_PDF_ATTACHMENTS]
            base = _job_doc_from_structured(fields, user, user_role, attachments_meta)
            update_fields = {k: v for k, v in base.items() if k not in {"created_at", "created_by_email", "created_by_role"}}
            if not attachments_meta:
                update_fields["attachments"] = []
                update_fields["attachment"] = None
            coll.update_one({"_id": oid}, {"$set": update_fields})
            return jsonify({"message": "Job updated."}), 200

        if "multipart/form-data" in content_type:
            form = request.form
            company_name = (form.get("company_name") or "").strip()
            role_name = (form.get("role") or "").strip()
            job_type = (form.get("type") or "").strip()
            mode = (form.get("mode") or "").strip()
            location = (form.get("location") or "").strip()
            description = (form.get("description") or "").strip()
            requirements = (form.get("requirements") or "").strip()
            salary = (form.get("salary") or "").strip()
            deadline = (form.get("deadline") or "").strip()
            eligible_branches = _parse_branches(form.get("eligible_branches"))
            attachment_file = None
        else:
            data = request.get_json(silent=True) or {}
            company_name = (data.get("company_name") or "").strip()
            role_name = (data.get("role") or "").strip()
            job_type = (data.get("type") or "").strip()
            mode = (data.get("mode") or "").strip()
            location = (data.get("location") or "").strip()
            description = (data.get("description") or "").strip()
            requirements = (data.get("requirements") or "").strip()
            salary = (data.get("salary") or "").strip()
            deadline = (data.get("deadline") or "").strip()
            eligible_branches = _parse_branches(data.get("eligible_branches"))
            attachment_file = None

        if not company_name or not role_name or not job_type or not mode or not deadline:
            return jsonify({"error": "company_name, role, type, mode, and deadline are required."}), 400
        if job_type not in {"Internship", "Full-Time"}:
            return jsonify({"error": "type must be Internship or Full-Time."}), 400

        update_fields = {
            "company_name": company_name,
            "role": role_name,
            "type": job_type,
            "mode": mode,
            "location": location or None,
            "eligible_branches": eligible_branches,
            "description": description or None,
            "requirements": requirements or None,
            "salary": salary or None,
            "deadline": deadline,
        }

        if attachment_file and attachment_file.filename:
            return jsonify({"error": "Job attachment uploads are temporarily disabled."}), 400

        coll.update_one({"_id": oid}, {"$set": update_fields})
        return jsonify({"message": "Job updated."}), 200

    if request.method == "DELETE":
        if not can_manage:
            return jsonify({"error": "Forbidden"}), 403
        # Remove the job and any linked student applications so it disappears
        # from job feeds, application lists, faculty views, and coordinator views.
        db["applications"].delete_many({"job_id": oid})
        coll.delete_one({"_id": oid})
        return jsonify({"message": "Job deleted."}), 200

    # GET
    att_list = _job_attachment_list(doc)
    job = {
        "id": str(doc.get("_id")),
        "company_name": doc.get("company_name"),
        "role": doc.get("role"),
        "type": doc.get("type"),
        "mode": doc.get("mode"),
        "location": doc.get("location"),
        "eligible_branches": doc.get("eligible_branches") or [],
        "description": doc.get("description"),
        "requirements": doc.get("requirements"),
        "salary": doc.get("salary"),
        "deadline": doc.get("deadline"),
        "status": doc.get("status"),
        "created_at": doc.get("created_at").isoformat() if isinstance(doc.get("created_at"), datetime) else None,
        "attachment": {
            "filename": (doc.get("attachment") or {}).get("filename"),
            "has_attachment": bool(att_list),
        },
        "attachments": [
            {"filename": a.get("filename"), "index": i} for i, a in enumerate(att_list)
        ],
        "form_version": doc.get("form_version"),
        "title": doc.get("title") or doc.get("role"),
        "job_type": doc.get("job_type") or doc.get("type"),
        "work_mode": doc.get("work_mode") or doc.get("mode"),
        "about": doc.get("about"),
        "responsibilities": doc.get("responsibilities") if isinstance(doc.get("responsibilities"), list) else None,
        "required_skills": doc.get("required_skills") if isinstance(doc.get("required_skills"), list) else None,
        "preferred_skills": doc.get("preferred_skills") if isinstance(doc.get("preferred_skills"), list) else None,
        "min_cgpa": doc.get("min_cgpa"),
        "branches_allowed": doc.get("branches_allowed") or doc.get("eligible_branches") or [],
        "batch_year": doc.get("batch_year"),
        "experience": doc.get("experience"),
        "backlog_criteria": doc.get("backlog_criteria"),
        "other_requirements": doc.get("other_requirements"),
        "important_criteria_enabled": bool(doc.get("important_criteria_enabled")),
        "important_criteria_text": doc.get("important_criteria_text"),
        "perks": doc.get("perks") if isinstance(doc.get("perks"), list) else [],
        "application_deadline": doc.get("application_deadline") or doc.get("deadline"),
        "deadline_ends_at": application_deadline_end_utc_iso(doc),
        "deadline_passed": is_application_deadline_passed(doc),
        "selection_process": doc.get("selection_process"),
        "rounds": doc.get("rounds") if isinstance(doc.get("rounds"), list) else [],
        "joining_date": doc.get("joining_date"),
    }

    can_apply = False
    reasons = []
    already_applied = False
    application_status = None
    skill_suggestions: list = []
    if user_role == ROLE_STUDENT:
        can_apply, reasons = _student_apply_eligibility(user, doc)
        st_view = dict(user)
        st_view["profile"] = _profile_for_user(user)
        if can_apply:
            skill_suggestions = compute_missing_required_skills_suggestions(st_view, doc)
        # Check duplicate application
        existing = db["applications"].find_one({
            "student_id": user["_id"],
            "job_id": oid,
        })
        if existing:
            already_applied = True
            application_status = existing.get("status")
            can_apply = False
            skill_suggestions = []

    return jsonify({
        "job": job,
        "apply": {
            "can_apply": can_apply,
            "reasons": reasons,
            "already_applied": already_applied,
            "application_status": application_status,
            "deadline_passed": is_application_deadline_passed(doc),
            "skill_suggestions": skill_suggestions,
        },
        "manage": {
            "can_edit": can_manage,
        },
    }), 200


@app.route("/api/jobs/<job_id>/apply", methods=["POST"])
@login_required
@role_required("STUDENT")
def api_job_apply(job_id):
    student = get_logged_in_user()
    if not student:
        return jsonify({"error": "Not authenticated"}), 401

    try:
        oid = ObjectId(job_id)
    except Exception:
        return jsonify({"error": "Invalid job id"}), 400

    job = db["job_posts"].find_one({"_id": oid, "status": "active"})
    if not job:
        return jsonify({"error": "Job not found or inactive"}), 404

    # Duplicate check
    existing = db["applications"].find_one({
        "student_id": student["_id"],
        "job_id": oid,
    })
    if existing:
        return jsonify({
            "message": "Already applied.",
            "status": existing.get("status") or APPLICATION_STATUS_APPLIED,
        }), 200

    if is_application_deadline_passed(job):
        return jsonify({
            "error": APPLICATION_DEADLINE_PASSED_MSG,
            "reasons": [APPLICATION_DEADLINE_PASSED_MSG],
        }), 400

    can_apply, reasons = _student_apply_eligibility(student, job)
    if not can_apply:
        return jsonify({"error": "Not eligible for this job.", "reasons": reasons}), 400

    result = db["applications"].insert_one({
        "student_id": student["_id"],
        "job_id": oid,
        "status": APPLICATION_STATUS_APPLIED,
        "applied_at": datetime.utcnow(),
    })

    # Track activity for job application
    create_activity(
        student["_id"],
        ACTIVITY_TYPE_APPLICATION,
        oid,
        "job",
        {
            "company": job.get("company_name"),
            "role": job.get("role"),
            "status": APPLICATION_STATUS_APPLIED
        }
    )

    # Notification for successful application
    create_notification(
        student["_id"],
        f"Your application to {job.get('role') or 'a role'} at {job.get('company_name') or 'company'} has been submitted.",
        notification_type="application",
        reference_id=oid,
        reference_type="job"
    )

    return jsonify({"message": "Application submitted.", "status": APPLICATION_STATUS_APPLIED}), 201


@app.route("/api/student/predict-placement", methods=["GET"])
@login_required
@role_required("STUDENT")
def api_student_predict_placement():
    """Return placement prediction for the current student (optionally for a specific job)."""
    student = get_logged_in_user()
    if not student:
        return jsonify({"error": "Not authenticated"}), 401
    student_with_profile = dict(student)
    student_with_profile["profile"] = _profile_for_user(student)
    job_id = request.args.get("job_id")
    job = None
    if job_id:
        try:
            job_oid = ObjectId(job_id)
            job = db["job_posts"].find_one({"_id": job_oid, "status": "active"})
            if not job:
                aj = db["alumni_jobs"].find_one({"_id": job_oid})
                if aj:
                    job = _alumni_job_doc_for_placement_engine(aj)
        except Exception:
            pass
    result = predict_placement(student_with_profile, job)
    if result.get("error"):
        return jsonify(result), 400
    return jsonify(result), 200


@app.route("/api/student/suitable-jobs", methods=["GET"])
@login_required
@role_required("STUDENT")
def api_student_suitable_jobs():
    """Return active jobs with eligibility: can_apply, already_applied, or reasons to improve."""
    student = get_logged_in_user()
    if not student:
        return jsonify({"error": "Not authenticated"}), 401
    student_with_profile = dict(student)
    student_with_profile["profile"] = _profile_for_user(student)
    limit = min(50, int(request.args.get("limit", 30)))
    coord_cursor = db["job_posts"].find({"status": "active"}).sort("created_at", -1).limit(limit)
    alumni_cursor = db["alumni_jobs"].find({}).sort("created_at", -1).limit(limit)
    applied_job_ids = set()
    for doc in db["applications"].find(
        {"student_id": student["_id"]},
        projection={"job_id": 1}
    ):
        jid = doc.get("job_id")
        if jid:
            applied_job_ids.add(jid)
    applied_alumni_job_ids = set()
    for doc in db["alumni_job_applications"].find(
        {"student_id": student["_id"]},
        projection={"job_id": 1}
    ):
        jid = doc.get("job_id")
        if jid:
            applied_alumni_job_ids.add(jid)

    def _ts(doc):
        c = doc.get("created_at")
        return c if isinstance(c, datetime) else datetime.min

    coord_docs = list(coord_cursor)
    alumni_docs = list(alumni_cursor)
    merged: list[tuple[str, dict]] = [("coordinator", d) for d in coord_docs] + [("alumni", d) for d in alumni_docs]
    merged.sort(key=lambda x: _ts(x[1]), reverse=True)
    merged = merged[:limit]

    items = []
    for source, doc in merged:
        job_id = doc.get("_id")
        if source == "coordinator":
            already_applied = job_id in applied_job_ids
            can_apply, reasons = _student_apply_eligibility(student_with_profile, doc)
            skill_sug = (
                compute_missing_required_skills_suggestions(student_with_profile, doc)
                if can_apply
                else []
            )
            items.append({
                "id": str(job_id),
                "source": "coordinator",
                "company_name": doc.get("company_name"),
                "role": doc.get("role"),
                "type": doc.get("type"),
                "mode": doc.get("mode"),
                "salary": doc.get("salary"),
                "deadline": doc.get("deadline"),
                "application_deadline": doc.get("application_deadline") or doc.get("deadline"),
                "deadline_ends_at": application_deadline_end_utc_iso(doc),
                "deadline_passed": is_application_deadline_passed(doc),
                "eligible_branches": doc.get("eligible_branches") or [],
                "can_apply": can_apply and not already_applied,
                "already_applied": already_applied,
                "reasons": reasons if not can_apply else [],
                "skill_suggestions": skill_sug,
            })
        else:
            already_applied = job_id in applied_alumni_job_ids
            deadline_passed = is_application_deadline_passed(doc)
            if already_applied:
                can_apply = False
                reasons: list[str] = []
            elif deadline_passed:
                can_apply = False
                reasons = [APPLICATION_DEADLINE_PASSED_MSG]
            else:
                can_apply = True
                reasons = []
            pred_doc = _alumni_job_doc_for_placement_engine(doc)
            skill_sug = (
                compute_missing_required_skills_suggestions(student_with_profile, pred_doc)
                if can_apply
                else []
            )
            items.append({
                "id": str(job_id),
                "source": "alumni",
                "company_name": doc.get("company_name") or doc.get("company"),
                "role": doc.get("title") or doc.get("role"),
                "type": doc.get("job_type") or doc.get("type"),
                "mode": doc.get("work_mode") or doc.get("mode"),
                "salary": doc.get("salary"),
                "deadline": doc.get("deadline") or doc.get("application_deadline"),
                "application_deadline": doc.get("application_deadline") or doc.get("deadline"),
                "deadline_ends_at": application_deadline_end_utc_iso(doc),
                "deadline_passed": deadline_passed,
                "eligible_branches": list(doc.get("branches_allowed") or doc.get("department_allowed") or []),
                "can_apply": can_apply and not already_applied,
                "already_applied": already_applied,
                "reasons": reasons if not can_apply else [],
                "skill_suggestions": skill_sug,
            })
    return jsonify({"items": items}), 200


@app.route("/api/student/suggested-jobs", methods=["GET"])
@login_required
@role_required("STUDENT")
def api_student_suggested_jobs():
    """
    Jobs with weighted match_score >= min_score (default 50), sorted best-first.
    Each item includes eligibility (strict rules), apply_eligible (false if already applied or ineligible),
    and already_applied for coordinator vs alumni job application records.
    Omit limit (or limit=0) to return all qualifying jobs within max_scan (default 500, max 1000).
    Cached briefly; invalidated when jobs, profile, or this student's applications change.
    """
    student = get_logged_in_user()
    if not student:
        return jsonify({"error": "Not authenticated"}), 401
    profile = _profile_for_user(student)
    try:
        min_score = float(request.args.get("min_score", 50))
    except (TypeError, ValueError):
        min_score = 50.0
    min_score = max(0.0, min(100.0, min_score))
    limit_raw = request.args.get("limit")
    limit = None
    if limit_raw is not None and str(limit_raw).strip() != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = None
        if limit is not None and limit <= 0:
            limit = None
        elif limit is not None:
            limit = max(1, min(500, limit))
    try:
        max_scan = int(request.args.get("max_scan", 500))
    except (TypeError, ValueError):
        max_scan = 500
    max_scan = max(1, min(1000, max_scan))

    from services.suggested_jobs import get_suggested_jobs_cached

    items, _, _ = get_suggested_jobs_cached(
        db,
        student,
        profile,
        min_score=min_score,
        limit=limit,
        max_scan=max_scan,
    )
    return jsonify(
        {
            "items": items,
            "min_score": min_score,
            "limit": limit,
            "max_scan": max_scan,
        }
    ), 200


@app.route("/api/student/applications", methods=["GET"])
@login_required
@role_required("STUDENT")
def api_student_applications():
    student = get_logged_in_user()
    if not student:
        return jsonify({"error": "Not authenticated"}), 401

    apps = []
    cursor = db["applications"].find({"student_id": student["_id"]}).sort("applied_at", -1)
    job_ids = []
    for doc in cursor:
        job_id = doc.get("job_id")
        if job_id:
            job_ids.append(job_id)
        apps.append(doc)

    jobs_by_id = {}
    if job_ids:
        for j in db["job_posts"].find({"_id": {"$in": job_ids}}):
            jobs_by_id[j["_id"]] = j

    items: list[dict] = []
    for a in apps:
        j = jobs_by_id.get(a.get("job_id")) or {}
        if not j:
            continue
        role_or_title = (j.get("title") or j.get("role")) if j else None
        applied = a.get("applied_at")
        items.append({
            "id": str(a.get("_id")),
            "job_source": "coordinator",
            "job_id": str(a.get("job_id")) if a.get("job_id") else None,
            "job_company": j.get("company_name") if j else None,
            "job_role": role_or_title,
            "job_title": role_or_title,
            "job_type": j.get("job_type") or j.get("type") if j else None,
            "job_mode": j.get("work_mode") or j.get("mode") if j else None,
            "job_listed": bool(j),
            "status": a.get("status") or APPLICATION_STATUS_APPLIED,
            "applied_at": applied.isoformat() if isinstance(applied, datetime) else None,
            "_sort_at": applied if isinstance(applied, datetime) else datetime.min,
        })

    alumni_apps = list(
        db["alumni_job_applications"].find({"student_id": student["_id"]}).sort("applied_at", -1)
    )
    alumni_job_ids = [x.get("job_id") for x in alumni_apps if x.get("job_id")]
    alumni_jobs_by_id: dict = {}
    if alumni_job_ids:
        for j in db["alumni_jobs"].find({"_id": {"$in": alumni_job_ids}}):
            alumni_jobs_by_id[j["_id"]] = j

    for a in alumni_apps:
        jid = a.get("job_id")
        j = alumni_jobs_by_id.get(jid) or {}
        if not j:
            continue
        role_or_title = (j.get("title") or j.get("role")) if j else None
        st = a.get("status") or APPLICATION_STATUS_APPLIED
        if isinstance(st, str):
            st = st.strip().upper()
        applied = a.get("applied_at")
        items.append({
            "id": str(a.get("_id")),
            "job_source": "alumni",
            "job_id": str(jid) if jid else None,
            "job_company": (j.get("company_name") or j.get("company")) if j else None,
            "job_role": role_or_title,
            "job_title": role_or_title,
            "job_type": j.get("job_type") or j.get("type") if j else None,
            "job_mode": j.get("work_mode") or j.get("mode") if j else None,
            "job_listed": bool(j),
            "status": st,
            "applied_at": applied.isoformat() if isinstance(applied, datetime) else None,
            "_sort_at": applied if isinstance(applied, datetime) else datetime.min,
        })

    items.sort(key=lambda x: x.get("_sort_at") or datetime.min, reverse=True)
    for it in items:
        it.pop("_sort_at", None)

    return jsonify({"items": items}), 200


MAX_ALUMNI_MENTEES = 5


@app.route("/request-mentorship/<alumni_id>", methods=["POST"])
@login_required
def api_request_mentorship(alumni_id):
    """
    Student requests mentorship from an alumni.
    Validates: user is student, student has no mentor, alumni has < 5 mentees, no duplicate pending request.
    """
    student = get_logged_in_user()
    if not student:
        return jsonify({"error": "Not authenticated"}), 401
    if (student.get("user_type") or "").strip().lower() != "student":
        return jsonify({"error": "Only students can request mentorship"}), 403
    if student.get("mentor_id") is not None:
        return jsonify({"error": "You already have a mentor. Cancel current mentorship to request another."}), 400
    try:
        alumni_oid = ObjectId(alumni_id)
    except Exception:
        return jsonify({"error": "Invalid alumni id"}), 400
    alumni = db["users"].find_one({"_id": alumni_oid, "user_type": "alumni"})
    if not alumni:
        return jsonify({"error": "Alumni not found"}), 404
    mentorship_settings = (alumni.get("alumni_settings") or {}).get("mentorship") or {}
    if mentorship_settings.get("allow_mentorship_requests") is False:
        return jsonify({"error": "This alumni is not accepting mentorship requests at the moment."}), 403
    mentees = alumni.get("mentees") or []
    if len(mentees) >= MAX_ALUMNI_MENTEES:
        return jsonify({"error": "Mentee slots are full."}), 400
    existing = db["mentoring_requests"].find_one({
        "student_id": student["_id"],
        "alumni_id": alumni_oid,
        "status": "pending",
    })
    if existing:
        return jsonify({"error": "You already have a pending request with this alumni."}), 400
    now = datetime.utcnow()
    doc = {
        "student_id": student["_id"],
        "alumni_id": alumni_oid,
        "status": "pending",
        "timestamp": now,
        "created_at": now,
    }
    ins = db["mentoring_requests"].insert_one(doc)
    return jsonify({"message": "Mentorship request sent.", "id": str(ins.inserted_id)}), 201


@app.route("/api/student/mentorship-request", methods=["POST"])
@login_required
@role_required("STUDENT")
def api_student_mentorship_request():
    """Legacy: Student sends mentorship request (use POST /request-mentorship/<alumni_id> for new flow)."""
    data = request.get_json(silent=True) or {}
    alumni_id_raw = data.get("alumni_id")
    if not alumni_id_raw:
        return jsonify({"error": "alumni_id is required"}), 400
    return api_request_mentorship(alumni_id_raw)


@app.route("/api/student/referral-request", methods=["POST"])
@login_required
@role_required("STUDENT")
def api_student_referral_request():
    """Student requests a referral from an alumni (optionally for a specific job)."""
    student = get_logged_in_user()
    if not student:
        return jsonify({"error": "Not authenticated"}), 401
    data = request.get_json(silent=True) or {}
    alumni_id_raw = data.get("alumni_id")
    if not alumni_id_raw:
        return jsonify({"error": "alumni_id is required"}), 400
    try:
        alumni_oid = ObjectId(alumni_id_raw)
    except Exception:
        return jsonify({"error": "Invalid alumni_id"}), 400
    alumni = db["users"].find_one({"_id": alumni_oid, "user_type": "alumni"})
    if not alumni:
        return jsonify({"error": "Alumni not found"}), 404
    mentorship_settings = (alumni.get("alumni_settings") or {}).get("mentorship") or {}
    if mentorship_settings.get("allow_contact_for_guidance") is False:
        return jsonify({"error": "This alumni is not accepting contact requests at the moment."}), 403
    job_id_raw = data.get("job_id")
    job_oid = None
    if job_id_raw:
        try:
            job_oid = ObjectId(job_id_raw)
            job = db["alumni_jobs"].find_one({"_id": job_oid, "posted_by": alumni_oid})
            if not job:
                return jsonify({"error": "Job not found or not posted by this alumni"}), 404
        except Exception:
            return jsonify({"error": "Invalid job_id"}), 400
    doc = {
        "student_id": student["_id"],
        "alumni_id": alumni_oid,
        "job_id": job_oid,
        "status": "pending",
        "referral_note": None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    ins = db["referral_requests"].insert_one(doc)
    return jsonify({"message": "Referral request sent.", "id": str(ins.inserted_id)}), 201


@app.route("/api/student/alumni-job-apply", methods=["POST"])
@login_required
@role_required("STUDENT")
def api_student_alumni_job_apply():
    """Student applies to an alumni-posted job."""
    student = get_logged_in_user()
    if not student:
        return jsonify({"error": "Not authenticated"}), 401
    data = request.get_json(silent=True) or {}
    job_id_raw = data.get("job_id")
    if not job_id_raw:
        return jsonify({"error": "job_id is required"}), 400
    try:
        job_oid = ObjectId(job_id_raw)
    except Exception:
        return jsonify({"error": "Invalid job_id"}), 400
    job = db["alumni_jobs"].find_one({"_id": job_oid})
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if is_application_deadline_passed(job):
        return jsonify({"error": APPLICATION_DEADLINE_PASSED_MSG}), 400
    existing = db["alumni_job_applications"].find_one({"job_id": job_oid, "student_id": student["_id"]})
    if existing:
        return jsonify({"error": "You have already applied to this job"}), 400
    message = (data.get("message") or "").strip() or None
    doc = {
        "job_id": job_oid,
        "student_id": student["_id"],
        "message": message,
        "applied_at": datetime.utcnow(),
    }
    ins = db["alumni_job_applications"].insert_one(doc)
    return jsonify({"message": "Application submitted.", "id": str(ins.inserted_id)}), 201


@app.route("/api/student/alumni-jobs/<job_id>", methods=["GET"])
@login_required
def api_student_alumni_job_get(job_id):
    """Student (or any logged-in user) views an alumni-posted job."""
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        oid = ObjectId(job_id)
    except Exception:
        return jsonify({"error": "Invalid job id"}), 400
    job = db["alumni_jobs"].find_one({"_id": oid})
    if not job:
        return jsonify({"error": "Job not found"}), 404
    job_view, apply_dict = _alumni_job_for_student_view(job, user)
    poster = db["users"].find_one({"_id": job.get("posted_by")}) if job.get("posted_by") else None
    poster_name = ""
    if poster:
        poster_name = f"{poster.get('first_name', '')} {poster.get('last_name', '')}".strip()
    job_view["posted_by_name"] = poster_name or None
    return jsonify({"job": job_view, "apply": apply_dict}), 200


@app.route("/api/jobs/<job_id>/applications/<app_id>/status", methods=["POST"])
@login_required
@role_required("ADMIN", "COORDINATOR")
def api_update_application_status(job_id, app_id):
    """
    Update application status to SHORTLISTED or REJECTED by admin/coordinator
    and notify the student about the change.
    """
    try:
        job_oid = ObjectId(job_id)
        app_oid = ObjectId(app_id)
    except Exception:
        return jsonify({"error": "Invalid id"}), 400

    app_doc = db["applications"].find_one({"_id": app_oid, "job_id": job_oid})
    if not app_doc:
        return jsonify({"error": "Application not found"}), 404

    data = request.get_json(silent=True) or {}
    status = (data.get("status") or "").strip().upper()
    if status not in {APPLICATION_STATUS_SHORTLISTED, APPLICATION_STATUS_REJECTED}:
        return jsonify({"error": "status must be SHORTLISTED or REJECTED"}), 400

    db["applications"].update_one(
        {"_id": app_doc["_id"]},
        {"$set": {"status": status}}
    )

    # Notify student
    student_id = app_doc.get("student_id")
    job = db["job_posts"].find_one({"_id": job_oid}) or {}
    if isinstance(student_id, ObjectId):
        if status == APPLICATION_STATUS_SHORTLISTED:
            msg = f"Good news! You have been shortlisted for {job.get('role') or 'a role'} at {job.get('company_name') or 'company'}."
        else:
            msg = f"Your application for {job.get('role') or 'a role'} at {job.get('company_name') or 'company'} was not selected."
        create_notification(
            student_id, 
            msg,
            notification_type="application",
            reference_id=job_oid,
            reference_type="job"
        )

    return jsonify({"message": "Status updated.", "status": status}), 200


@app.route("/api/notifications", methods=["GET", "POST"])
@login_required
def api_notifications():
    """
    GET: list notifications for current user (unread first).
    POST: mark all as read.
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    coll = db["notifications"]

    if request.method == "POST":
        coll.update_many(
            {"user_id": user["_id"], "is_read": False},
            {"$set": {"is_read": True}}
        )
        return jsonify({"message": "Marked as read."}), 200

    items = []
    for doc in coll.find({"user_id": user["_id"]}).sort("created_at", -1).limit(20):
        sender_name = None
        sender_id = doc.get("sender_id")
        if sender_id:
            sender = db["users"].find_one({"_id": sender_id}, {"first_name": 1, "last_name": 1, "name": 1})
            if sender:
                sender_name = f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip() or sender.get("name")
        item = {
            "id": str(doc.get("_id")),
            "message": doc.get("message"),
            "is_read": bool(doc.get("is_read")),
            "notification_type": doc.get("notification_type"),
            "type": doc.get("type") or doc.get("notification_type"),
            "sender_id": str(sender_id) if sender_id else None,
            "sender_name": sender_name,
            "reference_type": doc.get("reference_type"),
            "reference_id": str(doc.get("reference_id")) if doc.get("reference_id") else None,
            "post_id": str(doc.get("post_id")) if doc.get("post_id") else (str(doc.get("reference_id")) if doc.get("reference_type") == "post" and doc.get("reference_id") else None),
            "metadata": doc.get("metadata") or {},
            "created_at": to_utc_iso(doc.get("created_at")),
        }
        
        # For connection requests, check if still pending
        if doc.get("notification_type") == "connection_request":
            metadata = doc.get("metadata") or {}
            conn_id = metadata.get("connection_id")
            if conn_id:
                try:
                    conn = db["connections"].find_one({"_id": ObjectId(conn_id)})
                    if conn:
                        item["metadata"]["connection_status"] = conn.get("status")
                except Exception:
                    pass
        
        items.append(item)
    
    # Count unread
    unread_count = coll.count_documents({"user_id": user["_id"], "is_read": False})
    
    return jsonify({"items": items, "unread_count": unread_count}), 200


@app.route("/api/notifications/<notification_id>/read", methods=["POST"])
@login_required
def api_notification_mark_read(notification_id):
    """Mark a single notification as read."""
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    try:
        notif_oid = ObjectId(notification_id)
    except Exception:
        return jsonify({"error": "Invalid notification id"}), 400

    result = db["notifications"].update_one(
        {"_id": notif_oid, "user_id": user["_id"]},
        {"$set": {"is_read": True}}
    )
    
    if result.matched_count == 0:
        return jsonify({"error": "Notification not found"}), 404
    
    return jsonify({"message": "Marked as read"}), 200


@app.route("/notifications", methods=["GET"])
@login_required
def notifications_alias_get():
    """Alias route for listing current user's notifications."""
    return api_notifications()


@app.route("/notifications/read/<notification_id>", methods=["POST"])
@login_required
def notifications_alias_mark_read(notification_id):
    """Alias route for marking single notification as read."""
    return api_notification_mark_read(notification_id)


@app.route("/notifications/read-all", methods=["POST"])
@login_required
def notifications_alias_mark_all_read():
    """Alias route for marking all current user's notifications as read."""
    return api_notifications()


# ---------- Support tickets (SOS / Helpdesk) ----------
SUPPORT_ISSUE_TYPES = frozenset({"technical", "account", "bug", "feature", "other"})
SUPPORT_PRIORITIES = frozenset({"low", "medium", "high"})
SUPPORT_STATUSES = frozenset({"open", "in_progress", "resolved", "closed"})


def resolve_api_user():
    """Session user (users collection) or JWT bearer (coordinator/alumni API)."""
    u = get_logged_in_user()
    if u:
        return u, None
    user, err = require_jwt()
    if err:
        return None, err
    return user, None


def _support_role_for_user(user: dict) -> str:
    ut = (user.get("user_type") or "").strip().lower()
    r = (user.get("role") or "").strip().upper()
    if ut == "student" or r == ROLE_STUDENT:
        return "student"
    if ut == "alumni" or r == ROLE_ALUMNI:
        return "alumni"
    if ut == "faculty" or r == ROLE_FACULTY:
        return "faculty"
    if ut == "coordinator" or r == ROLE_COORDINATOR:
        return "coordinator"
    if ut:
        return re.sub(r"[^a-z0-9]", "_", ut)[:24] or "user"
    return "user"


def _upload_sos_screenshot(file, user: dict, ticket_id: ObjectId):
    if not file or not file.filename:
        return None, None
    ext = _extract_file_ext(file.filename)
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return None, "Screenshot must be JPG/JPEG/PNG."
    try:
        file.stream.seek(0, os.SEEK_END)
        size = file.stream.tell()
        file.stream.seek(0)
    except Exception:
        size = None
    if size and size > MAX_IMAGE_SIZE:
        return None, "Screenshot must be <= 5 MB."
    uploaded, err = upload_to_cloudinary(
        file,
        "campus/sos_reports",
        resource_type="image",
        public_id_prefix=f"sos_{str(ticket_id)}",
    )
    if err:
        return None, err
    return uploaded.get("secure_url"), None


def _support_ticket_number(oid: ObjectId) -> str:
    return "SOS-" + str(oid)[-6:].upper()


def _serialize_support_message(m: dict) -> dict:
    created = m.get("created_at")
    return {
        "sender_name": m.get("sender_name"),
        "sender_role": m.get("sender_role"),
        "message": m.get("message"),
        "created_at": to_utc_iso(created) if isinstance(created, datetime) else None,
        "is_staff": m.get("sender_kind") == "admin" or (m.get("sender_role") or "").lower() == "admin",
    }


def _serialize_support_ticket(doc: dict, include_messages: bool) -> dict:
    oid = doc.get("_id")
    out = {
        "id": str(oid),
        "ticket_number": _support_ticket_number(oid),
        "issue_type": doc.get("issue_type"),
        "title": doc.get("title"),
        "status": doc.get("status"),
        "priority": doc.get("priority"),
        "screenshot_url": doc.get("screenshot_url"),
        "created_at": to_utc_iso(doc.get("created_at")),
        "updated_at": to_utc_iso(doc.get("updated_at")),
    }
    if include_messages:
        out["description"] = doc.get("description")
        out["messages"] = [_serialize_support_message(x) for x in (doc.get("messages") or [])]
    return out


def _notify_support_staff_about_ticket(message: str, notif_type: str, ticket_oid: ObjectId, meta: dict | None = None):
    notified = set()
    meta = dict(meta or {})
    meta["ticket_id"] = str(ticket_oid)
    for u in db["users"].find({"$or": [{"user_type": "admin"}, {"role": ROLE_ADMIN}]}):
        uid = u.get("_id")
        if uid and str(uid) not in notified:
            create_notification(
                uid,
                message,
                notif_type,
                reference_id=ticket_oid,
                reference_type="support_ticket",
                metadata=meta,
            )
            notified.add(str(uid))
    for ad in db["admins"].find({}, {"email": 1}):
        em = (ad.get("email") or "").strip().lower()
        if not em:
            continue
        u = db["users"].find_one({"email": em})
        if u and u.get("_id"):
            sid = str(u["_id"])
            if sid not in notified:
                create_notification(
                    u["_id"],
                    message,
                    notif_type,
                    reference_id=ticket_oid,
                    reference_type="support_ticket",
                    metadata=meta,
                )
                notified.add(sid)


def _admin_sender_name(admin_doc: dict) -> str:
    if not admin_doc:
        return "Support"
    return (
        admin_doc.get("name")
        or f"{admin_doc.get('first_name', '')} {admin_doc.get('last_name', '')}".strip()
        or admin_doc.get("email")
        or "Support"
    )


@app.route("/api/support/tickets", methods=["GET", "POST"])
def api_support_tickets_user():
    user, err = resolve_api_user()
    if err:
        return err
    coll = db["support_tickets"]
    if request.method == "GET":
        items = []
        for doc in coll.find({"user_id": user["_id"]}).sort("updated_at", -1).limit(200):
            items.append(_serialize_support_ticket(doc, False))
        return jsonify({"tickets": items}), 200

    issue_type = (request.form.get("issue_type") or "").strip().lower()
    title = (request.form.get("title") or "").strip()
    description = _clean_multiline_str(request.form.get("description"), 8000) or ""
    priority = (request.form.get("priority") or "medium").strip().lower()
    if issue_type not in SUPPORT_ISSUE_TYPES:
        return jsonify({"error": "Invalid issue type."}), 400
    if priority not in SUPPORT_PRIORITIES:
        return jsonify({"error": "Invalid priority."}), 400
    title_clean = title[:200].strip()
    if not title_clean or len(title_clean) < 3:
        return jsonify({"error": "Title is required (at least 3 characters)."}), 400
    if len(description.strip()) < 10:
        return jsonify({"error": "Description must be at least 10 characters."}), 400

    ticket_oid = ObjectId()
    screenshot_url = None
    screenshot_file = (
        request.files.get("screenshot")
        or request.files.get("screenshot_file")
        or request.files.get("file")
    )
    if screenshot_file and screenshot_file.filename:
        screenshot_url, upload_err = _upload_sos_screenshot(screenshot_file, user, ticket_oid)
        if upload_err:
            return jsonify({"error": upload_err}), 400

    now = datetime.utcnow()
    role = _support_role_for_user(user)
    doc = {
        "_id": ticket_oid,
        "user_id": user["_id"],
        "role": role,
        "issue_type": issue_type,
        "title": title_clean,
        "description": description.strip(),
        "priority": priority,
        "screenshot_url": screenshot_url,
        "status": "open",
        "messages": [],
        "created_at": now,
        "updated_at": now,
    }
    ins = coll.insert_one(doc)
    oid = ins.inserted_id
    _notify_support_staff_about_ticket(
        f"New support ticket: {title_clean}",
        "support_ticket_new",
        oid,
        {"title": title_clean, "priority": priority},
    )
    create_notification(
        user["_id"],
        f"Support ticket {_support_ticket_number(oid)} was created. We'll get back to you soon.",
        "support_ticket_created",
        reference_id=oid,
        reference_type="support_ticket",
        metadata={"title": title_clean},
    )
    doc["_id"] = oid
    return jsonify({"ticket": _serialize_support_ticket(doc, True)}), 201


@app.route("/api/support/tickets/<ticket_id>", methods=["GET"])
def api_support_ticket_get(ticket_id):
    user, err = resolve_api_user()
    if err:
        return err
    try:
        oid = ObjectId(ticket_id)
    except Exception:
        return jsonify({"error": "Invalid ticket id"}), 400
    doc = db["support_tickets"].find_one({"_id": oid})
    if not doc:
        return jsonify({"error": "Not found"}), 404
    if doc.get("user_id") != user["_id"]:
        return jsonify({"error": "Forbidden"}), 403
    return jsonify({"ticket": _serialize_support_ticket(doc, True)}), 200


@app.route("/api/support/tickets/<ticket_id>/messages", methods=["POST"])
def api_support_ticket_message_user(ticket_id):
    user, err = resolve_api_user()
    if err:
        return err
    try:
        oid = ObjectId(ticket_id)
    except Exception:
        return jsonify({"error": "Invalid ticket id"}), 400
    doc = db["support_tickets"].find_one({"_id": oid})
    if not doc:
        return jsonify({"error": "Not found"}), 404
    if doc.get("user_id") != user["_id"]:
        return jsonify({"error": "Forbidden"}), 403
    if (doc.get("status") or "").lower() == "closed":
        return jsonify({"error": "This ticket is closed. Open a new ticket if you still need help."}), 400
    data = request.get_json(silent=True) or {}
    msg_text = _clean_multiline_str(data.get("message"), 4000) or ""
    if len(msg_text.strip()) < 1:
        return jsonify({"error": "Message is required."}), 400
    now = datetime.utcnow()
    msg = {
        "sender_kind": "user",
        "sender_user_id": user["_id"],
        "sender_admin_id": None,
        "sender_name": _user_display_name(user),
        "sender_role": _support_role_for_user(user),
        "message": msg_text.strip(),
        "created_at": now,
    }
    db["support_tickets"].update_one(
        {"_id": oid},
        {"$push": {"messages": msg}, "$set": {"updated_at": now}},
    )
    _notify_support_staff_about_ticket(
        f"User reply on {_support_ticket_number(oid)}: {doc.get('title', '')[:60]}",
        "support_ticket_reply",
        oid,
        {"title": doc.get("title")},
    )
    return jsonify({"message": _serialize_support_message(msg)}), 201


@app.route("/api/admin/support/tickets", methods=["GET"])
def api_admin_support_tickets_list():
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return jsonify({"error": "Admin authentication required"}), 401
    status = (request.args.get("status") or "").strip().lower()
    priority = (request.args.get("priority") or "").strip().lower()
    role = (request.args.get("role") or "").strip().lower()
    q = {}
    if status in SUPPORT_STATUSES:
        q["status"] = status
    if priority in SUPPORT_PRIORITIES:
        q["priority"] = priority
    if role in {"student", "alumni", "faculty", "coordinator"}:
        q["role"] = role
    items = []
    for doc in db["support_tickets"].find(q).sort("updated_at", -1).limit(500):
        row = _serialize_support_ticket(doc, False)
        u = db["users"].find_one(
            {"_id": doc.get("user_id")},
            {"first_name": 1, "last_name": 1, "name": 1, "email": 1},
        )
        row["user_name"] = _user_display_name(u) if u else "Unknown"
        row["user_email"] = (u.get("email") if u else "") or ""
        items.append(row)
    return jsonify({"tickets": items}), 200


@app.route("/api/admin/support/tickets/<ticket_id>", methods=["GET"])
def api_admin_support_ticket_get(ticket_id):
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return jsonify({"error": "Admin authentication required"}), 401
    try:
        oid = ObjectId(ticket_id)
    except Exception:
        return jsonify({"error": "Invalid ticket id"}), 400
    doc = db["support_tickets"].find_one({"_id": oid})
    if not doc:
        return jsonify({"error": "Not found"}), 404
    full = _serialize_support_ticket(doc, True)
    u = db["users"].find_one(
        {"_id": doc.get("user_id")},
        {"first_name": 1, "last_name": 1, "name": 1, "email": 1},
    )
    full["user_name"] = _user_display_name(u) if u else "Unknown"
    full["user_email"] = (u.get("email") if u else "") or ""
    return jsonify({"ticket": full}), 200


@app.route("/api/admin/support/tickets/<ticket_id>", methods=["PATCH"])
def api_admin_support_ticket_patch(ticket_id):
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return jsonify({"error": "Admin authentication required"}), 401
    try:
        oid = ObjectId(ticket_id)
    except Exception:
        return jsonify({"error": "Invalid ticket id"}), 400
    doc = db["support_tickets"].find_one({"_id": oid})
    if not doc:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json(silent=True) or {}
    new_status = (data.get("status") or "").strip().lower()
    if new_status not in SUPPORT_STATUSES:
        return jsonify({"error": "Invalid status."}), 400
    old = doc.get("status")
    now = datetime.utcnow()
    db["support_tickets"].update_one({"_id": oid}, {"$set": {"status": new_status, "updated_at": now}})
    uid = doc.get("user_id")
    if uid and old != new_status:
        create_notification(
            uid,
            f"Ticket {_support_ticket_number(oid)} is now: {new_status.replace('_', ' ').title()}",
            "support_ticket_status",
            reference_id=oid,
            reference_type="support_ticket",
            metadata={"status": new_status, "title": doc.get("title")},
        )
    doc = db["support_tickets"].find_one({"_id": oid})
    return jsonify({"ticket": _serialize_support_ticket(doc, True)}), 200


@app.route("/api/admin/support/tickets/<ticket_id>/messages", methods=["POST"])
def api_admin_support_ticket_message(ticket_id):
    admin_doc, err = require_admin_session(require_second_auth=True)
    if err:
        return jsonify({"error": "Admin authentication required"}), 401
    try:
        oid = ObjectId(ticket_id)
    except Exception:
        return jsonify({"error": "Invalid ticket id"}), 400
    doc = db["support_tickets"].find_one({"_id": oid})
    if not doc:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json(silent=True) or {}
    msg_text = _clean_multiline_str(data.get("message"), 4000) or ""
    if len(msg_text.strip()) < 1:
        return jsonify({"error": "Message is required."}), 400
    now = datetime.utcnow()
    sender_name = _admin_sender_name(admin_doc)
    msg = {
        "sender_kind": "admin",
        "sender_user_id": None,
        "sender_admin_id": admin_doc.get("_id") if admin_doc else None,
        "sender_name": sender_name,
        "sender_role": "admin",
        "message": msg_text.strip(),
        "created_at": now,
    }
    db["support_tickets"].update_one(
        {"_id": oid},
        {"$push": {"messages": msg}, "$set": {"updated_at": now}},
    )
    uid = doc.get("user_id")
    if uid:
        create_notification(
            uid,
            f"Support replied on ticket {_support_ticket_number(oid)}",
            "support_staff_reply",
            reference_id=oid,
            reference_type="support_ticket",
            metadata={"title": doc.get("title")},
        )
    return jsonify({"message": _serialize_support_message(msg)}), 201


# ---------- Admin helpers ----------
def require_admin_session(require_second_auth=False):
    """
    Allow admin access if: (1) session has email and user has admin role, or
    (2) session has admin_email and, when require_second_auth is True, admin_verified.
    """
    if session.get("email"):
        roles = get_user_roles(session["email"])
        if "admin" in roles:
            admin = db["admins"].find_one({"email": session["email"]})
            if admin:
                return admin, None
            user = db["users"].find_one({"email": session["email"]})
            if user and (user.get("user_type") == "admin" or (user.get("role") or "").upper() == ROLE_ADMIN):
                return user, None
    if "admin_email" not in session:
        return None, (redirect(url_for("admin_login")), 302)
    admin = db["admins"].find_one({"email": session.get("admin_email")})
    if not admin:
        session.pop("admin_email", None)
        session.pop("admin_verified", None)
        return None, (redirect(url_for("admin_login")), 302)
    if require_second_auth and not session.get("admin_verified"):
        return None, (redirect(url_for("admin_verify")), 302)
    return admin, None


# ---------- Admin Dashboard ----------
@app.route("/admin/dashboard")
def admin_dashboard_page():
    if "email" in session:
        user_roles = session.get("roles", []) or get_user_roles(session.get("email"))
        session["roles"] = user_roles
        if "admin" not in user_roles:
            flash("You do not have access to the admin dashboard.", "danger")
            return redirect(url_for("main"))
        session["selected_role"] = "admin"
        return send_from_directory(app.static_folder, "admin-dashboard.html")
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return err
    return send_from_directory(app.static_folder, "admin-dashboard.html")


@app.route("/api/admin/overview", methods=["GET"])
def api_admin_overview():
    """Get admin dashboard overview statistics and analytics."""
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return jsonify({"error": "Admin authentication required"}), 401

    users_coll = db["users"]
    student_query = {
        "$or": [
            {"user_type": "student"},
            {"role": ROLE_STUDENT},
            {"role": "STUDENT"}
        ]
    }
    total_students = users_coll.count_documents(student_query)
    total_alumni = users_coll.count_documents({"$or": [{"user_type": "alumni"}, {"role": ROLE_ALUMNI}, {"role": "ALUMNI"}]})
    total_faculty = users_coll.count_documents({"$or": [{"user_type": "faculty"}, {"role": ROLE_FACULTY}]})
    total_coordinators = users_coll.count_documents({"$or": [{"user_type": "coordinator"}, {"role": ROLE_COORDINATOR}]})
    total_jobs_coord = db["job_posts"].count_documents({})
    total_jobs_alumni = db["alumni_jobs"].count_documents({})
    total_jobs_posted = total_jobs_coord + total_jobs_alumni
    total_applications = db["applications"].count_documents({}) + db["alumni_job_applications"].count_documents({})
    active_jobs = db["job_posts"].count_documents({"status": "active"})
    closed_jobs = db["job_posts"].count_documents({"status": {"$ne": "active"}})
    placed_students = users_coll.count_documents({"$or": [{"user_type": "student"}, {"role": ROLE_STUDENT}], "placement_status": PLACEMENT_STATUS_PLACED})
    eligible_students = 0
    try:
        from services.eligibility import check_placement_eligibility
        for u in users_coll.find(student_query, projection={"profile": 1, "verification_status": 1, "branch_code": 1, "branch": 1}):
            u["profile"] = u.get("profile") or {}
            if check_placement_eligibility(u).get("eligible"):
                eligible_students += 1
    except Exception:
        pass
    now = datetime.utcnow()
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    new_registrations_this_month = users_coll.count_documents({"created_at": {"$gte": start_of_month}})
    students_complete = users_coll.count_documents({**student_query, "profile_completion": {"$gte": 80}})
    students_incomplete = users_coll.count_documents({**student_query, "$or": [{"profile_completion": {"$lt": 80}}, {"profile_completion": {"$exists": False}}]})
    most_applied_role = None
    try:
        pipeline = [{"$group": {"_id": "$job_id", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}, {"$limit": 1}]
        agg = list(db["applications"].aggregate(pipeline))
        if agg:
            job_id = agg[0].get("_id")
            job = db["job_posts"].find_one({"_id": job_id}, projection={"role": 1})
            if job:
                most_applied_role = job.get("role")
    except Exception:
        pass
    avg_placement_pct = None
    placement_distribution = []
    try:
        from services.placement_predictor import predict_placement
        predictions = []
        for u in users_coll.find(student_query).limit(200):
            u["profile"] = u.get("profile") or {}
            res = predict_placement(u, None)
            if not res.get("error") and res.get("score") is not None:
                predictions.append(res.get("score", 0))
        if predictions:
            avg_placement_pct = round(sum(predictions) / len(predictions), 1)
            buckets = [0, 20, 40, 60, 80, 100]
            for i in range(len(buckets) - 1):
                low, high = buckets[i], buckets[i + 1]
                count = sum(1 for p in predictions if low <= p < high or (high == 100 and p == 100))
                placement_distribution.append({"range": f"{low}-{high}%", "count": count})
    except Exception:
        pass
    job_postings_per_month = []
    try:
        from collections import defaultdict
        by_month = defaultdict(int)
        for doc in db["job_posts"].find({}, projection={"created_at": 1}):
            ct = doc.get("created_at")
            if ct:
                key = ct.strftime("%Y-%m") if hasattr(ct, "strftime") else str(ct)[:7]
                by_month[key] += 1
        for doc in db["alumni_jobs"].find({}, projection={"created_at": 1}):
            ct = doc.get("created_at")
            if ct:
                key = ct.strftime("%Y-%m") if hasattr(ct, "strftime") else str(ct)[:7]
                by_month[key] += 1
        for k in sorted(by_month.keys(), reverse=True)[:12]:
            job_postings_per_month.append({"month": k, "count": by_month[k]})
        job_postings_per_month.reverse()
    except Exception:
        pass
    student_registrations_per_month = []
    try:
        from collections import defaultdict
        by_month = defaultdict(int)
        for doc in users_coll.find(student_query, projection={"created_at": 1}):
            ct = doc.get("created_at")
            if ct:
                key = ct.strftime("%Y-%m") if hasattr(ct, "strftime") else str(ct)[:7]
                by_month[key] += 1
        for k in sorted(by_month.keys(), reverse=True)[:12]:
            student_registrations_per_month.append({"month": k, "count": by_month[k]})
        student_registrations_per_month.reverse()
    except Exception:
        pass

    return jsonify({
        "counts": {
            "total_users": users_coll.count_documents({}),
            "total_students": total_students,
            "total_alumni": total_alumni,
            "total_faculty": total_faculty,
            "total_coordinators": total_coordinators,
            "total_jobs_posted": total_jobs_posted,
            "total_applications": total_applications,
            "active_jobs": active_jobs,
            "closed_jobs": closed_jobs,
            "placed_students": placed_students,
            "eligible_students": eligible_students,
            "avg_placement_prediction": avg_placement_pct,
            "most_applied_job_role": most_applied_role,
            "new_registrations_this_month": new_registrations_this_month,
            "students_complete_profiles": students_complete,
            "students_incomplete_profiles": students_incomplete,
        },
        "analytics": {
            "job_postings_per_month": job_postings_per_month,
            "student_registrations_per_month": student_registrations_per_month,
            "placement_prediction_distribution": placement_distribution,
        }
    }), 200


@app.route("/api/admin/activities", methods=["GET"])
def api_admin_activities():
    """Get recent activities for admin dashboard."""
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return jsonify({"error": "Admin authentication required"}), 401

    activities = []
    
    # Get recent student registrations (query by user_type OR role)
    student_query = {
        "$or": [
            {"user_type": "student"},
            {"role": ROLE_STUDENT},
            {"role": "STUDENT"}
        ]
    }
    for user in db["users"].find(student_query).sort("created_at", -1).limit(5):
        name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
        activities.append({
            "type": "student_registered",
            "message": f"New student registered: {name}",
            "created_at": to_utc_iso(user.get("created_at")),
        })
    
    # Get recent coordinator additions
    for user in db["users"].find({"user_type": "coordinator"}).sort("created_at", -1).limit(3):
        name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
        activities.append({
            "type": "faculty_added",
            "message": f"Coordinator added: {name}",
            "created_at": to_utc_iso(user.get("created_at")),
        })
    
    # Get recent job posts
    for job in db["job_posts"].find().sort("created_at", -1).limit(3):
        activities.append({
            "type": "job_posted",
            "message": f"New job: {job.get('role')} at {job.get('company_name')}",
            "created_at": to_utc_iso(job.get("created_at")),
        })
    
    # Sort all by created_at and take top 10
    activities.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    
    return jsonify({"activities": activities[:10]}), 200


@app.route("/api/admin/users", methods=["GET"])
def api_admin_users():
    """Get all users for admin management. Includes alumni-specific fields when user is alumni."""
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return jsonify({"error": "Admin authentication required"}), 401

    users = []
    for doc in db["users"].find().sort("created_at", -1):
        name = f"{doc.get('first_name', '')} {doc.get('last_name', '')}".strip()
        ut = (doc.get("user_type") or "").strip().lower()
        role_raw = doc.get("role") or ""
        role = (ut or (role_raw or "student").lower() if isinstance(role_raw, str) else "student")
        if role and role.upper() in (ROLE_STUDENT, ROLE_FACULTY, ROLE_COORDINATOR, ROLE_ADMIN, ROLE_ALUMNI):
            role = role.lower()
        else:
            role = ut or "student"
        entry = {
            "id": str(doc.get("_id")),
            "name": name or doc.get("email", "Unknown"),
            "email": doc.get("email"),
            "role": role,
            "is_blocked": bool(doc.get("is_blocked")),
            "branch": doc.get("branch_code") or doc.get("branch"),
            "verification_status": doc.get("verification_status"),
            "created_at": to_utc_iso(doc.get("created_at")),
        }
        if role == "alumni":
            profile = doc.get("profile") or {}
            edu = profile.get("education") or []
            graduation_year = None
            if edu and isinstance(edu, list) and len(edu) > 0:
                first_edu = edu[0] if isinstance(edu[0], dict) else {}
                graduation_year = first_edu.get("graduation_year") or first_edu.get("year") or first_edu.get("passing_year")
            entry["department"] = doc.get("branch_code") or doc.get("branch") or profile.get("department") or "—"
            entry["graduation_year"] = graduation_year or "—"
            entry["current_company"] = profile.get("current_company") or "—"
            entry["job_role"] = profile.get("designation") or profile.get("job_role") or "—"
        users.append(entry)

    return jsonify({"users": users}), 200


@app.route("/api/admin/users/<user_id>", methods=["GET"])
def api_admin_user_get(user_id):
    """Get a single user by id for admin view."""
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return jsonify({"error": "Admin authentication required"}), 401
    try:
        user_oid = ObjectId(user_id)
    except Exception:
        return jsonify({"error": "Invalid user id"}), 400
    doc = db["users"].find_one({"_id": user_oid})
    if not doc:
        return jsonify({"error": "User not found"}), 404
    name = f"{doc.get('first_name', '')} {doc.get('last_name', '')}".strip()
    ut = (doc.get("user_type") or "").strip().lower()
    role_raw = doc.get("role") or ""
    role = (ut or (role_raw or "student").lower() if isinstance(role_raw, str) else "student")
    if role and role.upper() in (ROLE_STUDENT, ROLE_FACULTY, ROLE_COORDINATOR, ROLE_ADMIN, ROLE_ALUMNI):
        role = role.lower()
    else:
        role = ut or "student"
    entry = {
        "id": str(doc.get("_id")),
        "name": name or doc.get("email", "Unknown"),
        "email": doc.get("email"),
        "role": role,
        "is_blocked": bool(doc.get("is_blocked")),
        "branch": doc.get("branch_code") or doc.get("branch"),
        "verification_status": doc.get("verification_status"),
        "created_at": to_utc_iso(doc.get("created_at")),
    }
    if role == "alumni":
        profile = doc.get("profile") or {}
        edu = profile.get("education") or []
        graduation_year = None
        if edu and isinstance(edu, list) and len(edu) > 0:
            first_edu = edu[0] if isinstance(edu[0], dict) else {}
            graduation_year = first_edu.get("graduation_year") or first_edu.get("year") or first_edu.get("passing_year")
        entry["department"] = doc.get("branch_code") or doc.get("branch") or profile.get("department") or "—"
        entry["graduation_year"] = graduation_year or "—"
        entry["current_company"] = profile.get("current_company") or "—"
        entry["job_role"] = profile.get("designation") or profile.get("job_role") or "—"
    return jsonify({"user": entry}), 200


@app.route("/api/admin/users/<user_id>/block", methods=["POST"])
def api_admin_block_user(user_id):
    """Block or unblock a user."""
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return jsonify({"error": "Admin authentication required"}), 401

    try:
        user_oid = ObjectId(user_id)
    except Exception:
        return jsonify({"error": "Invalid user id"}), 400

    user = db["users"].find_one({"_id": user_oid})
    if not user:
        return jsonify({"error": "User not found"}), 404

    # Prevent blocking admins
    user_role = (user.get("user_type") or user.get("role") or "").lower()
    if user_role == "admin":
        return jsonify({"error": "Cannot block admin users"}), 403

    data = request.get_json(silent=True) or {}
    block = data.get("block", True)

    db["users"].update_one(
        {"_id": user_oid},
        {"$set": {"is_blocked": bool(block)}}
    )

    action = "blocked" if block else "unblocked"
    return jsonify({"message": f"User {action} successfully"}), 200


@app.route("/api/admin/users/<user_id>", methods=["DELETE"])
def api_admin_remove_user(user_id):
    """Remove a user (faculty/coordinator only). Admins and students cannot be removed via this."""
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return jsonify({"error": "Admin authentication required"}), 401
    try:
        user_oid = ObjectId(user_id)
    except Exception:
        return jsonify({"error": "Invalid user id"}), 400
    user = db["users"].find_one({"_id": user_oid})
    if not user:
        return jsonify({"error": "User not found"}), 404
    role = (user.get("user_type") or user.get("role") or "").strip().lower()
    if role == "admin":
        return jsonify({"error": "Cannot remove admin users"}), 403
    if role not in ("faculty", "coordinator"):
        return jsonify({"error": "Only faculty or coordinator accounts can be removed here"}), 403
    db["users"].delete_one({"_id": user_oid})
    return jsonify({"message": "User removed successfully"}), 200


@app.route("/api/admin/students", methods=["GET"])
def api_admin_students():
    """Get all students with profile information for admin."""
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return jsonify({"error": "Admin authentication required"}), 401

    students = []
    # Query for students by user_type OR role to catch all registered students
    query = {
        "$or": [
            {"user_type": "student"},
            {"role": ROLE_STUDENT},
            {"role": "STUDENT"}
        ]
    }
    
    for doc in db["users"].find(query).sort("created_at", -1):
        name = f"{doc.get('first_name', '')} {doc.get('last_name', '')}".strip()
        profile = doc.get("profile") or {}
        education_list = profile.get("education") or []
        
        # Get CGPA from first education entry (education is a list)
        cgpa = None
        if education_list and isinstance(education_list, list) and len(education_list) > 0:
            first_edu = education_list[0] or {}
            cgpa_str = first_edu.get("cgpa")
            if cgpa_str:
                try:
                    cgpa = float(cgpa_str)
                except (ValueError, TypeError):
                    pass
        
        # Calculate profile completion using the profile dict, not the full doc
        completion = calculate_profile_completion(profile)
        
        # Get branch from user doc or first education entry
        branch = doc.get("branch_code") or doc.get("branch")
        if not branch and education_list and isinstance(education_list, list) and len(education_list) > 0:
            first_edu = education_list[0] or {}
            branch = first_edu.get("branch")
        
        students.append({
            "id": str(doc.get("_id")),
            "name": name or doc.get("email", "Unknown"),
            "email": doc.get("email"),
            "branch": branch or "—",
            "cgpa": cgpa,
            "profile_completion": completion,
            "verification_status": doc.get("verification_status") or "pending",
            "created_at": to_utc_iso(doc.get("created_at")),
        })

    return jsonify({"students": students}), 200


# ---------- Coordinator account management (admin-only) ----------
@app.route("/admin/coordinators")
def admin_coordinators_page():
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return err
    return send_from_directory(app.static_folder, "admin-coordinators.html")


@app.route("/api/admin/coordinators", methods=["GET", "POST"])
def api_admin_coordinators():
    _, err = require_admin_session(require_second_auth=True)
    if err:
        # API-friendly response for unauthenticated admin calls
        return jsonify({"error": "Admin authentication required"}), 401

    users = db["users"]

    if request.method == "GET":
        items = []
        for doc in users.find({"user_type": "coordinator"}).sort("created_at", -1):
            items.append({
                "id": str(doc.get("_id")),
                "email": doc.get("email"),
                "first_name": doc.get("first_name"),
                "last_name": doc.get("last_name"),
                "created_at": doc.get("created_at").isoformat() if isinstance(doc.get("created_at"), datetime) else None,
            })
        return jsonify({"items": items}), 200

    # POST create coordinator
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    password = data.get("password") or ""
    branch_code = normalize_branch_code(data.get("branch_code") or data.get("branch"))

    if not email or not first_name or not password:
        return jsonify({"error": "First name, email, and password are required."}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400
    if not branch_code:
        return jsonify({"error": "branch_code is required (e.g., IT, CSE, ECE)."}), 400
    if users.find_one({"email": email}):
        return jsonify({"error": "A user with this email already exists."}), 400

    users.insert_one({
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "password": generate_password_hash(password),
        "user_type": "coordinator",
        "role": ROLE_COORDINATOR,
        "branch_code": branch_code,
        "verification_status": VERIFICATION_PENDING,
        "profile_completion": 0,
        "created_at": datetime.utcnow(),
    })
    return jsonify({"message": "Coordinator created."}), 201


@app.route("/api/admin/faculty-and-coordinators", methods=["GET"])
def api_admin_faculty_and_coordinators():
    """List all faculty and coordinators for admin dashboard. Display: Name, Email, Department, Role."""
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return jsonify({"error": "Admin authentication required"}), 401
    faculty = []
    coordinators = []
    for doc in db["users"].find({
        "$or": [
            {"user_type": "faculty"},
            {"user_type": "coordinator"},
            {"role": ROLE_FACULTY},
            {"role": ROLE_COORDINATOR},
        ]
    }).sort("created_at", -1):
        name = f"{doc.get('first_name', '')} {doc.get('last_name', '')}".strip()
        ut = (doc.get("user_type") or "").strip().lower()
        role_label = "Faculty" if (ut == "faculty" or (doc.get("role") or "").strip().upper() == ROLE_FACULTY) else "Coordinator"
        department = doc.get("branch_code") or doc.get("branch") or "—"
        item = {
            "id": str(doc.get("_id")),
            "email": doc.get("email"),
            "name": name or doc.get("email"),
            "department": department,
            "branch": department,
            "role": role_label,
            "created_at": to_utc_iso(doc.get("created_at")),
        }
        if role_label == "Faculty":
            faculty.append(item)
        else:
            coordinators.append(item)
    return jsonify({"faculty": faculty, "coordinators": coordinators}), 200


@app.route("/api/admin/jobs", methods=["GET"])
def api_admin_jobs():
    """List all jobs: coordinator job_posts and alumni alumni_jobs."""
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return jsonify({"error": "Admin authentication required"}), 401
    jobs = []
    for doc in db["job_posts"].find().sort("created_at", -1):
        jobs.append({
            "id": str(doc.get("_id")),
            "source": "coordinator",
            "company": doc.get("company_name") or doc.get("company"),
            "role": doc.get("role"),
            "job_type": doc.get("type"),
            "location": doc.get("location"),
            "status": doc.get("status"),
            "created_at": to_utc_iso(doc.get("created_at")),
            "posted_by_email": doc.get("created_by_email"),
        })
    for doc in db["alumni_jobs"].find().sort("created_at", -1):
        poster = db["users"].find_one({"_id": doc.get("posted_by")}) if doc.get("posted_by") else None
        poster_name = f"{poster.get('first_name', '')} {poster.get('last_name', '')}".strip() if poster else ""
        jobs.append({
            "id": str(doc.get("_id")),
            "source": "alumni",
            "company": doc.get("company"),
            "role": doc.get("title"),
            "job_type": doc.get("job_type"),
            "location": doc.get("location"),
            "status": None,
            "created_at": to_utc_iso(doc.get("created_at")),
            "posted_by_email": poster.get("email") if poster else "",
            "posted_by_name": poster_name,
        })
    jobs.sort(key=lambda x: (x.get("created_at") or ""), reverse=True)
    return jsonify({"jobs": jobs}), 200


# ---------- Admin Settings (stored in database) ----------
def _default_admin_settings():
    return {
        "platform": {
            "enable_student_registration": True,
            "enable_alumni_registration": True,
            "enable_job_posting": True,
            "max_resume_size_mb": 5,
            "placement_predictor_visible": True,
        },
        "verification": {
            "enable_student_verification": True,
            "enable_faculty_approval_requirement": False,
            "auto_approve_alumni": True,
        },
        "resume": {
            "resume_template": "default",
            "auto_generate_resume": True,
            "allow_resume_download": True,
        },
        "placement_predictor": {
            "enabled": True,
            "min_profile_completion": 40,
            "min_cgpa_required": 0,
        },
        "notifications": {
            "email_notifications": True,
            "job_alert_notifications": True,
            "placement_update_alerts": True,
        },
    }


@app.route("/api/admin/settings", methods=["GET"])
def api_admin_settings_get():
    """Get admin settings (platform, verification, resume, placement, notifications)."""
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return jsonify({"error": "Admin authentication required"}), 401
    doc = db["admin_settings"].find_one({"id": "main"})
    settings = doc.get("settings", {}) if doc else {}
    defaults = _default_admin_settings()
    for key in defaults:
        if key not in settings:
            settings[key] = defaults[key]
    return jsonify({"settings": settings}), 200


@app.route("/api/admin/settings", methods=["PUT", "PATCH"])
def api_admin_settings_update():
    """Update admin settings."""
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return jsonify({"error": "Admin authentication required"}), 401
    data = request.get_json(silent=True) or {}
    defaults = _default_admin_settings()
    settings = {}
    for key in defaults:
        settings[key] = data.get(key, defaults[key])
    db["admin_settings"].update_one(
        {"id": "main"},
        {"$set": {"settings": settings, "updated_at": datetime.utcnow()}},
        upsert=True
    )
    return jsonify({"settings": settings, "message": "Settings saved"}), 200


# ---------- Admin Announcements ----------
def _admin_session_creator_fields() -> dict:
    email = (session.get("email") or session.get("admin_email") or "").strip().lower()
    name = ""
    if email:
        admin_doc = db["admins"].find_one({"email": email})
        if admin_doc:
            name = (
                f"{admin_doc.get('first_name', '')} {admin_doc.get('last_name', '')}".strip()
                or admin_doc.get("name")
                or email
            )
        else:
            user = db["users"].find_one({"email": email})
            if user:
                name = _user_display_name(user)
    return {
        "created_by": email,
        "created_by_email": email,
        "created_by_name": name or email,
        "creator_role": "admin",
        "role": "admin",
    }


@app.route("/api/admin/announcements", methods=["GET"])
def api_admin_announcements_list():
    """List all announcements."""
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return jsonify({"error": "Admin authentication required"}), 401
    announcements = []
    for doc in db["announcements"].find().sort("date", -1):
        announcements.append({
            "id": str(doc.get("_id")),
            "title": doc.get("title"),
            "description": doc.get("description"),
            "date": to_utc_iso(doc.get("date")),
            "visibility": doc.get("visibility") or "all",
            "audience": _announcement_audience_list(doc),
            "media": _announcement_media_items_from_doc(doc),
            "banner_image_url": doc.get("banner_image_url"),
            "media_url": doc.get("media_url") or doc.get("banner_image_url"),
            "posted_by": doc.get("created_by_name") or doc.get("posted_by"),
        })
    return jsonify({"announcements": announcements}), 200


@app.route("/api/admin/announcements", methods=["POST"])
def api_admin_announcements_create():
    """Create announcement. audience: [student, faculty, alumni] or legacy visibility. Optional multipart banner."""
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return jsonify({"error": "Admin authentication required"}), 401
    banner_url = None
    audience_raw = None
    extra_media: list[dict] = []
    if request.content_type and "multipart/form-data" in request.content_type:
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        visibility = (request.form.get("visibility") or "all").strip().lower()
        date_val = request.form.get("date")
        audience_raw = request.form.getlist("audience") or request.form.get("audience_json")
        if isinstance(audience_raw, list) and len(audience_raw) == 1 and audience_raw[0] and str(audience_raw[0]).strip().startswith("["):
            audience_raw = audience_raw[0]
        banner_file = (
            request.files.get("banner")
            or request.files.get("banner_image")
            or request.files.get("file")
        )
        if banner_file and banner_file.filename:
            ext = _extract_file_ext(banner_file.filename)
            if ext not in ALLOWED_IMAGE_EXTENSIONS:
                return jsonify({"error": "Banner must be JPG/JPEG/PNG."}), 400
            uploaded, upload_err = upload_to_cloudinary(
                banner_file,
                "campus/announcements",
                resource_type="image",
                public_id_prefix="announcement_banner",
            )
            if upload_err:
                return jsonify({"error": upload_err}), 400
            banner_url = uploaded.get("secure_url")
        extra_media, m_err = _upload_announcement_media_files_from_request()
        if m_err:
            return jsonify({"error": m_err}), 400
    else:
        data = request.get_json(silent=True) or {}
        title = (data.get("title") or "").strip()
        description = (data.get("description") or "").strip()
        visibility = (data.get("visibility") or "all").strip().lower()
        date_val = data.get("date")
        audience_raw = data.get("audience")
    if visibility not in ("all", "students", "alumni", "faculty"):
        visibility = "all"
    audience, aud_err = _normalize_audience_payload(audience_raw)
    if aud_err:
        return jsonify({"error": aud_err}), 400
    if not audience:
        audience = _visibility_to_audience(visibility)
    if not title:
        return jsonify({"error": "Title is required"}), 400
    if not (description or "").strip():
        return jsonify({"error": "Description is required"}), 400
    if date_val:
        try:
            if isinstance(date_val, str):
                date_val = datetime.fromisoformat(date_val.replace("Z", "+00:00"))
        except Exception:
            date_val = datetime.utcnow()
    else:
        date_val = datetime.utcnow()
    creator = _admin_session_creator_fields()
    doc = {
        "title": title,
        "description": description,
        "date": date_val,
        "visibility": visibility,
        "audience": audience,
        "created_at": datetime.utcnow(),
        **creator,
    }
    if banner_url:
        doc["banner_image_url"] = banner_url
    media_items: list[dict] = []
    if banner_url:
        media_items.append({"url": banner_url, "type": "image"})
    media_items.extend(extra_media)
    if media_items:
        doc["media"] = media_items
        doc["media_urls"] = [m["url"] for m in media_items]
        doc["media_url"] = media_items[0]["url"]
    res = db["announcements"].insert_one(doc)
    doc["_id"] = res.inserted_id
    fan_out_announcement_notifications(
        res.inserted_id,
        audience,
        title,
        creator.get("created_by_email") or creator.get("email"),
    )
    out = {
        "id": str(res.inserted_id),
        "title": doc["title"],
        "description": doc["description"],
        "date": to_utc_iso(doc["date"]),
        "visibility": doc["visibility"],
        "audience": audience,
    }
    if doc.get("banner_image_url"):
        out["banner_image_url"] = doc["banner_image_url"]
    return jsonify({"announcement": out}), 201


@app.route("/api/admin/announcements/<announcement_id>", methods=["PUT"])
def api_admin_announcements_update(announcement_id):
    """Update announcement."""
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return jsonify({"error": "Admin authentication required"}), 401
    try:
        oid = ObjectId(announcement_id)
    except Exception:
        return jsonify({"error": "Invalid id"}), 400
    data = request.get_json(silent=True) or {}
    update = {}
    if "title" in data:
        update["title"] = (data.get("title") or "").strip()
    if "description" in data:
        update["description"] = (data.get("description") or "").strip()
    if "date" in data:
        try:
            date_val = data["date"]
            if isinstance(date_val, str):
                date_val = datetime.fromisoformat(date_val.replace("Z", "+00:00"))
            update["date"] = date_val
        except Exception:
            pass
    if "visibility" in data:
        v = (data.get("visibility") or "all").strip().lower()
        if v in ("all", "students", "alumni", "faculty"):
            update["visibility"] = v
    if "audience" in data:
        aud, aud_err = _normalize_audience_payload(data.get("audience"))
        if aud_err:
            return jsonify({"error": aud_err}), 400
        if aud:
            update["audience"] = aud
    if not update:
        return jsonify({"error": "No fields to update"}), 400
    update["updated_at"] = datetime.utcnow()
    result = db["announcements"].update_one({"_id": oid}, {"$set": update})
    if result.matched_count == 0:
        return jsonify({"error": "Announcement not found"}), 404
    doc = db["announcements"].find_one({"_id": oid})
    return jsonify({
        "announcement": {
            "id": str(doc.get("_id")),
            "title": doc.get("title"),
            "description": doc.get("description"),
            "date": to_utc_iso(doc.get("date")),
            "visibility": doc.get("visibility"),
            "audience": _announcement_audience_list(doc),
        }
    }), 200


@app.route("/api/admin/announcements/<announcement_id>", methods=["DELETE"])
def api_admin_announcements_delete(announcement_id):
    """Delete announcement."""
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return jsonify({"error": "Admin authentication required"}), 401
    try:
        oid = ObjectId(announcement_id)
    except Exception:
        return jsonify({"error": "Invalid id"}), 400
    result = db["announcements"].delete_one({"_id": oid})
    if result.deleted_count == 0:
        return jsonify({"error": "Announcement not found"}), 404
    return jsonify({"message": "Announcement deleted"}), 200


# ---------- JWT helpers ----------
def _get_bearer_token():
    auth = request.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


def create_access_token(user_doc: dict) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": user_doc.get("email"),
        "role": user_doc.get("user_type"),
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRES_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def require_jwt(role: str | None = None):
    """
    Enforce JWT auth using Authorization: Bearer <token>.
    If role is provided, the token/user must match that role.
    Returns (user_doc, None) on success, or (None, (response, status)) on failure.
    """
    token = _get_bearer_token()
    if not token:
        return None, (jsonify({"error": "Not authenticated"}), 401)
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        return None, (jsonify({"error": "Token expired"}), 401)
    except Exception:
        return None, (jsonify({"error": "Invalid token"}), 401)

    email = payload.get("sub")
    if not email:
        return None, (jsonify({"error": "Invalid token"}), 401)

    user = db["users"].find_one({"email": email})
    if not user:
        return None, (jsonify({"error": "User not found"}), 401)

    if user_is_banned(user):
        return None, (jsonify({"error": ACCOUNT_BANNED_AUTH_MESSAGE}), 403)

    if role and (user.get("user_type") or "").lower() != role.lower():
        return None, (jsonify({"error": "Forbidden"}), 403)

    return user, None


def get_session_or_jwt_user():
    """
    User document from Flask session (students, alumni, faculty) or JWT Bearer (coordinators).
    Returns (user_doc, None) or (None, (response, status_code)).
    """
    u = get_logged_in_user()
    if u:
        return u, None
    return require_jwt()


def _user_display_name(user: dict) -> str:
    return (
        f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
        or (user.get("name") or "").strip()
        or user.get("email")
        or "User"
    )


def _creator_role_normalized(user: dict) -> str:
    r = (user.get("role") or "").upper()
    ut = (user.get("user_type") or "").strip().lower()
    if ut == "admin" or r == ROLE_ADMIN:
        return "admin"
    if ut == "coordinator" or r == ROLE_COORDINATOR:
        return "coordinator"
    if ut == "faculty" or r == ROLE_FACULTY:
        return "faculty"
    if ut == "student" or r == ROLE_STUDENT:
        return "student"
    if ut == "alumni" or r == ROLE_ALUMNI:
        return "alumni"
    return ut or r.lower() or ""


def user_can_create_announcements(user: dict) -> bool:
    r = (user.get("role") or "").upper()
    ut = (user.get("user_type") or "").strip().lower()
    if ut == "admin" or r == ROLE_ADMIN:
        return True
    if ut == "coordinator" or r == ROLE_COORDINATOR:
        return True
    if ut == "faculty" or r == ROLE_FACULTY:
        return True
    return False


def _user_audience_key(user: dict) -> str | None:
    """Map viewer to announcement audience key (student / faculty / alumni)."""
    r = (user.get("role") or "").upper()
    ut = (user.get("user_type") or "").strip().lower()
    if ut == "student" or r == ROLE_STUDENT:
        return "student"
    if ut == "alumni" or r == ROLE_ALUMNI:
        return "alumni"
    if ut == "faculty" or r == ROLE_FACULTY:
        return "faculty"
    if ut == "coordinator" or r == ROLE_COORDINATOR:
        return "faculty"
    if ut == "admin" or r == ROLE_ADMIN:
        return "faculty"
    return None


def _visibility_to_audience(visibility: str | None) -> list[str]:
    v = (visibility or "all").strip().lower()
    if v == "all":
        return ["student", "faculty", "alumni"]
    if v in ("students", "student"):
        return ["student"]
    if v == "alumni":
        return ["alumni"]
    if v == "faculty":
        return ["faculty"]
    return ["student", "faculty", "alumni"]


def _announcement_audience_list(doc: dict) -> list[str]:
    aud = doc.get("audience")
    if isinstance(aud, list) and len(aud) > 0:
        return [str(x).lower().strip() for x in aud if x and str(x).strip()]
    return _visibility_to_audience(doc.get("visibility"))


def _announcement_matches_user(doc: dict, user: dict) -> bool:
    key = _user_audience_key(user)
    if not key:
        return False
    return key in set(_announcement_audience_list(doc))


def _normalize_audience_payload(raw) -> tuple[list[str] | None, str | None]:
    """Returns (audience_list, error_message)."""
    if raw is None:
        return None, None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
            raw = parts
    if not isinstance(raw, list):
        return None, "Invalid audience format."
    out = []
    for x in raw:
        s = str(x).lower().strip()
        if s in ANNOUNCEMENT_AUDIENCE_ALLOWED:
            out.append(s)
    if not out:
        return None, "Select at least one audience (Student, Faculty, or Alumni)."
    return list(dict.fromkeys(out)), None


def _infer_media_item_from_url(url: str) -> dict:
    u = (url or "").lower()
    if any(u.endswith(ext) for ext in (".mp4", ".webm", ".mov")) or "/video/upload/" in u:
        return {"url": url, "type": "video"}
    if ".pdf" in u or "/raw/upload/" in u or "/raw/" in u:
        return {"url": url, "type": "pdf"}
    return {"url": url, "type": "image"}


def _announcement_media_items_from_doc(doc: dict) -> list[dict]:
    raw = doc.get("media")
    if isinstance(raw, list) and raw:
        out: list[dict] = []
        for item in raw:
            if isinstance(item, dict) and item.get("url"):
                t = item.get("type") or "file"
                if isinstance(t, str):
                    t = t.strip().lower()
                else:
                    t = "file"
                out.append({"url": str(item["url"]).strip(), "type": t if t in ("image", "video", "pdf", "file") else "file"})
            elif isinstance(item, str) and item.strip():
                out.append(_infer_media_item_from_url(item.strip()))
        if out:
            return out
    urls = doc.get("media_urls")
    if isinstance(urls, list) and urls:
        return [_infer_media_item_from_url(str(u).strip()) for u in urls if u]
    u = doc.get("media_url") or doc.get("banner_image_url")
    if u and isinstance(u, str) and u.strip():
        return [_infer_media_item_from_url(u.strip())]
    return []


def _announcement_upload_kind_and_resource(ext: str) -> tuple[str, str] | None:
    """Cloudinary resource_type and API kind (image|video|pdf|file). None if unsupported."""
    e = (ext or "").lower().strip()
    if e in {"jpg", "jpeg", "png", "gif", "webp"}:
        return "image", "image"
    if e in {"mp4", "webm", "mov"}:
        return "video", "video"
    if e == "pdf":
        return "raw", "pdf"
    if e in {"doc", "docx", "ppt", "pptx", "xls", "xlsx", "zip", "txt", "csv", "rtf"}:
        return "raw", "file"
    return None


def _announcement_max_bytes_for_kind(kind: str) -> int:
    if kind == "video":
        return MAX_VIDEO_SIZE
    if kind in ("pdf", "file"):
        return MAX_DOC_SIZE
    return MAX_IMAGE_SIZE


def _announcement_file_stream_size(file) -> int | None:
    try:
        file.stream.seek(0, os.SEEK_END)
        n = file.stream.tell()
        file.stream.seek(0)
        return int(n) if n is not None else None
    except Exception:
        return None


def _upload_announcement_media_files_from_request() -> tuple[list[dict] | None, str | None]:
    """Parse multipart files and upload to Cloudinary. Returns (items, error_message)."""
    collected = []
    for key in ("media", "media[]", "files"):
        for f in request.files.getlist(key):
            if f and getattr(f, "filename", None) and str(f.filename).strip():
                collected.append(f)
    if not collected:
        return [], None
    if len(collected) > ANNOUNCEMENT_MEDIA_MAX_FILES:
        return None, f"At most {ANNOUNCEMENT_MEDIA_MAX_FILES} media files allowed."
    media_items: list[dict] = []
    for f in collected:
        ext = _extract_file_ext(f.filename)
        kr = _announcement_upload_kind_and_resource(ext)
        if not kr:
            return None, f"Unsupported file type: .{ext or 'unknown'}"
        resource_type, kind = kr
        max_b = _announcement_max_bytes_for_kind(kind)
        sz = _announcement_file_stream_size(f)
        if sz is not None and sz > max_b:
            return None, f"File too large ({f.filename!r}). Max {max_b // (1024 * 1024)} MB for this type."
        uploaded, upload_err = upload_to_cloudinary(
            f,
            "campus/announcements",
            resource_type=resource_type,
            public_id_prefix="announcement_media",
        )
        if upload_err:
            return None, upload_err
        url = (uploaded or {}).get("secure_url") or (uploaded or {}).get("url")
        if not url:
            return None, "Upload failed."
        media_items.append({"url": url, "type": kind})
    return media_items, None


def _serialize_announcement_doc(doc: dict, *, include_audience: bool = True) -> dict:
    created = doc.get("created_at") or doc.get("date")
    desc = doc.get("description")
    if desc is None:
        desc = doc.get("body") or ""
    media_items = _announcement_media_items_from_doc(doc)
    legacy = doc.get("media_url") or doc.get("banner_image_url")
    out = {
        "id": str(doc.get("_id")),
        "title": doc.get("title") or "",
        "description": desc,
        "body": desc,
        "media": media_items,
        "media_urls": [m["url"] for m in media_items],
        "media_url": media_items[0]["url"] if media_items else legacy,
        "posted_by": doc.get("created_by_name") or doc.get("posted_by") or "",
        "created_by": doc.get("created_by") or doc.get("created_by_email") or "",
        "role": doc.get("creator_role") or doc.get("role") or "",
        "created_at": created.isoformat() if isinstance(created, datetime) else (to_utc_iso(created) if created else None),
    }
    if include_audience:
        out["audience"] = _announcement_audience_list(doc)
    if doc.get("date") is not None:
        d = doc.get("date")
        out["date"] = d.isoformat() if isinstance(d, datetime) else to_utc_iso(d)
    return out


# default -> admin login
@app.route("/")
def home():
    return redirect(url_for("admin_login"))


# ---------- Admin routes ----------
@app.route("/admin/register", methods=["GET", "POST"])
def admin_register():
    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not first_name or not last_name or not email or not password:
            flash("Please fill all fields.")
            return redirect(url_for("admin_register"))

        if password != confirm_password:
            flash("Passwords do not match.")
            return redirect(url_for("admin_register"))

        admins = db["admins"]
        if admins.find_one({"email": email}):
            flash("Admin email already registered.")
            return redirect(url_for("admin_register"))

        pw_hash = generate_password_hash(password)
        admins.insert_one({
            "first_name": first_name,
            "last_name": last_name,
            "name": f"{first_name} {last_name}".strip(),
            "email": email,
            "password": pw_hash,
            "created_at": datetime.utcnow()
        })
        flash("Admin registration successful! Please log in.")
        return redirect(url_for("admin_login"))

    return send_from_directory(app.static_folder, "admin-signup.html")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        admin = db["admins"].find_one({"email": email})
        if admin and check_password_hash(admin["password"], password):
            session.clear()
            session["admin_email"] = email
            session.pop("admin_verified", None)
            user = db["users"].find_one({"email": email})
            if user:
                session["email"] = email
                session["roles"] = get_user_roles(email)
            return redirect(url_for("dashboard_selector"))
        flash("Invalid admin email or password.")
        return redirect(url_for("admin_login"))
    return send_from_directory(app.static_folder, "admin-signin.html")


@app.route("/admin/verify", methods=["GET", "POST"])
def admin_verify():
    """Second-level authentication: require password again before opening Admin Dashboard."""
    if "admin_email" not in session:
        return redirect(url_for("admin_login"))
    if request.method == "POST":
        password = request.form.get("password", "")
        admin = db["admins"].find_one({"email": session.get("admin_email")})
        if admin and check_password_hash(admin["password"], password):
            session["admin_verified"] = True
            return redirect(url_for("admin_dashboard_page"))
        return redirect(url_for("admin_verify") + "?error=1")
    return send_from_directory(app.static_folder, "admin-verify.html")


@app.route("/main")
def main():
    return send_from_directory(app.static_folder, "main.html")


# ---------- User registration & login ----------
@app.route("/register")
def register_page():
    return send_from_directory(app.static_folder, "registration.html")


def collection_has_documents(collection_name: str) -> bool:
    try:
        return db[collection_name].estimated_document_count() > 0
    except Exception:
        return False


def find_student_by_roll(roll_number: str):
    roll_clean = normalize_roll(roll_number)
    if not roll_clean:
        return None
    try:
        student_coll = db["student"]
    except Exception:
        return None
    candidate_keys = {"roll", "rollno", "rollnumber", "roll_no", "rollnum"}
    for doc in student_coll.find({}, projection=None):
        for key, value in doc.items():
            key_norm = "".join(ch.lower() for ch in str(key) if ch.isalnum())
            if key_norm in candidate_keys:
                if normalize_roll(value) == roll_clean:
                    return doc
    return None


def normalize_branch(branch: str) -> str:
    if not branch:
        return ""
    return branch.strip().upper()


def bootstrap_student_collection():
    csv_path = os.path.join(os.path.dirname(__file__), "data", "IT4 database.csv")
    if not os.path.exists(csv_path):
        return
    if collection_has_documents("student"):
        return
    docs = []
    with open(csv_path, newline="", encoding="utf-8-sig") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if not row:
                continue
            cleaned = {}
            for key, value in row.items():
                if key is None:
                    continue
                cleaned_key = key.strip()
                cleaned[cleaned_key] = value.strip() if isinstance(value, str) else value
            if cleaned:
                if "Branch" in cleaned:
                    cleaned["Branch"] = normalize_branch(cleaned["Branch"])
                cleaned.setdefault("branch", cleaned.get("Branch"))
                docs.append(cleaned)
    if docs:
        db["student"].insert_many(docs)


try:
    bootstrap_student_collection()
except Exception as e:
    # Avoid hard crash on startup when DB is temporarily unreachable.
    print(f"[startup] Student bootstrap skipped: {e}")


@app.route("/login")
def login_page():
    return send_from_directory(app.static_folder, "login.html")


@app.route("/images/<path:filename>")
def images(filename):
    """
    Serve logo and other brand assets from the top-level images directory.
    This keeps existing /images/logo.png references working across all pages.
    """
    images_dir = os.path.join(app.root_path, "images")
    return send_from_directory(images_dir, filename)


@app.route("/dashboard-selector")
def dashboard_selector():
    """Dashboard selection (admin flow only): Student Dashboard or Admin Dashboard. Requires admin login."""
    if "admin_email" not in session and "email" not in session:
        flash("Please sign in first.", "warning")
        return redirect(url_for("admin_login"))
    return send_from_directory(app.static_folder, "dashboard-selector.html")


@app.route("/api/auth/select-role", methods=["POST"])
@login_required
def api_select_role():
    """Handle role selection and redirect to appropriate dashboard."""
    if "email" not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    data = request.get_json(silent=True) or {}
    selected_role = (data.get("role") or "").lower()
    
    if not selected_role:
        return jsonify({"error": "Role is required"}), 400
    
    # Get user's available roles
    user_roles = session.get("roles", [])
    if not user_roles:
        # Re-fetch roles if not in session
        user_roles = get_user_roles(session.get("email"))
        session["roles"] = user_roles
    
    # Validate that user has this role
    if selected_role not in user_roles:
        return jsonify({"error": "You do not have access to this role"}), 403
    
    # Store selected role in session
    session["selected_role"] = selected_role
    
    # Determine redirect URL
    if selected_role == "admin":
        redirect_url = "/admin/dashboard"
    elif selected_role == "student":
        redirect_url = "/user/dashboard"
    elif selected_role == "coordinator":
        redirect_url = "/coordinator/dashboard"
    elif selected_role == "faculty":
        redirect_url = "/faculty/dashboard"
    elif selected_role == "alumni":
        redirect_url = "/alumni/dashboard"
    else:
        redirect_url = "/main"
    
    return jsonify({
        "message": "Role selected successfully",
        "redirect": redirect_url
    }), 200


@app.route("/announcements")
@login_required
@role_required("STUDENT", "ALUMNI")
def announcements_feed_page():
    """Full-screen announcements list (LinkedIn-style mobile hub)."""
    return send_from_directory(app.static_folder, "announcements_feed.html")


@app.route("/user/dashboard")
@login_required
def user_dashboard():
    if "email" not in session:
        return redirect(url_for("login_page"))
    
    # Roles from session (set at login; same for normal and post-reset login)
    user_roles = session.get("roles", [])
    if not user_roles:
        user_roles = get_user_roles(session.get("email"))
        session["roles"] = user_roles
    
    # Use primary role from login so we don't send users to selector when they were already sent here
    effective_role = session.get("selected_role") or session.get("role")
    if len(user_roles) > 1 and not effective_role:
        return redirect(url_for("dashboard_selector"))
    
    if effective_role == "alumni" or ("alumni" in user_roles and "student" not in user_roles):
        return redirect(url_for("alumni_dashboard"))
    if effective_role == "student" or "student" in user_roles:
        return send_from_directory(app.static_folder, "student_dashboard.html")

    flash("You do not have access to the student dashboard.", "danger")
    if len(user_roles) > 1:
        return redirect(url_for("dashboard_selector"))
    return redirect(url_for("main"))


@app.route("/student/placement-predictor")
@login_required
@role_required("STUDENT")
def student_placement_predictor_page():
    """Serve the Placement Predictor page (opens in new tab)."""
    return send_from_directory(app.static_folder, "placement_predictor.html")


@app.route("/student/skill-gap/<job_id>")
@login_required
@role_required("STUDENT")
def student_skill_gap_page(job_id):
    """Serve the Skill Gap Analysis page for a job."""
    return send_from_directory(app.static_folder, "skill_gap.html")


@app.route("/api/student/skill-gap/<job_id>", methods=["GET"])
@login_required
@role_required("STUDENT")
def api_student_skill_gap(job_id):
    """Return skill gap analysis and course recommendations for the given job."""
    student = get_logged_in_user()
    if not student:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        oid = ObjectId(job_id)
    except Exception:
        return jsonify({"error": "Invalid job id"}), 400
    job = db["job_posts"].find_one({"_id": oid, "status": "active"})
    if not job:
        aj = db["alumni_jobs"].find_one({"_id": oid})
        if aj:
            job = _alumni_job_doc_for_placement_engine(aj)
        else:
            return jsonify({"error": "Job not found or inactive"}), 404
    student_with_profile = dict(student)
    student_with_profile["profile"] = _profile_for_user(student)
    gap = analyze_skill_gap(student_with_profile, job)
    recommendations = recommend_courses_grouped_by_skill(gap["missing_skills"])
    job_basic = {
        "id": str(job["_id"]),
        "company_name": job.get("company_name"),
        "role": job.get("role") or job.get("title"),
        "type": job.get("type") or job.get("job_type"),
        "mode": job.get("mode") or job.get("work_mode"),
        "deadline": job.get("deadline") or job.get("application_deadline"),
        "salary": job.get("salary"),
        "eligible_branches": job.get("eligible_branches") or job.get("branches_allowed") or [],
        "required_skills": job.get("required_skills") or job.get("requiredSkills") or [],
    }
    return jsonify({
        "job": job_basic,
        "matched_skills": gap["matched_skills"],
        "missing_skills": gap["missing_skills"],
        "match_percentage": gap["match_percentage"],
        "recommendations": recommendations,
    }), 200


@app.route("/messages")
@login_required
def messages_page():
    """Serve the messages page."""
    return send_from_directory(app.static_folder, "messages.html")


@app.route("/student/profile/edit")
@login_required
@role_required("STUDENT")
def edit_student_profile():
    if "email" not in session:
        return redirect(url_for("login_page"))
    user = db["users"].find_one({"email": session.get("email")})
    if not user or user.get("user_type") != "student":
        return redirect(url_for("main"))
    return send_from_directory(app.static_folder, "edit_profile.html")


@app.route("/student/profile")
@login_required
@role_required("STUDENT")
def student_profile_page():
    return send_from_directory(app.static_folder, "student_profile.html")


@app.route("/student/settings")
@login_required
@role_required("STUDENT")
def student_settings_page():
    return send_from_directory(app.static_folder, "student_settings.html")


# ---------- Private Resume (PDF only, no approval, no storage) ----------
RESUME_PREVIEW_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Resume Preview</title>
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 11pt;
      line-height: 1.4;
      color: #1a1a1a;
      background: #f5f5f5;
      padding: 24px 16px 32px;
    }
    .resume-wrap {
      max-width: 700px;
      margin: 0 auto;
      background: #fff;
      padding: 32px 40px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    }
    .resume-name { margin: 0 0 4px; font-size: 22pt; font-weight: 700; }
    .resume-headline-block { margin-bottom: 12px; }
    .resume-headline { margin: 0 0 4px; font-size: 12pt; color: #333; }
    .resume-about { margin: 0; color: #444; }
    .resume-section { margin-bottom: 14px; }
    .resume-h2 { margin: 0 0 6px; font-size: 12pt; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid #ccc; padding-bottom: 4px; }
    .resume-list { margin: 0; padding-left: 20px; }
    .resume-list li { margin-bottom: 4px; }
    .resume-contact { margin: 0; }
    .resume-skills { margin: 0; }
    .resume-desc { color: #444; font-size: 10pt; }
    .download-row { text-align: center; margin-top: 28px; padding-top: 20px; border-top: 1px solid #eee; }
    .download-row a {
      display: inline-block;
      padding: 10px 24px;
      background: #1a365d;
      color: #fff;
      text-decoration: none;
      border-radius: 8px;
      font-weight: 600;
      font-size: 14px;
    }
    .download-row a:hover { background: #2c5282; }
  </style>
</head>
<body>
  <div class="resume-wrap">
    {{ resume_body }}
    <div class="download-row">
      <a href="/resume-download">Download PDF</a>
    </div>
  </div>
</body>
</html>
"""


@app.route("/resume-preview")
@login_required
@role_required("STUDENT")
def resume_preview():
    """Resume preview page: owner-only, no navbar/sidebar, one Download PDF button."""
    user = get_logged_in_user()
    profile = _profile_for_user(user)
    resume_body = build_resume_html(user, profile)
    html = RESUME_PREVIEW_HTML.replace("{{ resume_body }}", resume_body)
    return Response(html, mimetype="text/html; charset=utf-8")


@app.route("/resume-download")
@login_required
@role_required("STUDENT")
def resume_download():
    """Generate resume PDF from current user profile. Owner-only."""
    user = get_logged_in_user()
    profile = _profile_for_user(user)
    pdf_bytes = build_resume_pdf(user, profile)
    filename = safe_resume_filename(user)
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.route("/logout")
def logout():
    # Always do a full logout to ensure all protected tabs become unauthenticated.
    session.clear()
    flash("Logged out.")
    return redirect(url_for("login_page"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """
    Password reset request endpoint.
    GET  -> serve forgot password page.
    POST -> accept email, generate token, send email (generic response).
    """
    if request.method == "GET":
        return send_from_directory(app.static_folder, "forgot-password.html")

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()

    # Generic response to avoid email enumeration.
    generic_response = jsonify(
        {"message": "If this email is registered, a reset link has been sent."}
    )

    if not email:
        # Still use generic message to avoid leaking information.
        return generic_response, 200

    users_coll = db["users"]
    user = users_coll.find_one({"email": email})

    if not user:
        # Do not reveal whether email exists.
        return generic_response, 200

    if user_is_banned(user):
        return generic_response, 200

    now = datetime.utcnow()

    # Basic rate limiting: max 3 requests per hour per email.
    window_start = user.get("reset_request_window_start")
    request_count = user.get("reset_request_count") or 0

    if isinstance(window_start, datetime):
        window_age = now - window_start
    else:
        window_age = timedelta(hours=2)  # force reset window if invalid

    if window_age > timedelta(hours=1):
        window_start = now
        request_count = 0

    if request_count >= 3:
        # Too many requests in this window; silently ignore.
        try:
            app.logger.warning(f"Password reset rate limit exceeded for {email}")
        except Exception:
            pass
        return generic_response, 200

    # Generate secure token and store hashed version.
    raw_token = secrets.token_urlsafe(32)
    hashed_token = generate_password_hash(raw_token)
    expiry = now + timedelta(minutes=15)

    users_coll.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "reset_token": hashed_token,
                "reset_token_expiry": expiry,
                "reset_request_window_start": window_start,
                "reset_request_count": request_count + 1,
            }
        },
    )

    # Send email (errors are logged, not exposed to client).
    send_password_reset_email(email, raw_token)

    return generic_response, 200


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    """
    Password reset endpoint.
    GET  -> validate token and serve reset page or error page.
    POST -> validate token again, validate password strength, update password.
    """
    if request.method == "GET":
        user = _find_user_by_reset_token(token)
        if not user:
            # Invalid or expired token - show simple error page.
            return (
                """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Invalid or Expired Link</title>
  <style>
    body { font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#f9fafb; display:flex; align-items:center; justify-content:center; min-height:100vh; }
    .card { background:white; padding:32px 28px; border-radius:12px; box-shadow:0 10px 30px rgba(15,23,42,0.12); max-width:420px; width:100%; text-align:center; }
    h1 { font-size:22px; margin-bottom:12px; color:#1f2933; }
    p { font-size:14px; color:#4b5563; margin-bottom:16px; }
    a { color:#2563eb; text-decoration:none; font-weight:500; }
    a:hover { text-decoration:underline; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Link expired or invalid</h1>
    <p>Your password reset link is invalid or has expired. Please request a new reset.</p>
    <p><a href="/forgot-password">Request a new reset link</a></p>
  </div>
</body>
</html>
                """,
                400,
            )

        if user_is_banned(user):
            _ban_msg = html_escape(ACCOUNT_BANNED_AUTH_MESSAGE)
            return (
                f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Account banned</title>
  <style>
    body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#f9fafb; display:flex; align-items:center; justify-content:center; min-height:100vh; }}
    .card {{ background:white; padding:32px 28px; border-radius:12px; box-shadow:0 10px 30px rgba(15,23,42,0.12); max-width:420px; width:100%; text-align:center; }}
    h1 {{ font-size:22px; margin-bottom:12px; color:#1f2933; }}
    p {{ font-size:14px; color:#4b5563; margin-bottom:16px; line-height:1.5; }}
    a {{ color:#2563eb; text-decoration:none; font-weight:500; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Account banned</h1>
    <p>{_ban_msg}</p>
    <p><a href="/login">Back to sign in</a></p>
  </div>
</body>
</html>
                """,
                403,
            )

        # Token is valid -> serve reset password page.
        return send_from_directory(app.static_folder, "reset-password.html")

    # POST: handle new password submission (JSON body expected).
    data = request.get_json(silent=True) or {}
    new_password = (data.get("new_password") or "").strip()

    ok, reason = is_strong_password(new_password)
    if not ok:
        return jsonify({"error": reason}), 400

    user = _find_user_by_reset_token(token)
    if not user:
        return jsonify({"error": "Invalid or expired link. Please request a new reset."}), 400

    if user_is_banned(user):
        return jsonify({"error": ACCOUNT_BANNED_AUTH_MESSAGE}), 403

    users_coll = db["users"]
    try:
        # Only update password and clear reset fields; do NOT replace the document.
        users_coll.update_one(
            {"_id": user["_id"]},
            {
                "$set": {"password": generate_password_hash(new_password)},
                "$unset": {
                    "reset_token": "",
                    "reset_token_expiry": "",
                    "reset_request_window_start": "",
                    "reset_request_count": "",
                },
            },
        )
    except Exception:
        return jsonify({"error": "Failed to update password. Please try again."}), 500

    # Re-fetch user to verify structure and that role/user_type are unchanged
    user_after = users_coll.find_one({"_id": user["_id"]})
    if not user_after:
        return jsonify({"error": "Failed to verify account after update."}), 500

    role_val = (user_after.get("role") or "").strip().upper()
    if role_val not in (ROLE_STUDENT, ROLE_COORDINATOR, ROLE_ADMIN, ROLE_ALUMNI):
        derived = derive_role_from_existing_user_type(user_after.get("user_type"))
        users_coll.update_one(
            {"_id": user["_id"]},
            {"$set": {"role": derived}},
        )
    # Password reset must never modify role; only ensure it exists from user_type

    # Do not set session or redirect here. User must sign in via /login;
    # role-based redirect is handled by the same api_signin() logic.
    return jsonify({"message": "Password has been reset successfully. You can now sign in."}), 200


@app.route("/alumni/set-password/<token>", methods=["GET", "POST"])
def alumni_set_password(token):
    """Alumni password setup after approval: validate token, set password, set is_active=True."""
    if request.method == "GET":
        user = _find_user_by_setup_token(token)
        if not user:
            return (
                """
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Invalid or Expired Link</title>
<style>body{font-family:system-ui,sans-serif;background:#f9fafb;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;}
.card{background:white;padding:32px;border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,0.08);max-width:420px;text-align:center;}
h1{font-size:20px;color:#1f2933;}p{color:#4b5563;margin:16px 0;}a{color:#2563eb;text-decoration:none;}</style></head>
<body><div class="card"><h1>Link expired or invalid</h1><p>Your password setup link is invalid or has expired. Please contact your coordinator.</p><p><a href="/main">Go to CampusLink</a></p></div></body></html>
                """,
                400,
            )
        if user_is_banned(user):
            _bm = html_escape(ACCOUNT_BANNED_AUTH_MESSAGE)
            return (
                f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Account banned</title>
<style>body{{font-family:system-ui,sans-serif;background:#f9fafb;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;}}
.card{{background:white;padding:32px;border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,0.08);max-width:420px;text-align:center;}}
h1{{font-size:20px;color:#1f2933;}}p{{color:#4b5563;margin:16px 0;line-height:1.5;}}a{{color:#2563eb;text-decoration:none;}}</style></head>
<body><div class="card"><h1>Account banned</h1><p>{_bm}</p><p><a href="/main">Go to CampusLink</a></p></div></body></html>""",
                403,
            )
        return send_from_directory(app.static_folder, "alumni-set-password.html")
    data = request.get_json(silent=True) or {}
    new_password = (data.get("new_password") or "").strip()
    ok, reason = is_strong_password(new_password)
    if not ok:
        return jsonify({"error": reason}), 400
    user = _find_user_by_setup_token(token)
    if not user:
        return jsonify({"error": "Invalid or expired link. Please contact your coordinator."}), 400
    if user_is_banned(user):
        return jsonify({"error": ACCOUNT_BANNED_AUTH_MESSAGE}), 403
    db["users"].update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "password": generate_password_hash(new_password),
                "is_active": True,
            },
            "$unset": {
                "password_setup_token": "",
                "password_setup_token_expiry": "",
            },
        },
    )
    return jsonify({"message": "Password set successfully. You can now sign in."}), 200


@app.route("/api/auth/register", methods=["POST"])
def api_register():
    data = request.get_json(silent=True) or {}
    user_type = (data.get("user_type") or data.get("role") or "").strip().lower()
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    branch = normalize_branch(data.get("branch"))

    allowed_branches = {"IT", "CST", "CE", "DS", "ENC", "AI"}

    if user_type not in {"student", "coordinator", "faculty"}:
        return jsonify({"error": "Please select a valid role (Student, Faculty, or Coordinator)."}), 400
    if not first_name or not email or not password:
        return jsonify({"error": "First name, email, and password are required."}), 400
    if user_type == "student" and not (last_name or "").strip():
        return jsonify({"error": "Last name is required for students."}), 400
    if user_type == "faculty" and not branch:
        return jsonify({"error": "Faculty must select a department (branch)."}), 400
    if branch and branch not in allowed_branches:
        return jsonify({"error": "Please choose a valid branch code (IT, CST, CE, DS, ENC, AI)."}), 400

    users = db["users"]
    if is_email_banned(db, email):
        return jsonify({"error": ACCOUNT_BANNED_AUTH_MESSAGE}), 403
    existing_reg = users.find_one({"email": email})
    if existing_reg and user_is_banned(existing_reg):
        return jsonify({"error": ACCOUNT_BANNED_AUTH_MESSAGE}), 403
    if existing_reg:
        return jsonify({"error": "Email already registered. Please sign in."}), 400

    user_doc = {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "password": generate_password_hash(password),
        "user_type": user_type,
        "branch": branch,
        "role": derive_role_from_existing_user_type(user_type),
        "branch_code": normalize_branch_code(branch),
        "profile_completion": 0,
        "created_at": datetime.utcnow(),
    }
    if user_type == "student":
        user_doc["verification_status"] = VERIFICATION_PENDING
        user_doc["placement_status"] = PLACEMENT_STATUS_NOT_PLACED
        user_doc["is_valid_student"] = True
    else:
        # Faculty and Coordinator: auto-active, no verification required
        user_doc["verification_status"] = VERIFICATION_VERIFIED

    if user_type == "student":
        roll_number = normalize_roll(data.get("roll_number"))
        if not roll_number:
            return jsonify({"error": "Roll number is required for students."}), 400
        if users.find_one({"roll_number": roll_number}):
            return jsonify({"error": "User already registered"}), 400
        master_doc, master_err = validate_student_registration_against_master(
            db, first_name, last_name, roll_number
        )
        if master_err or not master_doc:
            return jsonify({"error": master_err or "Invalid Name or Roll Number. Please check your details."}), 400
        user_doc["roll_number"] = roll_number
        branch_from_master = None
        for key in ["Branch", "branch", "BRANCH"]:
            branch_value = master_doc.get(key)
            branch_normalized = normalize_branch(branch_value) if branch_value else ""
            if branch_normalized:
                branch_from_master = branch_normalized
                break
        if branch_from_master:
            if branch_from_master not in allowed_branches:
                return jsonify({"error": "Your records could not be verified. Contact admin."}), 400
            user_doc["branch"] = branch_from_master
            user_doc["branch_code"] = normalize_branch_code(branch_from_master)
        elif branch:
            user_doc["branch"] = branch
            user_doc["branch_code"] = normalize_branch_code(branch)
        else:
            return jsonify({"error": "Branch could not be determined from your records. Contact admin."}), 400
    elif user_type == "coordinator":
        faculty_id = str(data.get("faculty_id") or "").strip()
        user_doc["faculty_id"] = faculty_id
        faculty_coll = db.get_collection("faculty")
        if faculty_id and collection_has_documents("faculty"):
            match = faculty_coll.find_one({"$or": [
                {"faculty_id": faculty_id},
                {"facultyId": faculty_id},
                {"facultyID": faculty_id}
            ]})
            if not match:
                return jsonify({"error": "Faculty ID not found. Please contact admin."}), 400

    users.insert_one(user_doc)
    inserted_id = user_doc.get("_id")
    role = (user_doc.get("role") or user_doc.get("user_type") or "").strip().upper()
    if inserted_id and role in (ROLE_STUDENT, ROLE_ALUMNI):
        name = f"{user_doc.get('first_name', '')} {user_doc.get('last_name', '')}".strip() or "user"
        branch_or_company = user_doc.get("branch") or user_doc.get("branch_code") or ""
        if role == ROLE_ALUMNI:
            profile = user_doc.get("profile") or {}
            branch_or_company = branch_or_company or profile.get("current_company") or ""
        base_slug = generate_public_slug(name, branch_or_company or None)
        public_slug = ensure_unique_slug(users, base_slug, exclude_user_id=None)
        updates = {"public_slug": public_slug}
        base_url = (request.host_url or "").rstrip("/") or "https://yourdomain.com"
        qr_path = qr_profile_generate_qr(
            str(inserted_id), public_slug, base_url, app.static_folder
        )
        if qr_path:
            updates["qr_code_url"] = qr_path
        if updates:
            users.update_one({"_id": inserted_id}, {"$set": updates})
    return jsonify({"message": "Registration successful."}), 201


@app.route("/api/auth/signin", methods=["POST"])
def api_signin():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    user = db["users"].find_one({"email": email})
    user_valid = user and check_password_hash(user["password"], password)
    if user_valid and user and user_is_banned(user):
        return jsonify({"error": ACCOUNT_BANNED_AUTH_MESSAGE}), 403
    if user_valid and user and is_flagged_invalid_student(user):
        return jsonify({
            "error": "Your student record could not be verified against official records. Please contact admin.",
        }), 403
    if user_valid and (user.get("user_type") or "").strip().lower() == "alumni":
        if not user.get("is_active"):
            return jsonify({"error": "Your account is not active. Please complete password setup from the email sent after approval."}), 403
    
    # Check admins collection
    admin = db["admins"].find_one({"email": email})
    admin_valid = admin and check_password_hash(admin["password"], password)
    
    if not user_valid and not admin_valid:
        return jsonify({"error": "Invalid email or password."}), 401

    # Get all roles for this user (reads from DB again inside get_user_roles)
    all_roles = get_user_roles(email)
    # If user is in users collection but roles came back empty (e.g. missing role/user_type after reset), treat as student
    if user_valid and not all_roles and user:
        all_roles = ["student"]

    # Clear session and set up new session (single place for all logins, including after password reset)
    session.clear()
    session["email"] = email
    session["roles"] = all_roles

    # Determine redirect from database roles (same logic for normal login and post-reset login)
    if not all_roles:
        redirect_url = "/main"
        primary_role = None
    elif "alumni" in all_roles and user_valid:
        redirect_url = "/alumni/dashboard"
        primary_role = "alumni"
    elif "faculty" in all_roles and user_valid:
        redirect_url = "/faculty/dashboard"
        primary_role = "faculty"
    elif "coordinator" in all_roles and user_valid:
        redirect_url = "/coordinator/dashboard"
        primary_role = "coordinator"
    elif "admin" in all_roles and admin_valid:
        redirect_url = "/admin/dashboard"
        primary_role = "admin"
    elif "student" in all_roles:
        redirect_url = "/user/dashboard"
        primary_role = "student"
    elif "faculty" in all_roles:
        redirect_url = "/faculty/dashboard"
        primary_role = "faculty"
    elif "coordinator" in all_roles:
        redirect_url = "/coordinator/dashboard"
        primary_role = "coordinator"
    elif "admin" in all_roles:
        redirect_url = "/admin/dashboard"
        primary_role = "admin"
    else:
        redirect_url = "/main"
        primary_role = all_roles[0] if all_roles else None

    session["role"] = primary_role

    # Create token if user exists (for coordinator dashboard)
    token = None
    if user:
        token = create_access_token(user)
        role_upper = (user.get("role") or user.get("user_type") or "").strip().upper()
        if role_upper in (ROLE_STUDENT, ROLE_ALUMNI):
            updates = {}
            if not user.get("public_slug"):
                name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or "user"
                branch_or_company = user.get("branch") or user.get("branch_code") or ""
                if role_upper == ROLE_ALUMNI:
                    profile = user.get("profile") or {}
                    branch_or_company = branch_or_company or profile.get("current_company") or ""
                base_slug = generate_public_slug(name, branch_or_company or None)
                updates["public_slug"] = ensure_unique_slug(db["users"], base_slug, exclude_user_id=None)
            if not user.get("qr_code_url") and (updates.get("public_slug") or user.get("public_slug")):
                slug = updates.get("public_slug") or user.get("public_slug")
                base_url = (request.host_url or "").rstrip("/") or "https://yourdomain.com"
                qr_path = qr_profile_generate_qr(
                    str(user["_id"]), slug, base_url, app.static_folder
                )
                if qr_path:
                    updates["qr_code_url"] = qr_path
            if updates:
                db["users"].update_one({"_id": user["_id"]}, {"$set": updates})

    # Get user's name for the response
    user_name = None
    if user:
        user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    elif admin:
        user_name = admin.get("name") or f"{admin.get('first_name', '')} {admin.get('last_name', '')}".strip()
    
    return jsonify({
        "message": "Login successful.",
        "redirect": redirect_url,
        "role": primary_role,
        "token": token,
        "roles": all_roles,
        "name": user_name or email,
    }), 200


@app.route("/api/auth/me", methods=["GET"])
def api_auth_me():
    """
    Identity endpoint for both session-based and JWT-based auth.
    When session has admin_email (dashboard selector after admin login), return only roles student and admin.
    """
    if session.get("admin_email"):
        admin = db["admins"].find_one({"email": session["admin_email"]})
        name = (admin.get("name") or f"{admin.get('first_name', '')} {admin.get('last_name', '')}".strip()) if admin else session["admin_email"]
        return jsonify({
            "email": session["admin_email"],
            "name": name or session["admin_email"],
            "roles": ["student", "admin"],
            "role": "admin",
        }), 200
    if "email" in session:
        email = session.get("email")
        user = db["users"].find_one({"email": email})
        if user and user_is_banned(user):
            session.clear()
            return jsonify({"error": ACCOUNT_BANNED_AUTH_MESSAGE}), 401
        if user and is_flagged_invalid_student(user):
            session.clear()
            return jsonify({"error": "Session expired."}), 401
        admin = db["admins"].find_one({"email": email})
        
        user_name = None
        if user:
            user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
        elif admin:
            user_name = admin.get("name") or f"{admin.get('first_name', '')} {admin.get('last_name', '')}".strip()
        
        roles = get_user_roles(email)
        
        return jsonify({
            "email": email,
            "name": user_name or email,
            "roles": roles,
            "role": session.get("selected_role") or (roles[0] if roles else None),
        }), 200
    
    # Fallback to JWT-based auth (for coordinator dashboard)
    user, err = require_jwt()
    if err:
        return err
    return jsonify({
        "email": user.get("email"),
        "role": user.get("user_type"),
        "name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or None,
    }), 200


def extract_cgpa_from_student_doc(student_doc):
    """
    Try to extract a CGPA-like value from a student document.
    We look for common key variations and return a string or None.
    """
    if not student_doc:
        return None
    cgpa_keys = {"cgpa", "c_g_p_a", "c_gpa"}
    for key, value in student_doc.items():
        key_norm = "".join(ch.lower() for ch in str(key) if ch.isalnum())
        if key_norm in cgpa_keys:
            return str(value)
    # Fallback: look for "SGPA / CGPA"-style fields if present
    for key in student_doc.keys():
        if "cgpa" in str(key).lower():
            val = student_doc.get(key)
            if val is not None:
                return str(val)
    return None


@app.route("/api/dashboard/overview")
@login_required
@role_required("STUDENT")
def api_dashboard_overview():
    """
    Basic student dashboard overview for the currently logged-in student.
    Returns only real data pulled from MongoDB; if data is missing, fields
    are returned as null so the frontend can show honest empty states.
    """
    if "email" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    users_coll = db["users"]
    user = users_coll.find_one({"email": session.get("email")})
    if not user or user.get("user_type") != "student":
        return jsonify({"error": "Student dashboard available only for student accounts."}), 403

    # Try to enrich with student document (from CSV-backed collection)
    student_doc = None
    roll_number = user.get("roll_number")
    if roll_number:
        student_doc = find_student_by_roll(roll_number)

    # Profile basics
    first_name = user.get("first_name") or ""
    last_name = user.get("last_name") or ""
    full_name = f"{first_name} {last_name}".strip() or None

    profile_doc = user.get("profile") or {}

    # Prefer user-provided CGPA from profile.education over CSV cgpa.
    profile_cgpa = None
    try:
        education_list = profile_doc.get("education") or []
        if education_list and isinstance(education_list, list):
            first_edu = education_list[0] or {}
            profile_cgpa = first_edu.get("cgpa")
    except Exception:
        profile_cgpa = None

    effective_cgpa = profile_cgpa or extract_cgpa_from_student_doc(student_doc)

    profile = {
        "name": full_name,
        "branch": user.get("branch") or None,
        "roll_number": roll_number or None,
        "cgpa": effective_cgpa,
        "location": profile_doc.get("location"),
        "open_to": profile_doc.get("open_to") or [],
    }

    # Saved items & engagement – these collections may or may not exist yet.
    email = user.get("email")
    saved_jobs_count = db["saved_jobs"].count_documents({"user_email": email}) if email else 0
    saved_internships_count = db["saved_internships"].count_documents({"user_email": email}) if email else 0
    joined_webinars_count = db["webinar_registrations"].count_documents({"user_email": email}) if email else 0

    connection_count = db["connections"].count_documents({
        "$or": [
            {"requester_id": user["_id"], "status": CONNECTION_ACCEPTED},
            {"recipient_id": user["_id"], "status": CONNECTION_ACCEPTED},
        ]
    })
    mentor_count = 1 if user.get("mentor_id") is not None else 0

    stats = {
        "saved_jobs": saved_jobs_count,
        "saved_internships": saved_internships_count,
        "joined_webinars": joined_webinars_count,
        "connection_count": connection_count,
        "mentor_count": mentor_count,
    }

    return jsonify({
        "profile": profile,
        "stats": stats,
    }), 200


@app.route("/api/dashboard/placement-news")
@login_required
@role_required("STUDENT")
def api_dashboard_placement_news():
    """
    Placement coordinator announcements for students.
    Returns an array of items; when there are none, the array is empty,
    allowing the frontend to render a clear empty state message.
    """
    if "email" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    coll = db["placement_news"]
    items = []
    for doc in coll.find({}).sort("created_at", -1):
        items.append({
            "id": str(doc.get("_id")),
            "title": doc.get("title"),
            "body": doc.get("body"),
            "created_at": doc.get("created_at").isoformat() if isinstance(doc.get("created_at"), datetime) else None,
            "company": doc.get("company"),
            "tags": doc.get("tags") or [],
        })
    return jsonify({"items": items}), 200


@app.route("/api/dashboard/alumni-posts")
@login_required
@role_required("STUDENT")
def api_dashboard_alumni_posts():
    """
    Alumni posts visible to students.
    Returns an array of posts; when there are none, the array is empty.
    """
    if "email" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    coll = db["alumni_posts"]
    posts = []
    for doc in coll.find({}).sort("created_at", -1):
        author = doc.get("author") or {}
        posts.append({
            "id": str(doc.get("_id")),
            "title": doc.get("title"),
            "body": doc.get("body"),
            "created_at": doc.get("created_at").isoformat() if isinstance(doc.get("created_at"), datetime) else None,
            "author": {
                "name": author.get("name"),
                "role": author.get("role"),
                "company": author.get("company"),
            },
        })
    return jsonify({"posts": posts}), 200


@app.route("/api/dashboard/student-posts")
@login_required
@role_required("STUDENT", "ALUMNI")
def api_dashboard_student_posts():
    """
    Unified dashboard feed for students.
    Includes only MEDIA posts authored by STUDENT/ALUMNI users.
    Reverse chronological order (latest first). Includes like/comment counts and liked status.
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    limit = min(max(int(request.args.get("limit", 10)), 1), 50)
    skip = max(int(request.args.get("skip", 0)), 0)
    posts = []
    cursor = db["posts"].find({}).sort("created_at", -1).skip(skip).limit(limit + 1)
    for doc in cursor:
        author = db["users"].find_one({"_id": doc.get("author_id")})
        author_name = f"{author.get('first_name', '')} {author.get('last_name', '')}".strip() if author else "Unknown"
        role = ((author.get("role") or "STUDENT") if author else "STUDENT").upper()
        # Filter to student/alumni feed only.
        if role not in {"STUDENT", "ALUMNI"}:
            continue
        if author and user_hidden_from_campuslink_discovery(author):
            continue

        media_items = list(doc.get("media") or [])
        media_urls = [str(x).strip() for x in (doc.get("media_urls") or []) if isinstance(x, str) and str(x).strip()]
        media_url = (doc.get("media_url") or "").strip() if isinstance(doc.get("media_url"), str) else None
        if not media_items:
            # Backward compatibility from legacy fields
            for u in media_urls:
                media_items.append({"type": ("video" if u.lower().endswith(".mp4") else "image"), "url": u})
            if media_url and media_url not in media_urls:
                media_items.insert(0, {"type": ("video" if media_url.lower().endswith(".mp4") else "image"), "url": media_url})
        # Media-only posts (exclude text-only / empty)
        if not media_items:
            continue

        content = doc.get("content") or doc.get("description") or ""
        title = doc.get("title") or ""
        post_id = doc.get("_id")
        inter = _serialize_post_interaction_fields(doc, user)
        posts.append({
            "id": str(post_id),
            "author_id": str(doc.get("author_id")),
            "author_name": author_name,
            "author": {"name": author_name, "role": role},
            "author_profile_photo": _user_profile_photo_url(author),
            "branch": (author.get("branch_code") or author.get("branch") or "") if author else "",
            "title": title,
            "content": content,
            "description": content,
            "body": content,
            "feed_label": doc.get("feed_label") or "",
            "post_type": doc.get("post_type") or "text",
            "media_url": media_url,
            "media_urls": media_urls,
            "media": media_items,
            "hashtags": doc.get("hashtags") or [],
            "tagged_users": [str(x) for x in (doc.get("tagged_users") or []) if x],
            "tagged_user_info": doc.get("tagged_user_info") or [],
            "likes_count": inter["likes_count"],
            "comments_count": inter["comments_count"],
            "liked": inter["liked"],
            "settings": inter["settings"],
            "likes_count_hidden": inter["likes_count_hidden"],
            "comments_count_hidden": inter["comments_count_hidden"],
            "created_at": doc.get("created_at").isoformat() if isinstance(doc.get("created_at"), datetime) else None,
        })
    has_more = len(posts) > limit
    posts = posts[:limit]
    return jsonify({
        "posts": posts,
        "has_more": has_more,
        "next_skip": skip + len(posts),
        "current_user_id": str(user.get("_id")),
    }), 200


@app.route("/api/dashboard/important-notices")
@app.route("/api/announcements/feed", methods=["GET"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_announcements_feed():
    """
    Announcements for the logged-in student or alumni: audience must include their role.
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    coll = db["announcements"]
    items = []
    for doc in coll.find({}).sort([("created_at", -1), ("date", -1)]).limit(80):
        if not _announcement_matches_user(doc, user):
            continue
        items.append(_serialize_announcement_doc(doc))
        if len(items) >= 20:
            break
    return jsonify({"items": items}), 200


@app.route("/api/announcements/manage", methods=["GET"])
def api_announcements_manage():
    """List all announcements (admin, coordinator, faculty). Session or JWT."""
    user, err = get_session_or_jwt_user()
    if err:
        return err
    if not user_can_create_announcements(user):
        return jsonify({"error": "Forbidden"}), 403
    items = []
    for doc in db["announcements"].find({}).sort([("created_at", -1), ("date", -1)]).limit(200):
        items.append(_serialize_announcement_doc(doc))
    return jsonify({"items": items}), 200


@app.route("/api/announcements", methods=["POST"])
def api_announcements_create():
    """Create announcement (admin, coordinator, faculty). Session or JWT. multipart or JSON."""
    user, err = get_session_or_jwt_user()
    if err:
        return err
    if not user_can_create_announcements(user):
        return jsonify({"error": "Forbidden"}), 403

    title = ""
    description = ""
    audience_raw = None
    uploaded_media: list[dict] = []

    if request.content_type and "multipart/form-data" in request.content_type:
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        audience_raw = request.form.getlist("audience") or request.form.get("audience_json")
        if isinstance(audience_raw, list) and len(audience_raw) == 1 and audience_raw[0] and audience_raw[0].startswith("["):
            audience_raw = audience_raw[0]
        uploaded_media, m_err = _upload_announcement_media_files_from_request()
        if m_err:
            return jsonify({"error": m_err}), 400
    else:
        data = request.get_json(silent=True) or {}
        title = (data.get("title") or "").strip()
        description = (data.get("description") or "").strip()
        audience_raw = data.get("audience")

    if not title:
        return jsonify({"error": "Title is required"}), 400
    if not description:
        return jsonify({"error": "Description is required"}), 400

    audience, aud_err = _normalize_audience_payload(audience_raw)
    if aud_err:
        return jsonify({"error": aud_err}), 400
    if not audience:
        return jsonify({"error": "Select at least one audience (Student, Faculty, or Alumni)."}), 400

    now = datetime.utcnow()
    cr = _creator_role_normalized(user)
    doc = {
        "title": title,
        "description": description,
        "audience": audience,
        "visibility": "all",
        "created_by": user.get("email"),
        "created_by_email": user.get("email"),
        "created_by_name": _user_display_name(user),
        "creator_role": cr,
        "role": cr,
        "created_at": now,
        "date": now,
    }
    if uploaded_media:
        doc["media"] = uploaded_media
        doc["media_urls"] = [m["url"] for m in uploaded_media]
        doc["media_url"] = uploaded_media[0]["url"]
    res = db["announcements"].insert_one(doc)
    doc["_id"] = res.inserted_id
    fan_out_announcement_notifications(
        res.inserted_id,
        audience,
        title,
        user.get("email"),
    )
    return jsonify({"announcement": _serialize_announcement_doc(doc)}), 201


@app.route("/api/search/users")
@login_required
def api_search_users():
    """
    Search for registered users by name (prefix match).
    Query: q (required), type=students|alumni|all (default all for logged-in user search).
    """
    me = get_logged_in_user()
    if not me:
        return jsonify({"error": "Not authenticated"}), 401

    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"users": []}), 200

    type_filter = (request.args.get("type") or "all").strip().lower()
    coll = db["users"]
    users = []

    escaped_query = re.escape(query)
    pattern = {"$regex": f"^{escaped_query}", "$options": "i"}

    for doc in coll.find({
        "$or": [
            {"first_name": pattern},
            {"last_name": pattern},
            {"name": pattern}
        ]
    }).limit(40):
        if (doc.get("role") or "").strip().upper() == ROLE_FACULTY or (doc.get("user_type") or "").strip().lower() == "faculty":
            continue
        if (doc.get("role") or "").strip().upper() == ROLE_COORDINATOR or (doc.get("user_type") or "").strip().lower() == "coordinator":
            continue
        ut = (doc.get("user_type") or "").strip().lower()
        r = (doc.get("role") or "").strip().upper()
        is_student = ut == "student" or r == ROLE_STUDENT
        is_alumni = ut == "alumni" or r == ROLE_ALUMNI
        if type_filter == "students" and not is_student:
            continue
        if type_filter == "alumni" and not is_alumni:
            continue
        if user_hidden_from_campuslink_discovery(doc):
            continue
        users.append({
            "id": str(doc.get("_id")),
            "name": doc.get("name") or f"{doc.get('first_name', '')} {doc.get('last_name', '')}".strip(),
            "email": doc.get("email", ""),
            "branch": doc.get("branch") or doc.get("branch_code") or "",
            "roll_number": doc.get("roll_number", ""),
            "role": (doc.get("role") or "STUDENT").upper(),
            "user_type": ut or ("student" if is_student else "alumni" if is_alumni else ""),
        })
        if len(users) >= 10:
            break
    return jsonify({"users": users}), 200


@app.route("/api/posts/mentions")
@login_required
def api_posts_mentions():
    """
    Mention suggestions for post composer.
    Includes only STUDENT + ALUMNI users.
    """
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"users": []}), 200
    escaped_query = re.escape(q)
    pattern = {"$regex": escaped_query, "$options": "i"}
    users = []
    for doc in db["users"].find({
        "$and": [
            {"role": {"$in": ["STUDENT", "ALUMNI"]}},
            {"$or": [{"first_name": pattern}, {"last_name": pattern}, {"name": pattern}]},
        ]
    }).limit(8):
        if user_hidden_from_campuslink_discovery(doc):
            continue
        full_name = f"{doc.get('first_name', '')} {doc.get('last_name', '')}".strip() or (doc.get("name") or "User")
        users.append({
            "id": str(doc.get("_id")),
            "name": full_name,
            "role": (doc.get("role") or "").upper(),
        })
    return jsonify({"users": users}), 200


@app.route("/api/profile", methods=["GET", "PUT"])
def api_profile():
    """
    Get or update the current logged-in user's profile details.
    Data is stored inside the existing users document so that
    there is a single source of truth per user.
    """
    if "email" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    users_coll = db["users"]
    user = users_coll.find_one({"email": session.get("email")})
    if not user:
        return jsonify({"error": "User not found"}), 404

    if request.method == "GET":
        profile = user.get("profile") or {}
        # Build a copy of list sections for sorting (do not mutate stored profile)
        profile_data = {
            "education": list(profile.get("education") or []),
            "experience": list(profile.get("experience") or []),
            "projects": list(profile.get("projects") or []),
            "clubs": list(profile.get("clubs") or []),
            "certifications": list(profile.get("certifications") or []),
            "achievements": list(profile.get("achievements") or []),
        }
        sort_profile_sections_reverse_chronological(profile_data)
        basic = {
            "first_name": user.get("first_name"),
            "last_name": user.get("last_name"),
            "full_name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or None,
            "headline": profile.get("headline"),
            "location": profile.get("location"),
            "open_to": profile.get("open_to") or [],
        }
        return jsonify({
            "basic": basic,
            "education": profile_data["education"],
            "experience": profile_data["experience"],
            "projects": profile_data["projects"],
            "skills": profile.get("skills") or [],
            "clubs": profile_data["clubs"],
            "certifications": profile_data["certifications"],
        }), 200

    # PUT – update profile
    data = request.get_json(silent=True) or {}

    basic = data.get("basic") or {}

    full_name = (basic.get("full_name") or "").strip()
    first_name = (basic.get("first_name") or "").strip()
    last_name = (basic.get("last_name") or "").strip()

    if full_name and not (first_name or last_name):
        # Derive first/last from full name if only that is provided.
        parts = full_name.split()
        first_name = parts[0]
        last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

    update_fields = {}
    if first_name:
        update_fields["first_name"] = first_name
    if last_name:
        update_fields["last_name"] = last_name

    profile = {
        "headline": _clean_str(basic.get("headline"), 200) or None,
        "location": _clean_str(basic.get("location"), 200) or None,
        "open_to": _canonical_open_to(basic.get("open_to") or []),
        "education": data.get("education") or [],
        "experience": data.get("experience") or [],
        "projects": data.get("projects") or [],
        "skills": data.get("skills") or [],
        "clubs": data.get("clubs") or [],
        "certifications": data.get("certifications") or [],
    }

    update_fields["profile"] = profile

    users_coll.update_one(
        {"_id": user["_id"]},
        {"$set": update_fields}
    )

    return jsonify({"message": "Profile updated."}), 200


# ---------- Student Profile Module (modal CRUD) ----------
def _profile_for_user(user: dict) -> dict:
    profile = user.get("profile") or {}
    # Ensure expected arrays exist (safe defaults)
    profile.setdefault("education", [])
    profile.setdefault("experience", [])  # internships/work
    profile.setdefault("projects", [])
    profile.setdefault("skills", [])
    profile.setdefault("clubs", [])
    profile.setdefault("resume", user.get("profile", {}).get("resume") if isinstance(user.get("profile"), dict) else None)
    profile.setdefault("basic", {
        "headline": (profile.get("headline") if isinstance(profile.get("headline"), str) else None),
        "location": (profile.get("location") if isinstance(profile.get("location"), str) else None),
        "open_to": profile.get("open_to") or [],
    })
    return profile


def _save_profile(user: dict, profile: dict):
    profile = _strip_media_references_from_profile(profile)
    if (user.get("user_type") or "").strip().lower() == "alumni":
        completion = calculate_alumni_profile_completion(profile, {**user, "profile": profile})
    else:
        completion = calculate_profile_completion(profile)
    db["users"].update_one(
        {"_id": user["_id"]},
        {"$set": {"profile": profile, "profile_completion": completion}}
    )
    return completion


@app.route("/api/student/profile", methods=["GET"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_student_profile_get():
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    profile = _profile_for_user(user)
    # Interests are intentionally not part of the Edit Profile/back-end anymore.
    profile.pop("interests", None)
    profile_data = {
        "education": list(profile.get("education") or []),
        "experience": list(profile.get("experience") or []),
        "projects": list(profile.get("projects") or []),
        "clubs": list(profile.get("clubs") or []),
        "certifications": list(profile.get("certifications") or []),
        "achievements": list(profile.get("achievements") or []),
    }
    sort_profile_sections_reverse_chronological(profile_data)
    for key in profile_data:
        profile[key] = profile_data[key]
    completion = user.get("profile_completion")
    try:
        completion = int(completion) if completion is not None else calculate_profile_completion(profile)
    except Exception:
        completion = calculate_profile_completion(profile)

    return jsonify({
        "basic_user": {
            "id": str(user.get("_id")),
            "first_name": user.get("first_name"),
            "last_name": user.get("last_name"),
            "full_name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or None,
            "email": user.get("email"),
            "branch_code": user.get("branch_code") or user.get("branch"),
        },
        "verification_status": user.get("verification_status"),
        "profile_completion": completion,
        "profile": profile,
    }), 200


@app.route("/api/student/profile/basic", methods=["PUT"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_student_profile_basic_put():
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json(silent=True) or {}
    basic = data.get("basic") or {}

    profile = _profile_for_user(user)

    # Keep backward compatibility with existing profile shape
    headline = _clean_str(basic.get("headline"), 200)
    location = _clean_str(basic.get("location"), 200)
    open_to = _canonical_open_to(basic.get("open_to") or [])

    profile["headline"] = headline
    profile["location"] = location
    profile["open_to"] = open_to
    profile["basic"] = {"headline": headline, "location": location, "open_to": open_to}

    completion = _save_profile(user, profile)
    return jsonify({"message": "Basic info updated.", "profile_completion": completion}), 200


def _add_item(profile: dict, key: str, item: dict) -> dict:
    item = dict(item or {})
    item.setdefault("id", str(uuid.uuid4()))
    if key not in profile or not isinstance(profile.get(key), list):
        profile[key] = []
    profile[key].append(item)
    return item


def _update_item(profile: dict, key: str, item_id: str, patch: dict) -> dict | None:
    arr = profile.get(key) if isinstance(profile.get(key), list) else []
    for idx, it in enumerate(arr):
        if str(it.get("id")) == str(item_id):
            updated = dict(it)
            updated.update(patch or {})
            updated["id"] = str(updated.get("id") or item_id)
            arr[idx] = updated
            profile[key] = arr
            return updated
    return None


def _delete_item(profile: dict, key: str, item_id: str) -> bool:
    arr = profile.get(key) if isinstance(profile.get(key), list) else []
    before = len(arr)
    arr = [it for it in arr if str(it.get("id")) != str(item_id)]
    profile[key] = arr
    return len(arr) != before


def migrate_existing_user_media_folders(dry_run: bool = False, limit: int | None = None):
    return {"checked_users": 0, "updated_users": 0, "moved_assets": 0, "dry_run": dry_run, "errors": [], "error_count": 0}


def migrate_existing_post_media_folders(dry_run: bool = False, limit: int | None = None):
    return {"checked_posts": 0, "moved_assets": 0, "dry_run": dry_run, "errors": [], "error_count": 0}


def _profile_highlight_media_url(post_type: str, item: dict) -> str | None:
    """Image (or primary media URL) required for dashboard feed visibility."""
    item = item or {}
    if post_type == "certification":
        u = _clean_str(item.get("media_url"))
        return u or None
    if post_type == "achievement":
        u = _clean_str(item.get("media_url"))
        return u or None
    if post_type == "internship":
        u = _clean_str(item.get("media_url")) or _clean_str(item.get("completion_certificate_url"))
        return u or None
    return None


def _profile_highlight_description(post_type: str, item: dict) -> str | None:
    item = item or {}
    d = _clean_str(item.get("description"))
    return d or None


def _highlight_post_type_stored(post_type: str) -> str:
    if post_type == "certification":
        return "certificate"
    return post_type


def _highlight_feed_label(post_type: str) -> str:
    return {
        "certification": "Certificate Achievement",
        "achievement": "Achievement",
        "internship": "Internship",
    }.get(post_type, "Update")


def _build_highlight_post_content(post_type: str, item: dict) -> tuple[str, str]:
    """
    Returns (content, activity_preview).
    """
    item = item or {}
    if post_type == "certification":
        name = _clean_str(item.get("name")) or "Certificate"
        desc = _clean_str(item.get("description")) or ""
        issuer = _clean_str(item.get("issuer")) or ""
        head = f"{name} - {desc}" if desc else name
        lines = [head]
        if issuer:
            lines.append("")
            lines.append(f"Issued by {issuer}")
        if item.get("issue_date"):
            lines.append(str(item.get("issue_date")).strip())
        content = "\n".join(lines).strip()
        return content, head[:100]
    if post_type == "achievement":
        title = _clean_str(item.get("title")) or "Achievement"
        desc = _clean_str(item.get("description")) or ""
        assoc = _clean_str(item.get("associated_with") or item.get("issuer")) or ""
        head = f"{title} - {desc}" if desc else title
        lines = [head]
        if assoc:
            lines.append("")
            lines.append(f"Associated with {assoc}")
        if item.get("date"):
            lines.append(str(item.get("date")).strip())
        content = "\n".join(lines).strip()
        return content, head[:100]
    if post_type == "internship":
        company = _clean_str(item.get("company")) or "Company"
        role = _clean_str(item.get("role")) or ""
        desc = _clean_str(item.get("description")) or ""
        head = f"Internship at {company} - {desc}" if desc else f"Internship at {company}"
        lines = [head]
        if role:
            lines.append("")
            lines.append(role)
        if item.get("duration"):
            lines.append(str(item.get("duration")).strip())
        content = "\n".join(lines).strip()
        return content, head[:100]
    return "", "Post"


def create_certificate_post(user: dict, certificate: dict) -> ObjectId:
    """
    Insert a feed post for a certification (certificate) item.
    Expects certificate to include id, name, description, issuer, media_url, issue_date (optional).
    """
    if not _profile_highlight_media_url("certification", certificate) or not _profile_highlight_description(
        "certification", certificate
    ):
        raise ValueError("Certificate posts require media_url and description.")
    return _insert_profile_highlight_post(user, "certification", certificate, "certifications")


def _insert_profile_highlight_post(user: dict, post_type: str, item: dict, profile_section: str) -> ObjectId:
    """post_type: certification | achievement | internship"""
    media_url = _profile_highlight_media_url(post_type, item)
    desc = _profile_highlight_description(post_type, item)
    if not media_url or not desc:
        raise ValueError("Highlight posts require media and description.")
    content, preview = _build_highlight_post_content(post_type, item)
    stored_type = _highlight_post_type_stored(post_type)
    title_fallback = (
        _clean_str(item.get("name"))
        or _clean_str(item.get("title"))
        or _clean_str(item.get("company"))
        or "Update"
    )
    post_doc = {
        "author_id": user["_id"],
        "post_type": stored_type,
        "reference_type": profile_section,
        "reference_id": item.get("id"),
        "feed_label": _highlight_feed_label(post_type),
        "title": title_fallback,
        "description": content[:2000],
        "content": content[:2000],
        "media_url": media_url,
        "media_urls": [media_url],
        "media": [{"type": "image", "url": media_url}],
        "likes_count": 0,
        "comments_count": 0,
        "created_at": datetime.utcnow(),
    }
    result = db["posts"].insert_one(post_doc)
    create_activity(
        user["_id"],
        ACTIVITY_TYPE_POST,
        result.inserted_id,
        "post",
        {"content_preview": preview, "post_type": stored_type},
    )
    return result.inserted_id


def _maybe_create_profile_highlight_post(
    user: dict, post_type: str, item: dict, profile_section: str
) -> tuple[bool, str | None]:
    """
    Create at most one feed post per profile item when both media and description exist.
    Sets item['post_created'] and item['post_id'] on success.
    post_type: certification | achievement | internship
    """
    if not item or item.get("post_created"):
        return False, None
    media_url = _profile_highlight_media_url(post_type, item)
    desc = _profile_highlight_description(post_type, item)
    if not media_url or not desc:
        return False, None
    post_id = _insert_profile_highlight_post(user, post_type, item, profile_section)
    item["post_created"] = True
    item["post_id"] = str(post_id)
    msg = {
        "certification": "Your certificate has been shared as a post.",
        "achievement": "Your achievement has been shared as a post.",
        "internship": "Your internship has been shared as a post.",
    }.get(post_type)
    return True, msg


def _create_post_for_item(user: dict, post_type: str, item: dict, profile_section: str):
    """
    Auto-create a feed post for projects (legacy behavior).
    Certifications, achievements, and internships use _maybe_create_profile_highlight_post instead.
    """
    title = ""
    description = ""
    media_url = item.get("media_url") or (item.get("media_urls") or [None])[0] or item.get("project_video_url")
    if post_type == "project":
        title = f"Project: {item.get('name') or 'Project'}"
        description = (item.get("tech_stack") or "") + (" · " + (item.get("link") or "")) if (item.get("tech_stack") or item.get("link")) else (item.get("description") or "")[:300]
    else:
        raise ValueError(f"_create_post_for_item only supports project posts, not {post_type!r}")
    if not title:
        title = f"New {post_type}"
    post_doc = {
        "author_id": user["_id"],
        "post_type": post_type,
        "reference_type": profile_section,
        "reference_id": item.get("id"),
        "title": title,
        "description": (description or "")[:500],
        "content": (description or "")[:500],
        "media_url": media_url or None,
        "likes_count": 0,
        "comments_count": 0,
        "created_at": datetime.utcnow(),
    }
    result = db["posts"].insert_one(post_doc)
    create_activity(
        user["_id"],
        ACTIVITY_TYPE_POST,
        result.inserted_id,
        "post",
        {"content_preview": title[:100], "post_type": post_type},
    )
    return result.inserted_id


@app.route("/api/student/profile/education", methods=["POST"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_student_profile_education_post():
    user = get_logged_in_user()
    profile = _profile_for_user(user)
    data = request.get_json(silent=True) or {}
    raw_item = data.get("item") or {}
    item = _add_item(profile, "education", _normalize_education_item(raw_item))
    completion = _save_profile(user, profile)
    return jsonify({"item": item, "profile_completion": completion}), 201


@app.route("/api/student/profile/education/<item_id>", methods=["PUT", "DELETE"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_student_profile_education_item(item_id):
    user = get_logged_in_user()
    profile = _profile_for_user(user)
    if request.method == "PUT":
        data = request.get_json(silent=True) or {}
        raw_item = data.get("item") or {}
        updated = _update_item(profile, "education", item_id, _normalize_education_item(raw_item))
        if not updated:
            return jsonify({"error": "Education item not found"}), 404
        completion = _save_profile(user, profile)
        return jsonify({"item": updated, "profile_completion": completion}), 200

    deleted = _delete_item(profile, "education", item_id)
    if not deleted:
        return jsonify({"error": "Education item not found"}), 404
    completion = _save_profile(user, profile)
    return jsonify({"message": "Deleted", "profile_completion": completion}), 200


# Internships stored as profile.experience (keeps compatibility with existing /api/profile)
def _parse_internship_item_from_request(user: dict) -> tuple[dict, str | None]:
    """
    Parse internship item from JSON or multipart/form-data.
    Supports optional uploads:
    - offer_letter (jpg/png, max 5MB) -> offer_letter_url
    - completion_certificate (jpg/png, max 5MB) -> completion_certificate_url
    """
    if request.content_type and "multipart/form-data" in request.content_type:
        f = request.form
        skills_raw = (f.get("skills") or "").strip()
        skills_out: list[str] = []
        if skills_raw:
            try:
                parsed = json.loads(skills_raw)
                if isinstance(parsed, list):
                    for s in parsed:
                        cs = _clean_str(s, 80)
                        if cs:
                            skills_out.append(cs)
                elif isinstance(parsed, str):
                    for s in parsed.split(","):
                        cs = _clean_str(s, 80)
                        if cs:
                            skills_out.append(cs)
            except Exception:
                for s in skills_raw.split(","):
                    cs = _clean_str(s, 80)
                    if cs:
                        skills_out.append(cs)
        item: dict = {
            "company": (f.get("company") or "").strip(),
            "role": (f.get("role") or "").strip(),
            "employment_type": (f.get("employment_type") or "").strip(),
            "current": (f.get("current") or "").strip(),
            "start_month": (f.get("start_month") or "").strip(),
            "start_year": (f.get("start_year") or "").strip(),
            "start_date": (f.get("start_date") or "").strip(),
            "end_month": (f.get("end_month") or "").strip(),
            "end_year": (f.get("end_year") or "").strip(),
            "end_date": (f.get("end_date") or "").strip(),
            "location": (f.get("location") or "").strip(),
            "location_type": (f.get("location_type") or "").strip(),
            "description": (f.get("description") or "").strip(),
            "skills": skills_out,
        }
        offer_letter = request.files.get("offer_letter")
        if offer_letter and offer_letter.filename:
            url, err = _upload_profile_highlight_image(offer_letter, user, "offer_letter")
            if err:
                return {}, err
            if url:
                item["offer_letter_url"] = url
        completion_certificate = request.files.get("completion_certificate")
        if completion_certificate and completion_certificate.filename:
            url, err = _upload_profile_highlight_image(completion_certificate, user, "completion_certificate")
            if err:
                return {}, err
            if url:
                item["completion_certificate_url"] = url
        return item, None
    data = request.get_json(silent=True) or {}
    return (data.get("item") or {}), None


@app.route("/api/student/profile/internships", methods=["POST"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_student_profile_internships_post():
    user = get_logged_in_user()
    profile = _profile_for_user(user)
    raw_item, parse_err = _parse_internship_item_from_request(user)
    if parse_err:
        return jsonify({"error": parse_err}), 400
    item = raw_item if isinstance(raw_item, dict) else {}

    item = _add_item(profile, "experience", _normalize_experience_item(item))
    feed_post_created, feed_post_message = _maybe_create_profile_highlight_post(
        user, "internship", item, "experience"
    )
    completion = _save_profile(user, profile)
    return jsonify(
        {
            "item": item,
            "profile_completion": completion,
            "feed_post_created": feed_post_created,
            "feed_post_message": feed_post_message,
        }
    ), 201


@app.route("/api/student/profile/internships/<item_id>", methods=["PUT", "DELETE"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_student_profile_internships_item(item_id):
    user = get_logged_in_user()
    profile = _profile_for_user(user)
    if request.method == "PUT":
        raw_item, parse_err = _parse_internship_item_from_request(user)
        if parse_err:
            return jsonify({"error": parse_err}), 400
        if not isinstance(raw_item, dict):
            raw_item = {}
        updated = _update_item(profile, "experience", item_id, _normalize_experience_item(raw_item))
        if not updated:
            return jsonify({"error": "Internship item not found"}), 404
        feed_post_created, feed_post_message = _maybe_create_profile_highlight_post(
            user, "internship", updated, "experience"
        )
        completion = _save_profile(user, profile)
        return jsonify(
            {
                "item": updated,
                "profile_completion": completion,
                "feed_post_created": feed_post_created,
                "feed_post_message": feed_post_message,
            }
        ), 200

    deleted = _delete_item(profile, "experience", item_id)
    if not deleted:
        return jsonify({"error": "Internship item not found"}), 404
    completion = _save_profile(user, profile)
    return jsonify({"message": "Deleted", "profile_completion": completion}), 200


def _parse_project_item_from_request(user: dict) -> tuple[dict, str | None]:
    """
    Parse project item from JSON or multipart/form-data.
    Supports optional uploads:
    - project_image (jpg/png, max 5MB) -> appended as single entry in media_urls
    - project_video (mp4, max 50MB) -> project_video_url
    """
    if request.content_type and "multipart/form-data" in request.content_type:
        f = request.form
        item: dict = {
            "name": (f.get("name") or "").strip(),
            "tech_stack": (f.get("tech_stack") or "").strip(),
            "link": (f.get("link") or "").strip(),
            "role": (f.get("role") or "").strip(),
            "description": (f.get("description") or "").strip(),
        }
        img = request.files.get("project_image")
        if img and img.filename:
            url, kind, err = _upload_user_media(
                img,
                user,
                "projects",
                allow_images=True,
                allow_videos=False,
                allow_docs=False,
                public_id_prefix="project_image",
            )
            if err:
                return {}, err
            if url and kind == "image":
                item["media_urls"] = [url]
        vid = request.files.get("project_video")
        if vid and vid.filename:
            url, kind, err = _upload_user_media(
                vid,
                user,
                "projects",
                allow_images=False,
                allow_videos=True,
                allow_docs=False,
                public_id_prefix="project_video",
            )
            if err:
                return {}, err
            if url and kind == "video":
                item["project_video_url"] = url
        return item, None
    data = request.get_json(silent=True) or {}
    return (data.get("item") or {}), None


@app.route("/api/student/profile/projects", methods=["POST"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_student_profile_projects_post():
    user = get_logged_in_user()
    profile = _profile_for_user(user)
    item, parse_err = _parse_project_item_from_request(user)
    if parse_err:
        return jsonify({"error": parse_err}), 400
    if not isinstance(item, dict):
        item = {}
    item = _add_item(profile, "projects", item)
    completion = _save_profile(user, profile)
    _create_post_for_item(user, "project", item, "projects")
    return jsonify({"item": item, "profile_completion": completion}), 201


@app.route("/api/student/profile/projects/<item_id>", methods=["PUT", "DELETE"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_student_profile_projects_item(item_id):
    user = get_logged_in_user()
    profile = _profile_for_user(user)
    if request.method == "PUT":
        raw_item, parse_err = _parse_project_item_from_request(user)
        if parse_err:
            return jsonify({"error": parse_err}), 400
        if not isinstance(raw_item, dict):
            raw_item = {}
        updated = _update_item(profile, "projects", item_id, raw_item)
        if not updated:
            return jsonify({"error": "Project item not found"}), 404
        completion = _save_profile(user, profile)
        return jsonify({"item": updated, "profile_completion": completion}), 200

    deleted = _delete_item(profile, "projects", item_id)
    if not deleted:
        return jsonify({"error": "Project item not found"}), 404
    completion = _save_profile(user, profile)
    return jsonify({"message": "Deleted", "profile_completion": completion}), 200


@app.route("/api/student/profile/skills", methods=["POST"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_student_profile_skills_post():
    user = get_logged_in_user()
    profile = _profile_for_user(user)
    data = request.get_json(silent=True) or {}
    raw_item = data.get("item") or {}
    item = _add_item(profile, "skills", _normalize_skill_item(raw_item))
    completion = _save_profile(user, profile)
    return jsonify({"item": item, "profile_completion": completion}), 201


@app.route("/api/student/profile/skills/<item_id>", methods=["PUT", "DELETE"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_student_profile_skills_item(item_id):
    user = get_logged_in_user()
    profile = _profile_for_user(user)
    if request.method == "PUT":
        data = request.get_json(silent=True) or {}
        raw_item = data.get("item") or {}
        updated = _update_item(profile, "skills", item_id, _normalize_skill_item(raw_item))
        if not updated:
            return jsonify({"error": "Skill not found"}), 404
        completion = _save_profile(user, profile)
        return jsonify({"item": updated, "profile_completion": completion}), 200

    deleted = _delete_item(profile, "skills", item_id)
    if not deleted:
        return jsonify({"error": "Skill not found"}), 404
    completion = _save_profile(user, profile)
    return jsonify({"message": "Deleted", "profile_completion": completion}), 200


@app.route("/api/student/profile/clubs", methods=["POST"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_student_profile_clubs_post():
    user = get_logged_in_user()
    profile = _profile_for_user(user)
    data = request.get_json(silent=True) or {}
    raw_item = data.get("item") or {}
    norm = _normalize_alumni_council_item if (user.get("user_type") or "").lower() == "alumni" else _normalize_club_item
    item = _add_item(profile, "clubs", norm(raw_item))
    completion = _save_profile(user, profile)
    return jsonify({"item": item, "profile_completion": completion}), 201


@app.route("/api/student/profile/clubs/<item_id>", methods=["PUT", "DELETE"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_student_profile_clubs_item(item_id):
    user = get_logged_in_user()
    profile = _profile_for_user(user)
    if request.method == "PUT":
        data = request.get_json(silent=True) or {}
        raw_item = data.get("item") or {}
        norm = _normalize_alumni_council_item if (user.get("user_type") or "").lower() == "alumni" else _normalize_club_item
        updated = _update_item(profile, "clubs", item_id, norm(raw_item))
        if not updated:
            return jsonify({"error": "Club item not found"}), 404
        completion = _save_profile(user, profile)
        return jsonify({"item": updated, "profile_completion": completion}), 200

    deleted = _delete_item(profile, "clubs", item_id)
    if not deleted:
        return jsonify({"error": "Club item not found"}), 404
    completion = _save_profile(user, profile)
    return jsonify({"message": "Deleted", "profile_completion": completion}), 200


# ---------- Coordinator dashboard (JWT protected) ----------
@app.route("/coordinator/dashboard")
@login_required
def coordinator_dashboard():
    if "email" not in session:
        return redirect(url_for("login_page"))
    
    # Roles from session (set at login; same for normal and post-reset login)
    user_roles = session.get("roles", [])
    if not user_roles:
        user_roles = get_user_roles(session.get("email"))
        session["roles"] = user_roles
    
    # Use primary role from login so we don't send users to selector when they were already sent here
    effective_role = session.get("selected_role") or session.get("role")
    if len(user_roles) > 1 and not effective_role:
        return redirect(url_for("dashboard_selector"))
    
    # Allow access if login set role to coordinator or user has coordinator role
    if effective_role == "coordinator" or "coordinator" in user_roles:
        return send_from_directory(app.static_folder, "coordinator_dashboard.html")
    
    flash("You do not have access to the coordinator dashboard.", "danger")
    if len(user_roles) > 1:
        return redirect(url_for("dashboard_selector"))
    return redirect(url_for("main"))


# ---------- Alumni dashboard (session + JWT for API) ----------
@app.route("/faculty/dashboard")
@login_required
@faculty_required
def faculty_dashboard():
    return send_from_directory(app.static_folder, "faculty_dashboard.html")


def _faculty_department_scope(faculty_user: dict):
    """Return query filter for students in faculty's department only. None if faculty has no branch."""
    dept = normalize_branch_code(faculty_user.get("branch_code") or faculty_user.get("branch"))
    if not dept:
        return None
    return {
        "user_type": "student",
        "$or": [{"branch_code": dept}, {"branch": dept}],
    }


def _faculty_student_branch_matches(faculty_user: dict, student_doc: dict) -> bool:
    dept = normalize_branch_code(faculty_user.get("branch_code") or faculty_user.get("branch"))
    if not dept:
        return False
    s = normalize_branch_code(student_doc.get("branch_code") or student_doc.get("branch"))
    return bool(s and s == dept)


@app.route("/api/faculty/students", methods=["GET"])
@login_required
@faculty_required
def api_faculty_students():
    """List students in faculty's department only."""
    faculty = get_logged_in_user()
    if not faculty:
        return jsonify({"error": "Not authenticated"}), 401
    status_filter = (request.args.get("status") or "").strip().upper()
    query = _faculty_department_scope(faculty)
    if query is None:
        return jsonify({
            "error": "Your faculty profile has no branch assigned. Contact an administrator.",
            "students": [],
        }), 403
    if status_filter in ("PENDING", "VERIFIED", "REJECTED", "NEEDS_CORRECTION"):
        query["verification_status"] = status_filter
    items = []
    for doc in db["users"].find(query).sort("created_at", -1):
        profile = doc.get("profile") or {}
        cgpa = None
        if profile.get("education") and isinstance(profile["education"], list) and profile["education"]:
            cgpa = (profile["education"][0] or {}).get("cgpa")
        items.append({
            "id": str(doc.get("_id")),
            "name": f"{doc.get('first_name', '')} {doc.get('last_name', '')}".strip(),
            "email": doc.get("email"),
            "branch": doc.get("branch_code") or doc.get("branch"),
            "verification_status": doc.get("verification_status") or VERIFICATION_PENDING,
            "profile_completion": int(doc.get("profile_completion") or 0),
            "cgpa": cgpa,
        })
    return jsonify({"students": items}), 200


MIN_PROFILE_COMPLETION_FOR_VERIFY = 50


@app.route("/api/faculty/students/<student_id>/verify", methods=["POST"])
@login_required
@faculty_required
def api_faculty_student_verify(student_id):
    """Faculty: set profile verification status (verified / needs_correction / rejected). Requires profile completion >= 50%."""
    faculty = get_logged_in_user()
    if not faculty:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        oid = ObjectId(student_id)
    except Exception:
        return jsonify({"error": "Invalid student id"}), 400
    query = _faculty_department_scope(faculty)
    if query is None:
        return jsonify({"error": "Your faculty profile has no branch assigned."}), 403
    query["_id"] = oid
    student = db["users"].find_one(query)
    if not student:
        return jsonify({"error": "Student not found in your department"}), 404
    if not _faculty_student_branch_matches(faculty, student):
        return jsonify({"error": "Student branch does not match your branch."}), 403
    if user_is_banned(student):
        return jsonify({"error": "This account has been permanently banned."}), 400
    completion = int(student.get("profile_completion") or 0)
    if completion < MIN_PROFILE_COMPLETION_FOR_VERIFY:
        return jsonify({"error": "Profile must be at least 50% complete to verify."}), 400
    data = request.get_json(silent=True) or {}
    status = (data.get("status") or "").strip().upper()
    remark = (data.get("remark") or "").strip() or None
    if status not in (VERIFICATION_VERIFIED, VERIFICATION_REJECTED, VERIFICATION_NEEDS_CORRECTION):
        return jsonify({"error": "status must be VERIFIED, REJECTED, or NEEDS_CORRECTION"}), 400
    verified_flag = status == VERIFICATION_VERIFIED
    set_doc = {
        "verification_status": status,
        "verification_remark": remark,
        "verification_updated_at": datetime.utcnow(),
        "verification_by": faculty.get("email"),
        "is_verified": verified_flag,
    }
    if status == VERIFICATION_REJECTED:
        set_doc["is_banned"] = True
        set_doc["account_status"] = "rejected"
        set_doc["status"] = "rejected"
        ban_reason = remark or "Rejected during profile verification"
        record_ban(
            db,
            student.get("email") or "",
            ban_reason,
            banned_by=faculty.get("email"),
        )
    db["users"].update_one({"_id": oid}, {"$set": set_doc})
    return jsonify({"message": "Updated.", "verification_status": status}), 200


def _unverify_student_response(student: dict | None, actor_email: str):
    """Shared handler: unverify a verified, non-banned student. Returns Flask (response, status)."""
    if not student:
        return jsonify({"error": "Student not found."}), 404
    ut = (student.get("user_type") or "").strip().lower()
    role = (student.get("role") or "").strip().upper()
    if ut != "student" and role != ROLE_STUDENT:
        return jsonify({"error": "Only student accounts can be unverified here."}), 400
    if user_is_banned(student):
        return jsonify({"error": "This account is banned; unverify is not applicable."}), 400
    v = (student.get("verification_status") or "").strip().upper()
    if not student.get("is_verified") and v != VERIFICATION_VERIFIED:
        return jsonify({"error": "Student is not verified."}), 400
    db["users"].update_one(
        {"_id": student["_id"]},
        {
            "$set": {
                "is_verified": False,
                "verification_status": VERIFICATION_PENDING,
                "verification_updated_at": datetime.utcnow(),
                "verification_by": actor_email,
            }
        },
    )
    return jsonify({"message": "Student unverified.", "verification_status": VERIFICATION_PENDING}), 200


@app.route("/api/faculty/students/<student_id>/unverify", methods=["POST"])
@login_required
@faculty_required
def api_faculty_student_unverify(student_id):
    """Faculty: revoke verification (verified → pending). Confirmation is done in the UI."""
    faculty = get_logged_in_user()
    if not faculty:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        oid = ObjectId(student_id)
    except Exception:
        return jsonify({"error": "Invalid student id"}), 400
    query = _faculty_department_scope(faculty)
    if query is None:
        return jsonify({"error": "Your faculty profile has no branch assigned."}), 403
    query["_id"] = oid
    student = db["users"].find_one(query)
    if not student:
        return jsonify({"error": "Student not found in your department"}), 404
    if not _faculty_student_branch_matches(faculty, student):
        return jsonify({"error": "Student branch does not match your branch."}), 403
    return _unverify_student_response(student, faculty.get("email") or "")


@app.route("/api/coordinator/students/<student_id>/unverify", methods=["POST"])
@login_required
@role_required("COORDINATOR")
def api_coordinator_student_unverify(student_id):
    """Coordinator: revoke verification for any student."""
    coord = get_logged_in_user()
    if not coord:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        oid = ObjectId(student_id)
    except Exception:
        return jsonify({"error": "Invalid student id"}), 400
    student = db["users"].find_one(
        {
            "_id": oid,
            "$or": [
                {"user_type": "student"},
                {"role": ROLE_STUDENT},
                {"role": "STUDENT"},
            ],
        }
    )
    if not student:
        return jsonify({"error": "Student not found."}), 404
    return _unverify_student_response(student, coord.get("email") or "")


@app.route("/api/admin/students/<student_id>/unverify", methods=["POST"])
def api_admin_student_unverify(student_id):
    """Admin: revoke student verification (second auth when configured)."""
    _, err = require_admin_session(require_second_auth=True)
    if err:
        return jsonify({"error": "Admin authentication required"}), 401
    try:
        oid = ObjectId(student_id)
    except Exception:
        return jsonify({"error": "Invalid student id"}), 400
    student = db["users"].find_one(
        {
            "_id": oid,
            "$or": [
                {"user_type": "student"},
                {"role": ROLE_STUDENT},
                {"role": "STUDENT"},
            ],
        }
    )
    admin_email = session.get("admin_email") or session.get("email") or "admin"
    return _unverify_student_response(student, admin_email)


@app.route("/api/faculty/students/<student_id>/correction-message", methods=["POST"])
@login_required
@faculty_required
def api_faculty_student_correction_message(student_id):
    """Faculty sends a correction/changes message to a verified student. Delivered as notification."""
    faculty = get_logged_in_user()
    if not faculty:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        oid = ObjectId(student_id)
    except Exception:
        return jsonify({"error": "Invalid student id"}), 400
    query = _faculty_department_scope(faculty)
    if query is None:
        return jsonify({"error": "Your faculty profile has no branch assigned."}), 403
    query["_id"] = oid
    student = db["users"].find_one(query)
    if not student:
        return jsonify({"error": "Student not found in your department"}), 404
    if not _faculty_student_branch_matches(faculty, student):
        return jsonify({"error": "Student branch does not match your branch."}), 403
    if user_is_banned(student):
        return jsonify({"error": "This account has been permanently banned."}), 400
    if (student.get("verification_status") or "").strip().upper() != VERIFICATION_VERIFIED:
        return jsonify({"error": "Correction message can only be sent to verified students."}), 400
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Message is required."}), 400
    faculty_name = f"{faculty.get('first_name', '')} {faculty.get('last_name', '')}".strip() or "Faculty"
    notification_message = f"{faculty_name} has requested profile correction/changes."
    create_notification(
        oid,
        notification_message,
        notification_type="profile_correction",
        reference_id=faculty["_id"],
        reference_type="faculty_feedback",
        metadata={"message": message, "faculty_name": faculty_name},
    )
    return jsonify({"message": "Correction message sent to student."}), 200


@app.route("/api/faculty/applications", methods=["GET"])
@login_required
@faculty_required
def api_faculty_applications():
    """List job applications for students in faculty's department only."""
    faculty = get_logged_in_user()
    if not faculty:
        return jsonify({"error": "Not authenticated"}), 401
    dept_query = _faculty_department_scope(faculty)
    if dept_query is None:
        return jsonify({"applications": [], "jobs": {}}), 200
    student_ids = [doc["_id"] for doc in db["users"].find(dept_query, {"_id": 1})]
    if not student_ids:
        return jsonify({"applications": [], "jobs": {}}), 200
    applications = list(db["applications"].find({"student_id": {"$in": student_ids}}).sort("applied_at", -1))
    job_ids = list({a["job_id"] for a in applications if a.get("job_id")})
    jobs = {str(j["_id"]): j for j in db["job_posts"].find({"_id": {"$in": job_ids}})}
    students = {str(s["_id"]): s for s in db["users"].find({"_id": {"$in": student_ids}})}
    items = []
    for a in applications:
        sid = a.get("student_id")
        j = jobs.get(str(a.get("job_id"))) if a.get("job_id") else None
        s = students.get(str(sid)) if sid else None
        items.append({
            "id": str(a.get("_id")),
            "student_id": str(sid),
            "student_name": f"{s.get('first_name', '')} {s.get('last_name', '')}".strip() if s else None,
            "job_id": str(a.get("job_id")),
            "company": j.get("company_name") if j else None,
            "role": j.get("role") if j else None,
            "status": a.get("status") or APPLICATION_STATUS_APPLIED,
            "applied_at": to_utc_iso(a.get("applied_at")),
        })
    return jsonify({"applications": items}), 200


@app.route("/api/faculty/help/threads", methods=["GET"])
@login_required
@faculty_required
def api_faculty_help_threads():
    """List help threads for faculty's department (students who sent help requests)."""
    faculty = get_logged_in_user()
    if not faculty:
        return jsonify({"error": "Not authenticated"}), 401
    dept = normalize_branch_code(faculty.get("branch_code") or faculty.get("branch"))
    if not dept:
        return jsonify({"threads": []}), 200
    threads = []
    for doc in db["message_groups"].find({
        "type": "help",
        "department_id": dept,
    }).sort("created_at", -1):
        student = db["users"].find_one({"_id": doc.get("student_id")}) if doc.get("student_id") else None
        last_msg = db["messages"].find_one(
            {"thread_id": doc["_id"], "thread_type": "help"},
            sort=[("created_at", -1)]
        )
        unread = db["messages"].count_documents({
            "thread_id": doc["_id"],
            "thread_type": "help",
            "sender_id": {"$ne": faculty["_id"]},
            "is_read": False,
        })
        threads.append({
            "thread_id": str(doc["_id"]),
            "student_id": str(doc["student_id"]) if doc.get("student_id") else None,
            "student_name": f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() if student else None,
            "roll_number": student.get("roll_number") if student else None,
            "email": student.get("email") if student else None,
            "last_message": (last_msg or {}).get("content"),
            "last_message_at": to_utc_iso((last_msg or {}).get("created_at")),
            "unread_count": unread,
        })
    return jsonify({"threads": threads}), 200


@app.route("/api/faculty/help/threads/<thread_id>", methods=["GET"])
@login_required
@faculty_required
def api_faculty_help_thread_get(thread_id):
    """Get messages for a help thread. Faculty must be in same department as thread."""
    faculty = get_logged_in_user()
    if not faculty:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        thread_oid = ObjectId(thread_id)
    except Exception:
        return jsonify({"error": "Invalid thread id"}), 400
    dept = normalize_branch_code(faculty.get("branch_code") or faculty.get("branch"))
    thread = db["message_groups"].find_one({"_id": thread_oid, "type": "help", "department_id": dept})
    if not thread:
        return jsonify({"error": "Thread not found"}), 404
    student = db["users"].find_one({"_id": thread.get("student_id")}) if thread.get("student_id") else None
    db["messages"].update_many(
        {
            "thread_id": thread_oid,
            "thread_type": "help",
            "sender_id": {"$ne": faculty["_id"]},
            "is_read": False,
        },
        {"$set": {"is_read": True}}
    )
    messages = []
    for doc in db["messages"].find({"thread_id": thread_oid, "thread_type": "help"}).sort("created_at", 1).limit(100):
        is_mine = doc.get("sender_id") == faculty["_id"]
        messages.append({
            "id": str(doc.get("_id")),
            "content": doc.get("content"),
            "sender_id": str(doc.get("sender_id")),
            "is_own": is_mine,
            "is_mine": is_mine,
            "created_at": to_utc_iso(doc.get("created_at")),
        })
    return jsonify({
        "thread_id": thread_id,
        "student": {
            "id": str(thread.get("student_id")),
            "name": f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() if student else None,
            "roll_number": student.get("roll_number") if student else None,
            "email": student.get("email") if student else None,
        },
        "messages": messages,
    }), 200


@app.route("/api/faculty/help/threads/<thread_id>/messages", methods=["POST"])
@login_required
@faculty_required
def api_faculty_help_thread_reply(thread_id):
    """Faculty reply to a help thread."""
    faculty = get_logged_in_user()
    if not faculty:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        thread_oid = ObjectId(thread_id)
    except Exception:
        return jsonify({"error": "Invalid thread id"}), 400
    dept = normalize_branch_code(faculty.get("branch_code") or faculty.get("branch"))
    thread = db["message_groups"].find_one({"_id": thread_oid, "type": "help", "department_id": dept})
    if not thread:
        return jsonify({"error": "Thread not found"}), 404
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "Content is required"}), 400
    message_doc = {
        "sender_id": faculty["_id"],
        "recipient_id": None,
        "thread_id": thread_oid,
        "thread_type": "help",
        "content": content,
        "is_read": False,
        "created_at": datetime.utcnow(),
    }
    result = db["messages"].insert_one(message_doc)
    student_id = thread.get("student_id")
    if student_id:
        create_notification(
            student_id,
            "You have a new reply from Help.",
            notification_type="message",
            reference_id=thread_oid,
            reference_type="help_thread",
        )
    return jsonify({"message": "Reply sent", "id": str(result.inserted_id)}), 201


@app.route("/alumni/dashboard")
@login_required
def alumni_dashboard():
    if "email" not in session:
        return redirect(url_for("login_page"))
    user_roles = session.get("roles", [])
    if not user_roles:
        user_roles = get_user_roles(session.get("email"))
        session["roles"] = user_roles
    effective_role = session.get("selected_role") or session.get("role")
    if len(user_roles) > 1 and not effective_role:
        return redirect(url_for("dashboard_selector"))
    if effective_role == "alumni" or "alumni" in user_roles:
        return send_from_directory(app.static_folder, "alumni_dashboard.html")
    flash("You do not have access to the alumni dashboard.", "danger")
    if len(user_roles) > 1:
        return redirect(url_for("dashboard_selector"))
    return redirect(url_for("main"))


@app.route("/coordinator/students")
@login_required
@role_required("COORDINATOR")
def coordinator_students_route():
    """Legacy URL; student verification is handled in the faculty dashboard."""
    return redirect("/coordinator/dashboard")


@app.route("/coordinator/jobs")
@login_required
@role_required("COORDINATOR")
def coordinator_jobs_route():
    """Redirect to coordinator dashboard with job-posts view."""
    return redirect("/coordinator/dashboard#job-posts")


@app.route("/coordinator/jobs/create")
@login_required
@role_required("COORDINATOR")
def coordinator_job_create_page():
    """Serve coordinator job create page."""
    return send_from_directory(app.static_folder, "coordinator_job_create.html")


@app.route("/coordinator/jobs/<job_id>")
@login_required
@role_required("COORDINATOR")
def coordinator_job_detail_page(job_id):
    """Serve coordinator job detail page."""
    return send_from_directory(app.static_folder, "coordinator_job_detail.html")


@app.route("/api/coordinator/jobs", methods=["GET"])
def api_coordinator_jobs():
    """
    Get jobs created by the current coordinator.
    JWT-based.
    """
    user, err = require_jwt(role="coordinator")
    if err:
        return err

    items = []
    for doc in db["job_posts"].find({"created_by_email": user.get("email")}).sort("created_at", -1):
        job_oid = doc.get("_id")
        app_count = db["applications"].count_documents({"job_id": job_oid})
        items.append({
            "id": str(job_oid),
            "company_name": doc.get("company_name"),
            "role": doc.get("role"),
            "type": doc.get("type"),
            "mode": doc.get("mode"),
            "eligible_branches": doc.get("eligible_branches") or [],
            "deadline": doc.get("deadline"),
            "status": doc.get("status") or "active",
            "created_at": doc.get("created_at").isoformat() if isinstance(doc.get("created_at"), datetime) else None,
            "application_count": app_count,
        })
    return jsonify({"items": items}), 200


@app.route("/api/coordinator/jobs/<job_id>/applications", methods=["GET"])
def api_coordinator_job_applications(job_id):
    """
    Get all applications for a specific job.
    JWT coordinator must have created the job (same as /api/coordinator/jobs list).
    """
    user, err = require_jwt(role="coordinator")
    if err:
        return err

    try:
        oid = ObjectId(job_id)
    except Exception:
        return jsonify({"error": "Invalid job id"}), 400

    job = db["job_posts"].find_one({"_id": oid})
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if job.get("created_by_email") != user.get("email"):
        return jsonify({"error": "You can only view applications for jobs you created"}), 403

    applications = []
    for app_doc in db["applications"].find({"job_id": oid}).sort("applied_at", -1):
        student = db["users"].find_one({"_id": app_doc.get("student_id")})
        student_name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() if student else "Unknown"
        csv_f = _student_applicant_csv_fields(student)
        applications.append({
            "id": str(app_doc.get("_id")),
            "student_id": str(app_doc.get("student_id")),
            "student_name": student_name,
            "student_email": student.get("email") if student else None,
            "branch": csv_f["branch"] or (student.get("branch_code") or student.get("branch") if student else None),
            "first_name": csv_f["first_name"],
            "last_name": csv_f["last_name"],
            "year": csv_f["year"],
            "mail": csv_f["mail"],
            "status": app_doc.get("status") or APPLICATION_STATUS_APPLIED,
            "applied_at": app_doc.get("applied_at").isoformat() if isinstance(app_doc.get("applied_at"), datetime) else None,
        })

    return jsonify({"applications": applications}), 200


@app.route("/api/coordinator/overview", methods=["GET"])
def api_coordinator_overview():
    """
    Coordinator overview counts.
    All numbers are computed from MongoDB collections (no synthetic values).
    Student verification is handled by faculty; coordinators focus on alumni and placement ops.
    """
    user, err = require_jwt(role="coordinator")
    if err:
        return err

    users_coll = db["users"]

    total_students = users_coll.count_documents({"user_type": "student"})
    pending_alumni_requests = db["alumni_requests"].count_documents({"status": "pending"})

    # If job_posts collection doesn't exist yet, Mongo will treat it as empty -> count 0.
    active_job_posts = db["job_posts"].count_documents({"status": "active"})

    return jsonify({
        "counts": {
            "total_students": total_students,
            "pending_alumni_requests": pending_alumni_requests,
            "active_job_posts": active_job_posts,
        }
    }), 200


@app.route("/api/coordinator/students", methods=["GET"])
def api_coordinator_students_list():
    """
    Deprecated for coordinators: student verification is performed by faculty (same branch only).
    """
    user, err = require_jwt(role="coordinator")
    if err:
        return err
    return jsonify({
        "error": "Student verification is managed by faculty. Coordinators approve alumni requests only.",
    }), 403


@app.route("/api/coordinator/students/<student_id>", methods=["GET"])
def api_coordinator_student_detail(student_id):
    """
    Deprecated for coordinators: student profiles for verification are viewed by faculty.
    """
    coord, err = require_jwt(role="coordinator")
    if err:
        return err
    return jsonify({
        "error": "Student verification is managed by faculty. Coordinators approve alumni requests only.",
    }), 403


@app.route("/api/coordinator/students/<student_id>/verification", methods=["POST"])
def api_coordinator_student_verification(student_id):
    """
    Disabled: coordinators do not verify students. Use faculty dashboard (same branch).
    """
    coord, err = require_jwt(role="coordinator")
    if err:
        return err
    return jsonify({
        "error": "Student verification is performed by faculty of the same branch only.",
    }), 403


def _get_coordinator_user():
    """Return coordinator from JWT or session."""
    coord, err = require_jwt(role="coordinator")
    if not err and coord:
        return coord, None
    if session.get("email"):
        user = get_logged_in_user()
        if user and (user.get("user_type") or "").strip().lower() == "coordinator":
            return user, None
    return None, (jsonify({"error": "Coordinator access required"}), 403)


@app.route("/api/coordinator/alumni-requests", methods=["GET"])
def api_coordinator_alumni_requests():
    """List alumni registration requests (pending by default)."""
    coord, err = _get_coordinator_user()
    if err:
        return err
    status_filter = (request.args.get("status") or "pending").strip().lower()
    query = {}
    if status_filter in ("pending", "rejected", "approved"):
        query["status"] = status_filter
    else:
        query["status"] = "pending"
    items = []
    for doc in db["alumni_requests"].find(query).sort("created_at", -1):
        items.append({
            "id": str(doc.get("_id")),
            "first_name": doc.get("first_name"),
            "last_name": doc.get("last_name"),
            "email": doc.get("email"),
            "branch": doc.get("branch"),
            "passout_year": doc.get("passout_year"),
            "status": doc.get("status") or "pending",
            "created_at": to_utc_iso(doc.get("created_at")),
        })
    return jsonify({"items": items}), 200


@app.route("/api/coordinator/alumni-requests/<request_id>/reject", methods=["POST"])
def api_coordinator_alumni_request_reject(request_id):
    coord, err = _get_coordinator_user()
    if err:
        return err
    try:
        oid = ObjectId(request_id)
    except Exception:
        return jsonify({"error": "Invalid request id"}), 400
    req_doc = db["alumni_requests"].find_one({"_id": oid})
    if not req_doc:
        return jsonify({"error": "Request not found"}), 404
    if req_doc.get("status") != "pending":
        return jsonify({"error": "Request is not pending"}), 400
    db["alumni_requests"].update_one(
        {"_id": oid},
        {"$set": {"status": "rejected", "updated_at": datetime.utcnow()}}
    )
    return jsonify({"message": "Request rejected."}), 200


@app.route("/api/coordinator/alumni-requests/<request_id>/approve", methods=["POST"])
def api_coordinator_alumni_request_approve(request_id):
    coord, err = _get_coordinator_user()
    if err:
        return err
    try:
        oid = ObjectId(request_id)
    except Exception:
        return jsonify({"error": "Invalid request id"}), 400
    req_doc = db["alumni_requests"].find_one({"_id": oid})
    if not req_doc:
        return jsonify({"error": "Request not found"}), 404
    if req_doc.get("status") != "pending":
        return jsonify({"error": "Request is not pending"}), 400
    email = (req_doc.get("email") or "").strip().lower()
    if db["users"].find_one({"email": email, "user_type": "alumni"}):
        return jsonify({"error": "User already exists as alumni."}), 400
    raw_token = secrets.token_urlsafe(32)
    token_hash = generate_password_hash(raw_token)
    token_expiry = datetime.utcnow() + timedelta(hours=1)
    user_doc = {
        "first_name": req_doc.get("first_name"),
        "last_name": req_doc.get("last_name"),
        "email": email,
        "password": generate_password_hash(secrets.token_urlsafe(16)),
        "user_type": "alumni",
        "role": ROLE_ALUMNI,
        "branch": req_doc.get("branch"),
        "branch_code": normalize_branch_code(req_doc.get("branch")),
        "passout_year": req_doc.get("passout_year"),
        "is_active": False,
        "password_setup_token": token_hash,
        "password_setup_token_expiry": token_expiry,
        "verification_status": VERIFICATION_VERIFIED,
        "profile_completion": 0,
        "created_at": datetime.utcnow(),
    }
    db["users"].insert_one(user_doc)
    db["alumni_requests"].update_one(
        {"_id": oid},
        {"$set": {"status": "approved", "updated_at": datetime.utcnow(), "approved_by": coord.get("email")}}
    )
    setup_url = url_for("alumni_set_password", token=raw_token, _external=True)
    send_alumni_setup_email(email, setup_url)
    return jsonify({"message": "Approved. Password setup email sent to the alumni."}), 200


@app.route("/api/coordinator/policies", methods=["GET", "PUT"])
def api_coordinator_policies():
    """Get or update placement policy (one job, multiple offer, dream company threshold)."""
    coord, err = _get_coordinator_user()
    if err:
        return err
    if request.method == "GET":
        policy = get_active_policy(db)
        if not policy:
            policy = ensure_default_policy(db)
        return jsonify({
            "one_job_policy": policy.get("one_job_policy") is True,
            "multiple_offer_allowed": policy.get("multiple_offer_allowed") is True,
            "dream_company_threshold": policy.get("dream_company_threshold"),
        }), 200
    data = request.get_json(silent=True) or {}
    db["placement_policies"].update_many(
        {"active": True},
        {"$set": {
            "one_job_policy": bool(data.get("one_job_policy")),
            "multiple_offer_allowed": bool(data.get("multiple_offer_allowed")),
            "dream_company_threshold": data.get("dream_company_threshold"),
            "updated_at": datetime.utcnow(),
        }}
    )
    return jsonify({"message": "Policy updated."}), 200


@app.route("/api/coordinator/students/<student_id>/placed", methods=["POST"])
def api_coordinator_mark_placed(student_id):
    """Coordinator: mark student as placed (company, package). Locks further applications if one_job_policy."""
    coord, err = _get_coordinator_user()
    if err:
        return err
    try:
        oid = ObjectId(student_id)
    except Exception:
        return jsonify({"error": "Invalid student id"}), 400
    student = db["users"].find_one({"_id": oid, "user_type": "student"})
    if not student:
        return jsonify({"error": "Student not found"}), 404
    data = request.get_json(silent=True) or {}
    company = (data.get("company") or data.get("placed_company") or "").strip()
    package = (data.get("package") or data.get("placed_package") or "").strip()
    if not company:
        return jsonify({"error": "company is required"}), 400
    db["users"].update_one(
        {"_id": oid},
        {"$set": {
            "placement_status": PLACEMENT_STATUS_PLACED,
            "placed_company": company,
            "placed_package": package or None,
            "placed_at": datetime.utcnow(),
        }}
    )
    return jsonify({"message": "Student marked as placed."}), 200


# ---------- Interview Experience Module (invite-based) ----------
INTERVIEW_INVITE_PENDING = "Pending"
INTERVIEW_INVITE_SUBMITTED = "Submitted"
INTERVIEW_DRIVE_STATUS = "Completed"
INTERVIEW_DIFFICULTY = ("Easy", "Medium", "Hard")
INTERVIEW_TECHNICAL_HR = ("More Technical", "More HR", "Balanced")
INTERVIEW_DOMAINS = ("DSA", "OOPS", "DBMS", "OS", "CN", "Projects", "Internship", "Aptitude", "Other")
INTERVIEW_FOCUS = ("Projects", "Internship", "Skills", "Fundamentals")


@app.route("/api/coordinator/interview-drives", methods=["GET", "POST"])
def api_coordinator_interview_drives():
    """Coordinator: list drives or create new drive with CSV upload and invites."""
    coord, err = _get_coordinator_user()
    if err:
        return err
    if request.method == "GET":
        items = []
        for doc in db["interview_drives"].find({"created_by": coord["_id"]}).sort("created_at", -1):
            items.append({
                "id": str(doc["_id"]),
                "company": doc.get("company"),
                "role": doc.get("role"),
                "interview_date": doc.get("interview_date"),
                "rounds": doc.get("rounds") or [],
                "status": doc.get("status") or INTERVIEW_DRIVE_STATUS,
                "has_csv": bool(doc.get("csv_url")),
                "created_at": doc.get("created_at").isoformat() if isinstance(doc.get("created_at"), datetime) else None,
            })
        return jsonify({"drives": items}), 200

    # POST: create drive + optional CSV
    data = request.form
    company = (data.get("company") or "").strip()
    role = (data.get("role") or "").strip()
    jd = (data.get("jd") or "").strip()
    interview_date = (data.get("interview_date") or "").strip()
    students_applied = (data.get("students_applied") or "").strip()
    students_shortlisted = (data.get("students_shortlisted") or "").strip()
    stipend = (data.get("stipend") or "").strip()
    location = (data.get("location") or "").strip()
    rounds_raw = data.get("rounds") or ""
    rounds = [r.strip() for r in rounds_raw.split(",") if r.strip()]
    if not company or not role:
        return jsonify({"error": "company and role are required"}), 400

    csv_file = request.files.get("csv_file") or request.files.get("file")
    csv_url = None
    if csv_file and csv_file.filename:
        if _extract_file_ext(csv_file.filename) != "csv":
            return jsonify({"error": "Only CSV files are allowed."}), 400
        uploaded_csv, csv_upload_err = upload_to_cloudinary(
            csv_file,
            "campuslink/interview_csv",
            resource_type="raw",
            public_id_prefix="interview_csv",
        )
        if csv_upload_err:
            return jsonify({"error": csv_upload_err}), 400
        csv_url = uploaded_csv.get("secure_url")

    drive_doc = {
        "company": company,
        "role": role,
        "jd": jd or None,
        "interview_date": interview_date or None,
        "students_applied": students_applied or None,
        "students_shortlisted": students_shortlisted or None,
        "stipend": stipend or None,
        "location": location or None,
        "rounds": rounds,
        "status": INTERVIEW_DRIVE_STATUS,
        "created_by": coord["_id"],
        "created_at": datetime.utcnow(),
    }
    if csv_url:
        drive_doc["csv_url"] = csv_url
    ins = db["interview_drives"].insert_one(drive_doc)
    drive_id = ins.inserted_id

    summary = {
        "total_rows": 0,
        "duplicates_removed": 0,
        "successfully_invited": 0,
        "emails_not_found": [],
        "branch_invalid": [],
        "year_invalid": [],
        "branch_mismatch": [],
        "year_mismatch": [],
        "role_mismatch": [],
    }
    if csv_file:
        try:
            csv_file.seek(0)
            csv_content = csv_file.read()
        except Exception:
            csv_content = None
        if csv_content:
            result = process_csv(csv_content)
            if not result.get("ok"):
                return jsonify({"error": result.get("header_error", "Invalid CSV")}), 400
            summary["total_rows"] = result.get("total_rows", 0)
            summary["duplicates_removed"] = result.get("duplicates_removed", 0)
            drive_role_normalized = (role or "").strip()
            for row in result.get("rows", []):
                email = (row.get("email") or "").lower()
                if not email:
                    continue
                if row.get("branch_invalid"):
                    summary["branch_invalid"].append(email)
                if row.get("year_invalid"):
                    summary["year_invalid"].append(email)
                student = db["users"].find_one({"user_type": "student", "email": email})
                if not student:
                    summary["emails_not_found"].append(email)
                    continue
                student_branch = (student.get("branch_code") or student.get("branch") or "").strip().upper()
                student_year_raw = student.get("year")
                student_year = None
                if student_year_raw is not None:
                    try:
                        student_year = int(student_year_raw)
                    except (TypeError, ValueError):
                        pass
                csv_branch = (row.get("branch_code") or "").strip().upper() if row.get("branch_code") else None
                csv_year = row.get("year")
                if csv_branch and student_branch and csv_branch != student_branch:
                    summary["branch_mismatch"].append(email)
                if csv_year is not None and student_year is not None and csv_year != student_year:
                    summary["year_mismatch"].append(email)
                role_trimmed = (row.get("role") or "").strip()
                if role_trimmed and drive_role_normalized and role_trimmed != drive_role_normalized:
                    summary["role_mismatch"].append(email)
                existing = db["interview_invites"].find_one({"drive_id": drive_id, "student_id": student["_id"]})
                if existing:
                    continue
                token = generate_invite_token()
                db["interview_invites"].insert_one({
                    "drive_id": drive_id,
                    "student_id": student["_id"],
                    "email": email,
                    "invite_token": token,
                    "status": INTERVIEW_INVITE_PENDING,
                    "mail_sent": False,
                    "created_at": datetime.utcnow(),
                })
                submit_link = url_for("submit_experience_page", token=token, _external=True)
                sent = send_interview_invite_email(email, submit_link, company, role)
                db["interview_invites"].update_one(
                    {"drive_id": drive_id, "email": email},
                    {"$set": {"mail_sent": sent}},
                )
                summary["successfully_invited"] += 1

    return jsonify({"message": "Drive created.", "id": str(drive_id), "summary": summary}), 201


@app.route("/api/coordinator/interview-drives/<drive_id>", methods=["DELETE"])
def api_coordinator_interview_drive_delete(drive_id):
    """Coordinator only. Delete own interview drive and related module records."""
    coord, err = _get_coordinator_user()
    if err:
        return err
    try:
        oid = ObjectId(drive_id)
    except Exception:
        return jsonify({"error": "Invalid drive id"}), 400
    drive = db["interview_drives"].find_one({"_id": oid, "created_by": coord["_id"]})
    if not drive:
        return jsonify({"error": "Drive not found"}), 404

    exp_ids = [doc["_id"] for doc in db["interview_experiences"].find({"drive_id": oid}, {"_id": 1})]
    if exp_ids:
        db["interview_comments"].delete_many({"experience_id": {"$in": exp_ids}})
    db["interview_experiences"].delete_many({"drive_id": oid})
    db["interview_invites"].delete_many({"drive_id": oid})
    db["interview_drives"].delete_one({"_id": oid})
    return jsonify({"message": "Drive deleted."}), 200


@app.route("/api/coordinator/interview-drives/<drive_id>/csv-access", methods=["POST"])
def api_coordinator_interview_drive_csv_access(drive_id):
    """Coordinator only. Password re-auth then return temporary signed Cloudinary URL for CSV."""
    coord, err = _get_coordinator_user()
    if err:
        return err
    try:
        oid = ObjectId(drive_id)
    except Exception:
        return jsonify({"error": "Invalid drive id"}), 400
    drive = db["interview_drives"].find_one({"_id": oid, "created_by": coord["_id"]})
    if not drive:
        return jsonify({"error": "Drive not found"}), 404
    csv_url = (drive.get("csv_url") or "").strip()
    if not csv_url:
        return jsonify({"error": "No CSV uploaded for this drive."}), 404
    data = request.get_json(silent=True) or {}
    password = (data.get("password") or "").strip()
    if not password:
        return jsonify({"error": "Password is required."}), 400
    pwd_hash = coord.get("password") or ""
    if not pwd_hash or not check_password_hash(pwd_hash, password):
        return jsonify({"error": "Invalid password."}), 401
    return jsonify({"url": csv_url}), 200


@app.route("/submit-experience/<token>")
def submit_experience_page(token):
    """Serve submit-experience form (token-based; no login required to view form)."""
    return send_from_directory(app.static_folder, "submit_experience.html")


@app.route("/api/interview/invite-by-token/<token>", methods=["GET"])
def api_interview_invite_by_token(token):
    """Validate invite token; return drive info for form. Block if already submitted."""
    invite = db["interview_invites"].find_one({"invite_token": token.strip()})
    if not invite:
        return jsonify({"error": "Invalid or expired invite link"}), 404
    if (invite.get("status") or "").strip() == INTERVIEW_INVITE_SUBMITTED:
        return jsonify({"error": "You have already submitted your experience for this drive."}), 400
    drive = db["interview_drives"].find_one({"_id": invite["drive_id"]})
    if not drive:
        return jsonify({"error": "Drive not found"}), 404
    return jsonify({
        "valid": True,
        "drive_id": str(drive["_id"]),
        "company": drive.get("company"),
        "role": drive.get("role"),
        "invite_id": str(invite["_id"]),
    }), 200


@app.route("/api/interview/submit-experience", methods=["POST"])
def api_interview_submit_experience():
    """Submit experience (body must include invite_token and form fields)."""
    data = request.get_json(silent=True) or {}
    invite_token = (data.get("invite_token") or "").strip()
    if not invite_token:
        return jsonify({"error": "invite_token is required"}), 400
    invite = db["interview_invites"].find_one({"invite_token": invite_token})
    if not invite:
        return jsonify({"error": "Invalid or expired invite link"}), 404
    if (invite.get("status") or "").strip() == INTERVIEW_INVITE_SUBMITTED:
        return jsonify({"error": "You have already submitted."}), 400
    drive_id = invite["drive_id"]
    drive = db["interview_drives"].find_one({"_id": drive_id})
    if not drive:
        return jsonify({"error": "Drive not found"}), 404
    difficulty = (data.get("difficulty") or "").strip()
    if difficulty not in INTERVIEW_DIFFICULTY:
        difficulty = "Medium"
    technical_vs_hr = (data.get("technical_vs_hr") or "").strip()
    if technical_vs_hr not in INTERVIEW_TECHNICAL_HR:
        technical_vs_hr = "Balanced"
    domains_asked = data.get("domains_asked")
    if not isinstance(domains_asked, list):
        domains_asked = []
    domains_asked = [d for d in domains_asked if isinstance(d, str) and d.strip() and d.strip() in INTERVIEW_DOMAINS]
    focus_area = data.get("focus_area")
    if not isinstance(focus_area, list):
        focus_area = []
    focus_area = [f for f in focus_area if isinstance(f, str) and f.strip() and f.strip() in INTERVIEW_FOCUS]
    questions = data.get("questions")
    if not isinstance(questions, list):
        questions = []
    questions = [q for q in questions if isinstance(q, dict) and (q.get("round") or q.get("question"))]
    tips = (data.get("tips") or "").strip() or None
    experience_overview = (data.get("experience_overview") or "").strip() or None
    result = (data.get("result") or "").strip() or None
    selected = bool(data.get("selected"))
    student_id = invite["student_id"]
    experience_doc = {
        "drive_id": drive_id,
        "student_id": student_id,
        "difficulty": difficulty,
        "technical_vs_hr": technical_vs_hr,
        "domains_asked": domains_asked,
        "focus_area": focus_area,
        "questions": questions,
        "tips": tips,
        "experience_overview": experience_overview,
        "result": result,
        "selected": selected,
        "submitted_at": datetime.utcnow(),
    }
    db["interview_experiences"].insert_one(experience_doc)
    db["interview_invites"].update_one(
        {"_id": invite["_id"]},
        {"$set": {"status": INTERVIEW_INVITE_SUBMITTED}},
    )
    return jsonify({"message": "Experience submitted.", "drive_id": str(drive_id)}), 201


@app.route("/interviews")
def interviews_list_page():
    """Single Interview module entry: list of drives. All roles, login required."""
    user = get_logged_in_user()
    if not user:
        return redirect(url_for("login_page"))
    return send_from_directory(app.static_folder, "interviews.html")


@app.route("/api/interview/drives", methods=["GET"])
def api_interview_drives_list():
    """List all interview drives for /interviews page. Any logged-in user."""
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    role = (user.get("user_type") or user.get("role") or "").strip().lower()
    is_coordinator = role == "coordinator"
    user_id = user.get("_id")
    items = []
    for doc in db["interview_drives"].find({}).sort("created_at", -1):
        drive_oid = doc["_id"]
        exp_ids = [e["_id"] for e in db["interview_experiences"].find({"drive_id": drive_oid}, {"_id": 1})]
        comment_count = db["interview_comments"].count_documents({"experience_id": {"$in": exp_ids}}) if exp_ids else 0
        items.append({
            "id": str(doc["_id"]),
            "company": doc.get("company"),
            "role": doc.get("role"),
            "interview_date": doc.get("interview_date"),
            "comment_count": comment_count,
            "is_coordinator": is_coordinator,
            "can_delete": bool(is_coordinator and user_id and doc.get("created_by") == user_id),
        })
    return jsonify({"drives": items, "is_coordinator": is_coordinator}), 200


@app.route("/interview-drive/<drive_id>")
def interview_drive_page(drive_id):
    """Single drive page: About Drive | Interview Feedback. All roles, login required."""
    user = get_logged_in_user()
    if not user:
        return redirect(url_for("login_page"))
    return send_from_directory(app.static_folder, "interview_drive.html")


@app.route("/api/interview/drives/<drive_id>", methods=["GET"])
def api_interview_drive_detail(drive_id):
    """Return drive details and experiences (for interview-drive page). Role: student, faculty, alumni, coordinator."""
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    role = (user.get("user_type") or user.get("role") or "").strip().lower()
    is_coordinator = role == "coordinator"
    try:
        oid = ObjectId(drive_id)
    except Exception:
        return jsonify({"error": "Invalid drive id"}), 400
    drive = db["interview_drives"].find_one({"_id": oid})
    if not drive:
        return jsonify({"error": "Drive not found"}), 404
    experiences = []
    for exp in db["interview_experiences"].find({"drive_id": oid}).sort("submitted_at", -1):
        student = db["users"].find_one({"_id": exp["student_id"]}, {"first_name": 1, "last_name": 1, "branch_code": 1, "branch": 1})
        name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() if student else "Unknown"
        branch = (student.get("branch_code") or student.get("branch") or "") if student else ""
        experiences.append({
            "id": str(exp["_id"]),
            "student_id": str(exp["student_id"]),
            "student_name": name,
            "department": branch,
            "difficulty": exp.get("difficulty"),
            "technical_vs_hr": exp.get("technical_vs_hr"),
            "domains_asked": exp.get("domains_asked") or [],
            "focus_area": exp.get("focus_area") or [],
            "tips": exp.get("tips"),
            "questions": exp.get("questions") or [],
            "selected": exp.get("selected") is True,
            "submitted_at": exp.get("submitted_at").isoformat() if isinstance(exp.get("submitted_at"), datetime) else None,
        })
    return jsonify({
        "drive": {
            "id": str(drive["_id"]),
            "company": drive.get("company"),
            "role": drive.get("role"),
            "jd": drive.get("jd"),
            "interview_date": drive.get("interview_date"),
            "students_applied": drive.get("students_applied"),
            "students_shortlisted": drive.get("students_shortlisted"),
            "stipend": drive.get("stipend"),
            "location": drive.get("location"),
            "rounds": drive.get("rounds") or [],
            "status": drive.get("status"),
            "csv_url": drive.get("csv_url") if is_coordinator else None,
        },
        "is_coordinator": is_coordinator,
        "experiences": experiences,
    }), 200


@app.route("/interview-experiences/<drive_id>")
def interview_experiences_list_page(drive_id):
    """List of experiences for one drive. All roles, login required."""
    user = get_logged_in_user()
    if not user:
        return redirect(url_for("login_page"))
    return send_from_directory(app.static_folder, "interview_experiences.html")


@app.route("/api/interview/experiences/by-drive/<drive_id>", methods=["GET"])
def api_interview_experiences_by_drive(drive_id):
    """List experiences for a drive (cards: name, branch, year, preview, like/comment count)."""
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        drive_oid = ObjectId(drive_id)
    except Exception:
        return jsonify({"error": "Invalid drive id"}), 400
    drive = db["interview_drives"].find_one({"_id": drive_oid})
    if not drive:
        return jsonify({"error": "Drive not found"}), 404
    experiences = []
    for exp in db["interview_experiences"].find({"drive_id": drive_oid}).sort("submitted_at", -1):
        student = db["users"].find_one({"_id": exp["student_id"]}, {"first_name": 1, "last_name": 1, "branch_code": 1, "branch": 1, "year": 1})
        name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() if student else "Unknown"
        branch = (student.get("branch_code") or student.get("branch") or "") if student else ""
        year = student.get("year") if student is not None else None
        if year is not None and not isinstance(year, (int, str)):
            year = None
        preview_parts = [exp.get("tips") or "", (exp.get("questions") or [{}])[0].get("question", "") if (exp.get("questions") or []) else ""]
        preview = " ".join(p for p in preview_parts if p)[:180] or "No preview."
        comment_count = db["interview_comments"].count_documents({"experience_id": exp["_id"]})
        experiences.append({
            "id": str(exp["_id"]),
            "student_id": str(exp["student_id"]),
            "student_name": name,
            "branch": branch,
            "year": year,
            "preview": preview,
            "like_count": 0,
            "comment_count": comment_count,
        })
    return jsonify({
        "drive": {"id": str(drive["_id"]), "company": drive.get("company"), "role": drive.get("role")},
        "experiences": experiences,
    }), 200


@app.route("/interview-experience/<experience_id>")
def interview_experience_detail_page(experience_id):
    """Single experience detail with comments. All roles, login required."""
    user = get_logged_in_user()
    if not user:
        return redirect(url_for("login_page"))
    return send_from_directory(app.static_folder, "interview_experience.html")


@app.route("/api/interview/experiences/<experience_id>", methods=["GET"])
def api_interview_experience_detail(experience_id):
    """Single experience full detail for experience detail page."""
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        exp_oid = ObjectId(experience_id)
    except Exception:
        return jsonify({"error": "Invalid experience id"}), 400
    exp = db["interview_experiences"].find_one({"_id": exp_oid})
    if not exp:
        return jsonify({"error": "Experience not found"}), 404
    drive = db["interview_drives"].find_one({"_id": exp["drive_id"]})
    student = db["users"].find_one({"_id": exp["student_id"]}, {"first_name": 1, "last_name": 1, "branch_code": 1, "branch": 1, "year": 1})
    name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() if student else "Unknown"
    branch = (student.get("branch_code") or student.get("branch") or "") if student else ""
    year = student.get("year") if student is not None else None
    return jsonify({
        "experience": {
            "id": str(exp["_id"]),
            "student_name": name,
            "branch": branch,
            "year": year,
            "company": drive.get("company") if drive else "",
            "role": drive.get("role") if drive else "",
            "difficulty": exp.get("difficulty"),
            "technical_vs_hr": exp.get("technical_vs_hr"),
            "domains_asked": exp.get("domains_asked") or [],
            "focus_area": exp.get("focus_area") or [],
            "tips": exp.get("tips"),
            "experience_overview": exp.get("experience_overview"),
            "result": exp.get("result"),
            "questions": exp.get("questions") or [],
            "selected": exp.get("selected") is True,
        },
        "drive_id": str(exp["drive_id"]),
    }), 200


@app.route("/api/interview/experiences/<experience_id>/comments", methods=["GET", "POST"])
def api_interview_experience_comments(experience_id):
    """Get or add comments (logged-in student, faculty, alumni, coordinator)."""
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        exp_oid = ObjectId(experience_id)
    except Exception:
        return jsonify({"error": "Invalid experience id"}), 400
    exp = db["interview_experiences"].find_one({"_id": exp_oid})
    if not exp:
        return jsonify({"error": "Experience not found"}), 404
    if request.method == "GET":
        comments = []
        for c in db["interview_comments"].find({"experience_id": exp_oid}).sort("created_at", 1):
            comment_user = db["users"].find_one({"_id": c["user_id"]}, {"first_name": 1, "last_name": 1, "user_type": 1, "role": 1})
            cn = f"{comment_user.get('first_name', '')} {comment_user.get('last_name', '')}".strip() if comment_user else "Unknown"
            role_label = (comment_user.get("user_type") or comment_user.get("role") or c.get("role") or "User")
            if isinstance(role_label, str):
                role_label = role_label.replace("_", " ").title()
            comments.append({
                "id": str(c["_id"]),
                "user_id": str(c["user_id"]),
                "user_name": cn,
                "role": role_label,
                "comment": c.get("comment"),
                "parent_id": str(c["parent_id"]) if c.get("parent_id") else None,
                "created_at": c.get("created_at").isoformat() if isinstance(c.get("created_at"), datetime) else None,
                "like_count": 0,
            })
        return jsonify({"comments": comments}), 200
    data = request.get_json(silent=True) or {}
    comment_text = (data.get("comment") or "").strip()
    if not comment_text:
        return jsonify({"error": "comment is required"}), 400
    role = (user.get("user_type") or user.get("role") or "user").strip()
    parent_id = data.get("parent_id")
    parent_oid = None
    if parent_id:
        try:
            parent_oid = ObjectId(parent_id)
        except Exception:
            pass
    doc = {
        "experience_id": exp_oid,
        "user_id": user["_id"],
        "role": role,
        "comment": comment_text,
        "created_at": datetime.utcnow(),
    }
    if parent_oid:
        doc["parent_id"] = parent_oid
    db["interview_comments"].insert_one(doc)
    return jsonify({"message": "Comment added."}), 201


@app.route("/api/coordinator/interview-drives/list-for-nav", methods=["GET"])
def api_coordinator_interview_drives_list_nav():
    """Light list for coordinator nav (id, company, role)."""
    coord, err = _get_coordinator_user()
    if err:
        return err
    items = []
    for doc in db["interview_drives"].find({"created_by": coord["_id"]}).sort("created_at", -1).limit(50):
        items.append({"id": str(doc["_id"]), "company": doc.get("company"), "role": doc.get("role")})
    return jsonify({"drives": items}), 200


@app.route("/coordinator/post-interview")
@login_required
@role_required("COORDINATOR")
def coordinator_post_interview_page():
    """Coordinator: Post Completed Interview form page."""
    return send_from_directory(app.static_folder, "coordinator_post_interview.html")


@app.route("/coordinator/interview-drives")
@login_required
@role_required("COORDINATOR")
def coordinator_interview_drives_page():
    """Coordinator: List interview drives and View CSV (with re-auth)."""
    return send_from_directory(app.static_folder, "coordinator_interview_drives.html")


# ---------- Alumni registration request (public, no login) ----------
@app.route("/api/alumni/request", methods=["POST"])
def api_alumni_request():
    """
    Submit an alumni registration request. Data stored in alumni_requests with status=pending.
    No credentials created until coordinator approves.
    """
    data = request.get_json(silent=True) or {}
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    branch = (data.get("branch") or "").strip().upper()
    passout_year = (data.get("passout_year") or "").strip()
    if not first_name or not last_name or not email:
        return jsonify({"error": "First name, last name, and email are required."}), 400
    if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
        return jsonify({"error": "Valid email is required."}), 400
    if db["users"].find_one({"email": email, "user_type": "alumni"}):
        return jsonify({"error": "This email is already registered as an approved alumni."}), 400
    if db["alumni_requests"].find_one({"email": email, "status": "pending"}):
        return jsonify({"error": "A pending request with this email already exists."}), 400
    doc = {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "branch": branch or None,
        "passout_year": passout_year or None,
        "status": "pending",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    db["alumni_requests"].insert_one(doc)
    return jsonify({"message": "Your registration request has been sent for approval."}), 201


def _student_applicant_csv_fields(student: dict | None) -> dict[str, str]:
    """Fields for applicant export: first name, second name, branch, year, mail."""
    if not student:
        return {
            "first_name": "",
            "last_name": "",
            "branch": "",
            "year": "",
            "mail": "",
        }
    fn = (student.get("first_name") or "").strip()
    ln = (student.get("last_name") or "").strip()
    branch = student.get("branch_code") or student.get("branch") or ""
    year = student.get("graduation_year") or student.get("passout_year")
    profile = student.get("profile") or {}
    edu = profile.get("education") or []
    if (year is None or str(year).strip() == "") and isinstance(edu, list) and edu:
        e0 = edu[0] if isinstance(edu[0], dict) else {}
        year = e0.get("graduation_year") or e0.get("year") or e0.get("passing_year")
    mail = (student.get("email") or "").strip()
    y_str = str(year).strip() if year is not None and str(year).strip() else ""
    return {
        "first_name": fn,
        "last_name": ln,
        "branch": str(branch) if branch is not None else "",
        "year": y_str,
        "mail": mail,
    }


# ---------- Alumni API (session or JWT, role=alumni only) ----------
def _get_alumni_user():
    """
    Return current alumni user from session or JWT. Alumni must have user_type=alumni.
    Returns (alumni_doc, None) or (None, (response, status)).
    """
    user = get_logged_in_user()
    if user and (user.get("user_type") or "").strip().lower() == "alumni":
        return user, None
    return require_jwt(role="alumni")


@app.route("/api/alumni/dashboard", methods=["GET"])
def api_alumni_dashboard():
    alumni, err = _get_alumni_user()
    if err:
        return err
    aid = alumni.get("_id")
    profile = alumni.get("profile") or {}
    profile_completion = alumni.get("profile_completion")
    if profile_completion is None:
        profile_completion = calculate_alumni_profile_completion(profile, alumni)
    mentorship_received = db["mentoring_requests"].count_documents({"alumni_id": aid})
    pending_mentorship = db["mentoring_requests"].count_documents({"alumni_id": aid, "status": "pending"})
    referrals_given = db["referral_requests"].count_documents({"alumni_id": aid})
    jobs_posted = db["alumni_jobs"].count_documents({"posted_by": aid})
    accepted_mentorship = db["mentoring_requests"].count_documents({"alumni_id": aid, "status": "accepted"})
    mentees = alumni.get("mentees") or []
    active_mentees = len(mentees)
    mentee_slots_full = active_mentees >= MAX_ALUMNI_MENTEES
    connection_count = db["connections"].count_documents({
        "$or": [
            {"requester_id": aid, "status": CONNECTION_ACCEPTED},
            {"recipient_id": aid, "status": CONNECTION_ACCEPTED},
        ]
    })
    return jsonify({
        "profile_completion": max(0, min(100, int(profile_completion))),
        "mentoring_requests_received": mentorship_received,
        "mentorship_requests_received": mentorship_received,
        "pending_mentorship_requests": pending_mentorship,
        "referrals_given": referrals_given,
        "jobs_posted": jobs_posted,
        "students_mentored": accepted_mentorship,
        "active_mentees": active_mentees,
        "max_mentees": MAX_ALUMNI_MENTEES,
        "mentee_slots_full": mentee_slots_full,
        "connection_count": connection_count,
        "current_company": profile.get("current_company") or "—",
        "designation": profile.get("designation") or "—",
    }), 200


def _normalize_alumni_resource_entry(raw) -> dict:
    raw = dict(raw or {})
    links = raw.get("links") if isinstance(raw.get("links"), list) else []
    links = [str(l).strip() for l in links if isinstance(l, str) and str(l).strip()][:20]
    media = raw.get("media_urls") if isinstance(raw.get("media_urls"), list) else []
    media = [str(m).strip() for m in media if isinstance(m, str) and str(m).strip()][:12]
    return {
        "id": str(raw.get("id") or uuid.uuid4()),
        "description": _clean_str(raw.get("description"), 2000) or "",
        "links": links,
        "media_urls": media,
    }


@app.route("/api/alumni/profile", methods=["GET", "PUT"])
def api_alumni_profile():
    alumni, err = _get_alumni_user()
    if err:
        return err
    if (alumni.get("user_type") or "").lower() != "alumni":
        return jsonify({"error": "Alumni profile is only for alumni accounts."}), 403

    if request.method == "GET":
        profile = dict(alumni.get("profile") or {})
        first = alumni.get("first_name") or ""
        last = alumni.get("last_name") or ""
        full_name = f"{first} {last}".strip() or None
        profile_data = {
            "education": list(profile.get("education") or []),
            "experience": list(profile.get("experience") or []),
            "projects": list(profile.get("projects") or []),
            "clubs": list(profile.get("clubs") or []),
            "certifications": list(profile.get("certifications") or []),
            "achievements": list(profile.get("achievements") or []),
        }
        sort_profile_sections_reverse_chronological(profile_data)
        ph = profile.get("profile_photo")
        cv = profile.get("cover_photo")
        return jsonify({
            "full_name": full_name,
            "first_name": first,
            "last_name": last,
            "email": alumni.get("email"),
            "phone": profile.get("phone"),
            "headline": profile.get("headline"),
            "profile_photo": ph,
            "cover_photo": cv,
            "current_company": profile.get("current_company"),
            "designation": profile.get("designation"),
            "location": profile.get("location"),
            "industry": profile.get("industry"),
            "passing_year": profile.get("passing_year") or profile.get("passout_year") or alumni.get("passout_year"),
            "branch": profile.get("branch") or alumni.get("branch") or alumni.get("branch_code"),
            "degree": profile.get("degree"),
            "work_profile": profile.get("work_profile") if isinstance(profile.get("work_profile"), dict) else {},
            "experience_timeline": list(profile.get("experience_timeline") or []),
            "education": profile_data["education"],
            "experience": profile_data["experience"],
            "projects": profile_data["projects"],
            "skills": list(profile.get("skills") or []),
            "clubs": profile_data["clubs"],
            "certifications": profile_data["certifications"],
            "achievements": profile_data["achievements"],
            "student_resources": list(profile.get("student_resources") or profile.get("notes_for_students") or []),
            "bio": profile.get("bio"),
            "linkedin_url": profile.get("linkedin_url"),
            "portfolio_url": profile.get("portfolio_url"),
            "profile_completion": alumni.get("profile_completion"),
        }), 200

    data = request.get_json(silent=True) or {}
    full_name = (data.get("full_name") or "").strip()
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    if full_name and not (first_name or last_name):
        parts = full_name.split(maxsplit=1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ""
    profile = dict(alumni.get("profile") or {})

    def _opt_str(key, max_len=500):
        v = data.get(key)
        if v is None:
            return
        profile[key] = _clean_str(v, max_len) or None

    _opt_str("phone", 80)
    _opt_str("headline", 220)
    _opt_str("current_company", 200)
    _opt_str("designation", 200)
    _opt_str("location", 200)
    _opt_str("industry", 120)
    _opt_str("bio", 4000)
    _opt_str("linkedin_url", 500)
    _opt_str("portfolio_url", 500)
    _opt_str("passing_year", 20)
    _opt_str("passout_year", 20)
    _opt_str("branch", 40)
    _opt_str("degree", 120)

    if "work_profile" in data and isinstance(data.get("work_profile"), dict):
        wp = data.get("work_profile") or {}
        resp = wp.get("responsibilities") if isinstance(wp.get("responsibilities"), list) else []
        resp = [_clean_str(x, 400) for x in resp if isinstance(x, str) and x.strip()][:30]
        profile["work_profile"] = {
            "organization": _clean_str(wp.get("organization") or wp.get("current_organization"), 200) or None,
            "department": _clean_str(wp.get("department") or wp.get("team"), 200) or None,
            "responsibilities": resp,
            "technologies_used": _clean_str(wp.get("technologies_used") or wp.get("technologies"), 800) or None,
            "work_domain": _clean_str(wp.get("work_domain"), 80) or None,
        }

    if "experience_timeline" in data:
        experience_timeline = data.get("experience_timeline")
        if not isinstance(experience_timeline, list):
            experience_timeline = []
        profile["experience_timeline"] = [
            {
                "company": (x.get("company") or "").strip() if isinstance(x, dict) else "",
                "role": (x.get("role") or "").strip() if isinstance(x, dict) else "",
                "employment_type": (x.get("employment_type") or "").strip() if isinstance(x, dict) else "",
                "start_date": (x.get("start_date") or "").strip() if isinstance(x, dict) else "",
                "end_date": (x.get("end_date") or "").strip() if isinstance(x, dict) else "",
                "description": (x.get("description") or "").strip() if isinstance(x, dict) else "",
            }
            for x in experience_timeline
        ]

    if "skills" in data:
        skills = data.get("skills")
        normalized_skills = []
        for item in (skills if isinstance(skills, list) else []):
            if isinstance(item, str) and item.strip():
                normalized_skills.append(item.strip())
                continue
            if isinstance(item, dict):
                norm_skill = _normalize_skill_item(item)
                if norm_skill.get("name"):
                    normalized_skills.append(norm_skill)
        profile["skills"] = normalized_skills

    if "education" in data and isinstance(data.get("education"), list):
        profile["education"] = data.get("education")
    if "experience" in data and isinstance(data.get("experience"), list):
        profile["experience"] = data.get("experience")
    if "projects" in data and isinstance(data.get("projects"), list):
        profile["projects"] = data.get("projects")
    if "clubs" in data and isinstance(data.get("clubs"), list):
        profile["clubs"] = data.get("clubs")
    if "certifications" in data and isinstance(data.get("certifications"), list):
        profile["certifications"] = data.get("certifications")
    if "achievements" in data and isinstance(data.get("achievements"), list):
        profile["achievements"] = data.get("achievements")

    if "student_resources" in data or "notes_for_students" in data:
        raw_list = data.get("student_resources")
        if raw_list is None:
            raw_list = data.get("notes_for_students")
        if not isinstance(raw_list, list):
            raw_list = []
        profile["student_resources"] = [_normalize_alumni_resource_entry(x) for x in raw_list][:50]

    update_fields = {"profile": profile}
    if first_name:
        update_fields["first_name"] = first_name
    if last_name:
        update_fields["last_name"] = last_name
    py = profile.get("passing_year") or profile.get("passout_year")
    if py:
        update_fields["passout_year"] = str(py).strip()
    br = profile.get("branch") or alumni.get("branch")
    if br:
        update_fields["branch"] = str(br).strip().upper()
    merged_user = {**alumni, **update_fields}
    completion = calculate_alumni_profile_completion(profile, merged_user)
    update_fields["profile_completion"] = completion
    db["users"].update_one({"_id": alumni["_id"]}, {"$set": update_fields})
    return jsonify({"message": "Profile updated.", "profile_completion": completion}), 200


@app.route("/api/alumni/profile/notes-media", methods=["POST"])
def api_alumni_profile_notes_media():
    """Upload media for Notes / Resources (images/videos/docs)."""
    alumni, err = _get_alumni_user()
    if err:
        return err
    media_file = request.files.get("file") or request.files.get("media")
    url, media_kind, upload_err = _upload_user_media(
        media_file,
        alumni,
        "notes",
        allow_images=True,
        allow_videos=True,
        allow_docs=True,
        public_id_prefix="notes_media",
    )
    if upload_err:
        return jsonify({"error": upload_err}), 400
    return jsonify(
        {
            "url": url,
            "media": {
                "type": media_kind,
                "url": url,
            },
        }
    ), 201


def _find_profile_item_index(items: list, item_id: str) -> int | None:
    if not isinstance(items, list):
        return None
    for i, it in enumerate(items):
        if isinstance(it, dict) and str(it.get("id") or "") == str(item_id):
            return i
    return None


def _upsert_alumni_profile_item_media_post(
    alumni: dict,
    item: dict,
    *,
    post_type: str,
    profile_section: str,
    media_url: str,
) -> ObjectId | None:
    """
    Create or update a feed post for an alumni profile item that has media.
    Used for alumni certifications / achievements / experience proof uploads.
    """
    if not alumni or not item or not media_url:
        return None
    item_id = str(item.get("id") or "").strip()
    if not item_id:
        return None
    title = ""
    if post_type == "certification":
        title = f"Certification: {item.get('name') or 'Certification'}"
    elif post_type == "achievement":
        title = f"Achievement: {item.get('title') or 'Achievement'}"
    elif post_type == "internship":
        role = item.get("role") or "Experience"
        company = item.get("company") or "Company"
        title = f"Experience: {role} at {company}"
    else:
        title = f"Profile update: {post_type}"
    content = (
        _clean_str(item.get("description"), 500)
        or _clean_str(item.get("summary"), 500)
        or _clean_str(item.get("issuer"), 200)
        or title
    )
    media_items = [{"type": "image", "url": media_url}]
    post_doc = {
        "author_id": alumni["_id"],
        "post_type": post_type,
        "reference_type": profile_section,
        "reference_id": item_id,
        "title": title,
        "description": content,
        "content": content,
        "media_url": media_url,
        "media_urls": [media_url],
        "media": media_items,
        "media_type": "image",
        "likes": [],
        "likes_count": 0,
        "comments_count": 0,
    }
    post_id_raw = item.get("post_id")
    post_oid = None
    if post_id_raw:
        try:
            post_oid = ObjectId(str(post_id_raw))
        except Exception:
            post_oid = None
    now = datetime.utcnow()
    if post_oid:
        existing = db["posts"].find_one({"_id": post_oid, "author_id": alumni["_id"]})
        if existing:
            db["posts"].update_one(
                {"_id": post_oid},
                {"$set": {**post_doc, "updated_at": now, "created_at": existing.get("created_at") or now}},
            )
            return post_oid
    result = db["posts"].insert_one({**post_doc, "created_at": now})
    create_activity(
        alumni["_id"],
        ACTIVITY_TYPE_POST,
        result.inserted_id,
        "post",
        {"content_preview": title[:100], "post_type": post_type},
    )
    return result.inserted_id


@app.route("/api/alumni/profile/experience/<item_id>/media", methods=["POST"])
def api_alumni_profile_experience_media(item_id):
    """Upload proof image for an experience item (stores in `media_url`)."""
    alumni, err = _get_alumni_user()
    if err:
        return err
    media_file = request.files.get("file") or request.files.get("media") or request.files.get("photo")
    url, media_kind, upload_err = _upload_user_media(
        media_file,
        alumni,
        "internships",
        allow_images=True,
        allow_videos=False,
        allow_docs=False,
        public_id_prefix="experience_media",
    )
    if upload_err:
        return jsonify({"error": upload_err}), 400
    profile = dict(alumni.get("profile") or {})
    items = list(profile.get("experience") or [])
    idx = _find_profile_item_index(items, item_id)
    if idx is None:
        return jsonify({"error": "Experience entry not found"}), 404
    items[idx] = dict(items[idx] or {})
    items[idx]["media_url"] = url
    post_id = _upsert_alumni_profile_item_media_post(
        alumni,
        items[idx],
        post_type="internship",
        profile_section="experience",
        media_url=url,
    )
    if post_id:
        items[idx]["post_created"] = True
        items[idx]["post_id"] = str(post_id)
    profile["experience"] = items
    db["users"].update_one({"_id": alumni["_id"]}, {"$set": {"profile": profile}})
    return jsonify({"url": url, "media_type": media_kind, "item_id": item_id}), 201


@app.route("/api/alumni/profile/projects/<item_id>/media", methods=["POST"])
def api_alumni_profile_projects_media(item_id):
    """Upload project media: image(s) appended to `media_urls` or video stored in `project_video_url`."""
    alumni, err = _get_alumni_user()
    if err:
        return err
    media_file = request.files.get("file") or request.files.get("media")
    url, media_kind, upload_err = _upload_user_media(
        media_file,
        alumni,
        "projects",
        allow_images=True,
        allow_videos=True,
        allow_docs=False,
        public_id_prefix="project_media",
    )
    if upload_err:
        return jsonify({"error": upload_err}), 400
    profile = dict(alumni.get("profile") or {})
    items = list(profile.get("projects") or [])
    idx = _find_profile_item_index(items, item_id)
    if idx is None:
        return jsonify({"error": "Project entry not found"}), 404
    items[idx] = dict(items[idx] or {})
    if media_kind == "video":
        items[idx]["project_video_url"] = url
    else:
        arr = items[idx].get("media_urls")
        if not isinstance(arr, list):
            arr = []
        arr = [str(x).strip() for x in arr if isinstance(x, str) and str(x).strip()]
        arr.append(url)
        items[idx]["media_urls"] = arr[:10]
    profile["projects"] = items
    db["users"].update_one({"_id": alumni["_id"]}, {"$set": {"profile": profile}})
    return jsonify({"url": url, "media_type": media_kind, "item_id": item_id}), 201


@app.route("/api/alumni/profile/certifications/<item_id>/media", methods=["POST"])
def api_alumni_profile_certifications_media(item_id):
    """Upload certificate photo for a certification item (stores in `media_url`)."""
    alumni, err = _get_alumni_user()
    if err:
        return err
    media_file = request.files.get("file") or request.files.get("media") or request.files.get("photo")
    url, media_kind, upload_err = _upload_user_media(
        media_file,
        alumni,
        "certificates",
        allow_images=True,
        allow_videos=False,
        allow_docs=False,
        public_id_prefix="certificate_photo",
    )
    if upload_err:
        return jsonify({"error": upload_err}), 400
    profile = dict(alumni.get("profile") or {})
    items = list(profile.get("certifications") or [])
    idx = _find_profile_item_index(items, item_id)
    if idx is None:
        return jsonify({"error": "Certification entry not found"}), 404
    items[idx] = dict(items[idx] or {})
    items[idx]["media_url"] = url
    post_id = _upsert_alumni_profile_item_media_post(
        alumni,
        items[idx],
        post_type="certification",
        profile_section="certifications",
        media_url=url,
    )
    if post_id:
        items[idx]["post_created"] = True
        items[idx]["post_id"] = str(post_id)
    profile["certifications"] = items
    db["users"].update_one({"_id": alumni["_id"]}, {"$set": {"profile": profile}})
    return jsonify({"url": url, "media_type": media_kind, "item_id": item_id}), 201


@app.route("/api/alumni/profile/achievements/<item_id>/media", methods=["POST"])
def api_alumni_profile_achievements_media(item_id):
    """Upload proof image for an achievement item (stores in `media_url`)."""
    alumni, err = _get_alumni_user()
    if err:
        return err
    media_file = request.files.get("file") or request.files.get("media") or request.files.get("photo")
    url, media_kind, upload_err = _upload_user_media(
        media_file,
        alumni,
        "achievements",
        allow_images=True,
        allow_videos=False,
        allow_docs=False,
        public_id_prefix="achievement_photo",
    )
    if upload_err:
        return jsonify({"error": upload_err}), 400
    profile = dict(alumni.get("profile") or {})
    items = list(profile.get("achievements") or [])
    idx = _find_profile_item_index(items, item_id)
    if idx is None:
        return jsonify({"error": "Achievement entry not found"}), 404
    items[idx] = dict(items[idx] or {})
    items[idx]["media_url"] = url
    post_id = _upsert_alumni_profile_item_media_post(
        alumni,
        items[idx],
        post_type="achievement",
        profile_section="achievements",
        media_url=url,
    )
    if post_id:
        items[idx]["post_created"] = True
        items[idx]["post_id"] = str(post_id)
    profile["achievements"] = items
    db["users"].update_one({"_id": alumni["_id"]}, {"$set": {"profile": profile}})
    return jsonify({"url": url, "media_type": media_kind, "item_id": item_id}), 201


@app.route("/api/alumni/profile/alumni-docs", methods=["POST"])
def api_alumni_profile_alumni_docs():
    """Upload verification/proof documents under user other/ folder."""
    alumni, err = _get_alumni_user()
    if err:
        return err
    doc_file = request.files.get("file") or request.files.get("document")
    if not doc_file or not doc_file.filename:
        return jsonify({"error": "Document file is required."}), 400
    ext = _extract_file_ext(doc_file.filename)
    if ext not in {"pdf", "jpg", "jpeg", "png"}:
        return jsonify({"error": "Only PDF/JPG/JPEG/PNG are allowed."}), 400
    max_size = MAX_DOC_SIZE if ext == "pdf" else MAX_IMAGE_SIZE
    try:
        doc_file.stream.seek(0, os.SEEK_END)
        size = doc_file.stream.tell()
        doc_file.stream.seek(0)
    except Exception:
        size = None
    if size and size > max_size:
        return jsonify({"error": "File exceeds allowed size."}), 400
    uploaded, upload_err = upload_to_cloudinary(
        doc_file,
        _cloudinary_user_folder_path(alumni, "other"),
        resource_type="raw" if ext == "pdf" else "image",
        public_id_prefix="alumni_doc",
    )
    if upload_err:
        return jsonify({"error": upload_err}), 400
    return jsonify(
        {
            "url": uploaded.get("secure_url"),
            "document": {
                "url": uploaded.get("secure_url"),
                "public_id": uploaded.get("public_id"),
                "folder": uploaded.get("folder"),
            },
        }
    ), 201


def _default_alumni_settings():
    """Default alumni settings (privacy, notifications, mentorship)."""
    return {
        "privacy": {
            "profile_visibility": "public",
            "show_current_company": True,
            "show_job_role": True,
            "show_contact": True,
        },
        "notifications": {
            "job_notifications": True,
            "connection_requests": True,
            "announcements": True,
            "email_notifications": True,
        },
        "mentorship": {
            "allow_contact_for_guidance": True,
            "allow_mentorship_requests": True,
            "allow_profile_view": True,
        },
    }


@app.route("/api/alumni/settings", methods=["GET"])
def api_alumni_settings_get():
    """Get alumni settings (privacy, notifications, mentorship) and account info for Settings page."""
    alumni, err = _get_alumni_user()
    if err:
        return err
    settings = alumni.get("alumni_settings") or {}
    defaults = _default_alumni_settings()
    for key in defaults:
        if key not in settings:
            settings[key] = defaults[key]
    return jsonify({
        "email": alumni.get("email"),
        "settings": settings,
    }), 200


@app.route("/api/alumni/settings", methods=["PUT", "PATCH"])
def api_alumni_settings_update():
    """Update alumni settings (privacy, notifications, mentorship)."""
    alumni, err = _get_alumni_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    defaults = _default_alumni_settings()
    new_settings = dict(alumni.get("alumni_settings") or {})
    for category in ("privacy", "notifications", "mentorship"):
        if category not in data:
            continue
        new_settings[category] = dict(defaults.get(category, {}))
        for k, v in (data.get(category) or {}).items():
            if k in new_settings[category]:
                if isinstance(new_settings[category][k], bool):
                    new_settings[category][k] = bool(v)
                else:
                    new_settings[category][k] = v
    db["users"].update_one(
        {"_id": alumni["_id"]},
        {"$set": {"alumni_settings": new_settings, "alumni_settings_updated_at": datetime.utcnow()}}
    )
    return jsonify({"message": "Settings saved.", "settings": new_settings}), 200


@app.route("/api/alumni/change-password", methods=["POST"])
def api_alumni_change_password():
    """Change password for logged-in alumni. Requires current_password and new_password."""
    alumni, err = _get_alumni_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    current = data.get("current_password") or ""
    new_pw = data.get("new_password") or ""
    if not current or not new_pw:
        return jsonify({"error": "Current password and new password are required."}), 400
    if not check_password_hash(alumni.get("password") or "", current):
        return jsonify({"error": "Current password is incorrect."}), 400
    if len(new_pw) < 8:
        return jsonify({"error": "New password must be at least 8 characters."}), 400
    db["users"].update_one(
        {"_id": alumni["_id"]},
        {"$set": {"password": generate_password_hash(new_pw)}}
    )
    return jsonify({"message": "Password updated successfully."}), 200


@app.route("/api/alumni/update-email", methods=["PUT", "POST"])
def api_alumni_update_email():
    """Update email for logged-in alumni. Requires new_email and current password."""
    alumni, err = _get_alumni_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    new_email = (data.get("new_email") or "").strip().lower()
    current_password = data.get("current_password") or ""
    if not new_email:
        return jsonify({"error": "New email is required."}), 400
    if not current_password:
        return jsonify({"error": "Current password is required to change email."}), 400
    if not check_password_hash(alumni.get("password") or "", current_password):
        return jsonify({"error": "Current password is incorrect."}), 400
    if db["users"].find_one({"email": new_email, "_id": {"$ne": alumni["_id"]}}):
        return jsonify({"error": "This email is already in use."}), 400
    if db["admins"].find_one({"email": new_email}):
        return jsonify({"error": "This email is already in use."}), 400
    db["users"].update_one(
        {"_id": alumni["_id"]},
        {"$set": {"email": new_email}}
    )
    return jsonify({"message": "Email updated successfully.", "email": new_email}), 200


@app.route("/api/alumni/logout-all", methods=["POST"])
def api_alumni_logout_all():
    """Logout from all devices: clear server session and instruct client to remove token."""
    alumni, err = _get_alumni_user()
    if err:
        return err
    if "email" in session and session.get("email") == alumni.get("email"):
        session.clear()
    return jsonify({"message": "Logged out from all devices. Please sign in again."}), 200


@app.route("/api/alumni/mentorship", methods=["GET"])
def api_alumni_mentorship_list():
    alumni, err = _get_alumni_user()
    if err:
        return err
    aid = alumni["_id"]
    status_filter = (request.args.get("status") or "").strip().lower()
    query = {"alumni_id": aid}
    if status_filter in ("pending", "accepted", "rejected"):
        query["status"] = status_filter
    items = []
    for doc in db["mentoring_requests"].find(query).sort("created_at", -1):
        student = db["users"].find_one({"_id": doc.get("student_id")}) if doc.get("student_id") else None
        student_name = None
        student_email = None
        if student:
            student_name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or student.get("email")
            student_email = student.get("email")
        items.append({
            "id": str(doc.get("_id")),
            "student_id": str(doc.get("student_id")) if doc.get("student_id") else None,
            "student_name": student_name,
            "student_email": student_email,
            "status": doc.get("status") or "pending",
            "message": doc.get("message"),
            "response_message": doc.get("response_message"),
            "created_at": to_utc_iso(doc.get("created_at")),
            "updated_at": to_utc_iso(doc.get("updated_at")),
        })
    return jsonify({"items": items}), 200


@app.route("/api/alumni/mentorship/<request_id>", methods=["PATCH"])
def api_alumni_mentorship_patch(request_id):
    """Accept or reject mentorship. On accept: update student.mentor_id, alumni.mentees, create Mentoring chat."""
    alumni, err = _get_alumni_user()
    if err:
        return err
    try:
        oid = ObjectId(request_id)
    except Exception:
        return jsonify({"error": "Invalid request id"}), 400
    doc = db["mentoring_requests"].find_one({"_id": oid, "alumni_id": alumni["_id"]})
    if not doc:
        return jsonify({"error": "Mentorship request not found"}), 404
    data = request.get_json(silent=True) or {}
    status = (data.get("status") or "").strip().lower()
    if status not in ("accepted", "rejected"):
        return jsonify({"error": "status must be accepted or rejected"}), 400
    student_id = doc.get("student_id")
    if not student_id:
        return jsonify({"error": "Invalid request"}), 400

    if status == "rejected":
        db["mentoring_requests"].update_one({"_id": oid}, {"$set": {"status": "rejected", "timestamp": datetime.utcnow()}})
        return jsonify({"message": "Rejected.", "status": "rejected"}), 200

    # Accept: re-validate slots and student has no mentor
    student = db["users"].find_one({"_id": student_id, "user_type": "student"})
    if not student:
        return jsonify({"error": "Student not found"}), 404
    if student.get("mentor_id") is not None:
        return jsonify({"error": "Student already has a mentor."}), 400
    mentees = alumni.get("mentees") or []
    if len(mentees) >= MAX_ALUMNI_MENTEES:
        return jsonify({"error": "Mentee slots are full."}), 400
    if student_id in mentees:
        db["mentoring_requests"].update_one({"_id": oid}, {"$set": {"status": "accepted", "timestamp": datetime.utcnow()}})
        return jsonify({"message": "Already accepted.", "status": "accepted"}), 200

    db["users"].update_one({"_id": student_id}, {"$set": {"mentor_id": alumni["_id"]}})
    db["users"].update_one({"_id": alumni["_id"]}, {"$addToSet": {"mentees": student_id}})
    db["mentoring_requests"].update_one({"_id": oid}, {"$set": {"status": "accepted", "timestamp": datetime.utcnow()}})
    # Mark any other pending requests from this student as rejected so they can't have two mentors
    db["mentoring_requests"].update_many(
        {"student_id": student_id, "status": "pending", "_id": {"$ne": oid}},
        {"$set": {"status": "rejected", "timestamp": datetime.utcnow()}},
    )
    # Create Mentoring message group (conversation record for student-alumni pair)
    existing = db["message_groups"].find_one({
        "name": "Mentoring",
        "participants": {"$all": [student_id, alumni["_id"]]},
    })
    if not existing:
        db["message_groups"].insert_one({
            "name": "Mentoring",
            "participants": [student_id, alumni["_id"]],
            "created_at": datetime.utcnow(),
        })
    return jsonify({"message": "Accepted.", "status": "accepted"}), 200


@app.route("/cancel-mentorship", methods=["POST"])
@login_required
def api_cancel_mentorship():
    """Student cancels own mentorship; or alumni cancels for a specific mentee. Frees slot."""
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    data = request.get_json(silent=True) or {}
    ut = (user.get("user_type") or "").strip().lower()

    if ut == "student":
        mentor_id = user.get("mentor_id")
        if mentor_id is None:
            return jsonify({"error": "You do not have a mentor."}), 400
        db["users"].update_one({"_id": user["_id"]}, {"$set": {"mentor_id": None}})
        db["users"].update_one({"_id": mentor_id}, {"$pull": {"mentees": user["_id"]}})
        db["mentoring_requests"].update_many(
            {"student_id": user["_id"], "alumni_id": mentor_id, "status": "accepted"},
            {"$set": {"status": "cancelled", "timestamp": datetime.utcnow()}},
        )
        return jsonify({"message": "Mentorship cancelled."}), 200

    if ut == "alumni":
        student_id_raw = data.get("student_id")
        if not student_id_raw:
            return jsonify({"error": "student_id is required to cancel a mentee."}), 400
        try:
            student_oid = ObjectId(student_id_raw)
        except Exception:
            return jsonify({"error": "Invalid student_id"}), 400
        mentees = user.get("mentees") or []
        if student_oid not in mentees:
            return jsonify({"error": "This student is not your mentee."}), 400
        db["users"].update_one({"_id": user["_id"]}, {"$pull": {"mentees": student_oid}})
        db["users"].update_one({"_id": student_oid}, {"$set": {"mentor_id": None}})
        db["mentoring_requests"].update_many(
            {"student_id": student_oid, "alumni_id": user["_id"], "status": "accepted"},
            {"$set": {"status": "cancelled", "timestamp": datetime.utcnow()}},
        )
        return jsonify({"message": "Mentorship cancelled."}), 200

    return jsonify({"error": "Only students or alumni can cancel mentorship."}), 403


@app.route("/api/alumni/mentorship/<request_id>/mentee", methods=["GET"])
def api_alumni_mentorship_mentee(request_id):
    alumni, err = _get_alumni_user()
    if err:
        return err
    try:
        oid = ObjectId(request_id)
    except Exception:
        return jsonify({"error": "Invalid request id"}), 400
    doc = db["mentoring_requests"].find_one({"_id": oid, "alumni_id": alumni["_id"]})
    if not doc:
        return jsonify({"error": "Mentorship request not found"}), 404
    student_id = doc.get("student_id")
    if not student_id:
        return jsonify({"error": "No mentee linked"}), 404
    student = db["users"].find_one({"_id": student_id})
    if not student:
        return jsonify({"error": "Student not found"}), 404
    profile = student.get("profile") or {}
    return jsonify({
        "id": str(student.get("_id")),
        "name": f"{student.get('first_name', '')} {student.get('last_name', '')}".strip(),
        "email": student.get("email"),
        "branch": student.get("branch_code") or student.get("branch"),
        "profile": profile,
    }), 200


@app.route("/api/alumni/referrals", methods=["GET"])
def api_alumni_referrals_list():
    alumni, err = _get_alumni_user()
    if err:
        return err
    aid = alumni["_id"]
    status_filter = (request.args.get("status") or "").strip().lower()
    query = {"alumni_id": aid}
    if status_filter in ("pending", "approved", "rejected"):
        query["status"] = status_filter
    items = []
    for doc in db["referral_requests"].find(query).sort("created_at", -1):
        student = db["users"].find_one({"_id": doc.get("student_id")}) if doc.get("student_id") else None
        student_name = None
        student_email = None
        if student:
            student_name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or student.get("email")
            student_email = student.get("email")
        job_id = doc.get("job_id")
        job_title = None
        if job_id:
            job_doc = db["alumni_jobs"].find_one({"_id": job_id})
            if job_doc:
                job_title = job_doc.get("title")
        items.append({
            "id": str(doc.get("_id")),
            "student_id": str(doc.get("student_id")) if doc.get("student_id") else None,
            "student_name": student_name,
            "student_email": student_email,
            "job_id": str(job_id) if job_id else None,
            "job_title": job_title,
            "status": doc.get("status") or "pending",
            "referral_note": doc.get("referral_note"),
            "created_at": to_utc_iso(doc.get("created_at")),
            "updated_at": to_utc_iso(doc.get("updated_at")),
        })
    return jsonify({"items": items}), 200


@app.route("/api/alumni/referrals/<request_id>", methods=["PATCH"])
def api_alumni_referrals_patch(request_id):
    alumni, err = _get_alumni_user()
    if err:
        return err
    try:
        oid = ObjectId(request_id)
    except Exception:
        return jsonify({"error": "Invalid request id"}), 400
    doc = db["referral_requests"].find_one({"_id": oid, "alumni_id": alumni["_id"]})
    if not doc:
        return jsonify({"error": "Referral request not found"}), 404
    data = request.get_json(silent=True) or {}
    status = (data.get("status") or "").strip().lower()
    referral_note = (data.get("referral_note") or "").strip() or None
    if status not in ("approved", "rejected"):
        return jsonify({"error": "status must be approved or rejected"}), 400
    update = {"status": status, "updated_at": datetime.utcnow()}
    if referral_note is not None:
        update["referral_note"] = referral_note
    db["referral_requests"].update_one({"_id": oid}, {"$set": update})
    return jsonify({"message": "Updated.", "status": status}), 200


@app.route("/api/alumni/referrals/<request_id>/student", methods=["GET"])
def api_alumni_referral_student(request_id):
    alumni, err = _get_alumni_user()
    if err:
        return err
    try:
        oid = ObjectId(request_id)
    except Exception:
        return jsonify({"error": "Invalid request id"}), 400
    doc = db["referral_requests"].find_one({"_id": oid, "alumni_id": alumni["_id"]})
    if not doc:
        return jsonify({"error": "Referral request not found"}), 404
    student_id = doc.get("student_id")
    if not student_id:
        return jsonify({"error": "No student linked"}), 404
    student = db["users"].find_one({"_id": student_id})
    if not student:
        return jsonify({"error": "Student not found"}), 404
    profile = student.get("profile") or {}
    return jsonify({
        "id": str(student.get("_id")),
        "name": f"{student.get('first_name', '')} {student.get('last_name', '')}".strip(),
        "email": student.get("email"),
        "branch": student.get("branch_code") or student.get("branch"),
        "profile": profile,
    }), 200


@app.route("/api/alumni/jobs", methods=["GET", "POST"])
def api_alumni_jobs():
    alumni, err = _get_alumni_user()
    if err:
        return err
    aid = alumni["_id"]

    if request.method == "GET":
        items = []
        for doc in db["alumni_jobs"].find({"posted_by": aid}).sort("created_at", -1):
            app_count = db["alumni_job_applications"].count_documents({"job_id": doc.get("_id")})
            items.append({
                "id": str(doc.get("_id")),
                "title": doc.get("title"),
                "company": doc.get("company"),
                "location": doc.get("location"),
                "job_type": doc.get("job_type"),
                "description": doc.get("description"),
                "eligibility": doc.get("eligibility"),
                "department_allowed": list(doc.get("department_allowed") or []),
                "created_at": to_utc_iso(doc.get("created_at")),
                "applicant_count": app_count,
                "form_version": doc.get("form_version"),
                "application_deadline": _alumni_job_date_input(
                    doc.get("application_deadline") or doc.get("deadline")
                ),
            })
        return jsonify({"items": items}), 200

    content_type = request.content_type or ""
    if "multipart/form-data" in content_type and request.form.get("form_version") == "2":
        fields, pdf_files, parse_err = _parse_structured_job_from_request(request)
        if parse_err:
            return jsonify({"error": parse_err}), 400
        attachments_meta = _save_job_pdf_files(pdf_files)
        job_doc = _alumni_job_doc_from_structured(fields, alumni, attachments_meta)
        ins = db["alumni_jobs"].insert_one(job_doc)
        return jsonify({"message": "Job created.", "id": str(ins.inserted_id)}), 201

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    company = (data.get("company") or "").strip()
    location = (data.get("location") or "").strip()
    job_type = (data.get("job_type") or "").strip()
    description = (data.get("description") or "").strip()
    eligibility = (data.get("eligibility") or "").strip()
    department_allowed = data.get("department_allowed")
    if not isinstance(department_allowed, list):
        department_allowed = []
    department_allowed = [str(d).strip() for d in department_allowed if isinstance(d, str) and d.strip()]
    if not title or not company:
        return jsonify({"error": "title and company are required"}), 400
    job_doc = {
        "title": title,
        "company": company,
        "location": location or None,
        "job_type": job_type or None,
        "description": description or None,
        "eligibility": eligibility or None,
        "department_allowed": department_allowed,
        "posted_by": aid,
        "created_at": datetime.utcnow(),
    }
    ins = db["alumni_jobs"].insert_one(job_doc)
    return jsonify({"message": "Job created.", "id": str(ins.inserted_id)}), 201


@app.route("/api/alumni/jobs/<job_id>", methods=["GET", "PUT", "DELETE"])
def api_alumni_job_detail(job_id):
    alumni, err = _get_alumni_user()
    if err:
        return err
    try:
        oid = ObjectId(job_id)
    except Exception:
        return jsonify({"error": "Invalid job id"}), 400
    job = db["alumni_jobs"].find_one({"_id": oid, "posted_by": alumni["_id"]})
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if request.method == "GET":
        return jsonify({"job": _alumni_job_to_api_payload(job)}), 200

    if request.method == "DELETE":
        db["alumni_job_applications"].delete_many({"job_id": oid})
        db["alumni_jobs"].delete_one({"_id": oid})
        return jsonify({"message": "Job deleted"}), 200

    content_type = request.content_type or ""
    if "multipart/form-data" in content_type and request.form.get("form_version") == "2":
        fields, pdf_files, parse_err = _parse_structured_job_from_request(request, deadline_must_be_future=False)
        if parse_err:
            return jsonify({"error": parse_err}), 400
        existing_atts = _job_attachment_list(job)
        new_saved = _save_job_pdf_files(pdf_files)
        attachments_meta = (existing_atts + new_saved) if new_saved else existing_atts
        if len(attachments_meta) > MAX_JOB_PDF_ATTACHMENTS:
            attachments_meta = attachments_meta[:MAX_JOB_PDF_ATTACHMENTS]
        update_doc = _alumni_job_doc_from_structured(fields, alumni, attachments_meta)
        update_doc.pop("created_at", None)
        update_doc.pop("posted_by", None)
        update_doc["updated_at"] = datetime.utcnow()
        db["alumni_jobs"].update_one({"_id": oid, "posted_by": alumni["_id"]}, {"$set": update_doc})
        return jsonify({"message": "Job updated"}), 200

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    company = (data.get("company") or "").strip()
    location = (data.get("location") or "").strip()
    job_type = (data.get("job_type") or "").strip()
    description = (data.get("description") or "").strip()
    eligibility = (data.get("eligibility") or "").strip()
    department_allowed = data.get("department_allowed")
    if not isinstance(department_allowed, list):
        department_allowed = list(job.get("department_allowed") or [])
    department_allowed = [str(d).strip() for d in department_allowed if isinstance(d, str) and d.strip()]
    if not title or not company:
        return jsonify({"error": "title and company are required"}), 400
    update = {
        "title": title,
        "company": company,
        "location": location or None,
        "job_type": job_type or None,
        "description": description or None,
        "eligibility": eligibility or None,
        "department_allowed": department_allowed,
        "updated_at": datetime.utcnow(),
    }
    db["alumni_jobs"].update_one({"_id": oid}, {"$set": update})
    return jsonify({"message": "Job updated"}), 200


@app.route("/api/alumni/jobs/<job_id>/applicants", methods=["GET"])
def api_alumni_job_applicants(job_id):
    alumni, err = _get_alumni_user()
    if err:
        return err
    try:
        oid = ObjectId(job_id)
    except Exception:
        return jsonify({"error": "Invalid job id"}), 400
    job = db["alumni_jobs"].find_one({"_id": oid, "posted_by": alumni["_id"]})
    if not job:
        return jsonify({"error": "Job not found"}), 404
    applicants = []
    for doc in db["alumni_job_applications"].find({"job_id": oid}).sort("applied_at", -1):
        student = db["users"].find_one({"_id": doc.get("student_id")}) if doc.get("student_id") else None
        name = None
        email = None
        if student:
            name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip()
            email = student.get("email")
        csv_f = _student_applicant_csv_fields(student)
        applicants.append({
            "id": str(doc.get("_id")),
            "student_id": str(doc.get("student_id")) if doc.get("student_id") else None,
            "student_name": name,
            "student_email": email,
            "first_name": csv_f["first_name"],
            "last_name": csv_f["last_name"],
            "branch": csv_f["branch"],
            "year": csv_f["year"],
            "mail": csv_f["mail"],
            "message": doc.get("message"),
            "applied_at": to_utc_iso(doc.get("applied_at")),
        })
    return jsonify({"applicants": applicants}), 200


# ---------- Public Profile View (by slug: no login) and View Profile (by id: login) ----------
@app.route("/profile/me")
@login_required
def view_my_profile_page():
    """Redirect to the user's own profile. Always use same route/template as Edit Profile 'View Profile'."""
    user = get_logged_in_user()
    if user:
        return redirect(f"/profile/{str(user['_id'])}")
    return redirect(url_for("login_page"))


def _is_object_id_hex(s: str) -> bool:
    if not s or len(s) != 24:
        return False
    try:
        int(s, 16)
        return True
    except ValueError:
        return False


@app.route("/profile/<identifier>")
def profile_page(identifier):
    """
    If identifier is 24-char hex (ObjectId): require login; faculty profiles are not viewable (404); serve view_profile.html for others.
    Otherwise treat as public_slug: no login; find user by public_slug; if not STUDENT/ALUMNI or not found, 404; else serve public_profile.html.
    """
    if identifier == "me":
        return redirect(url_for("login_page"))
    if _is_object_id_hex(identifier):
        user = get_logged_in_user()
        if not user:
            return redirect(url_for("login_page"))
        try:
            profile_owner = db["users"].find_one({"_id": ObjectId(identifier)})
            if profile_owner:
                role_ut = (profile_owner.get("role") or profile_owner.get("user_type") or "").strip().upper()
                ut_lower = (profile_owner.get("user_type") or "").strip().lower()
                if role_ut == ROLE_FACULTY or ut_lower == "faculty":
                    abort(404)
                if role_ut == ROLE_COORDINATOR or ut_lower == "coordinator":
                    abort(404)
                if role_ut == ROLE_ADMIN or ut_lower == "admin":
                    abort(404)
                if user_hidden_from_campuslink_discovery(profile_owner):
                    abort(404)
        except Exception:
            pass
        return send_from_directory(app.static_folder, "view_profile.html")
    user = db["users"].find_one({"public_slug": identifier})
    if not user:
        abort(404)
    role = (user.get("role") or user.get("user_type") or "").strip().upper()
    if role not in (ROLE_STUDENT, ROLE_ALUMNI):
        abort(404)
    if user_hidden_from_campuslink_discovery(user):
        abort(404)
    return send_from_directory(app.static_folder, "public_profile.html")


@app.route("/api/public-profile/<public_slug>", methods=["GET"])
def api_public_profile_by_slug(public_slug):
    """
    Public (no auth) profile data by public_slug. Only STUDENT and ALUMNI.
    Returns safe fields only: no email, phone, resume, verification, internal fields.
    """
    user = db["users"].find_one({"public_slug": public_slug})
    if not user:
        return jsonify({"error": "Profile not found"}), 404
    role = (user.get("role") or user.get("user_type") or "").strip().upper()
    if role not in (ROLE_STUDENT, ROLE_ALUMNI):
        return jsonify({"error": "Profile not found"}), 404
    if user_hidden_from_campuslink_discovery(user):
        return jsonify({"error": "Profile not found"}), 404
    profile = user.get("profile") or {}
    full_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or ""

    if role == ROLE_STUDENT:
        cgpa = user.get("cgpa") or (profile.get("education") or [{}])[0].get("cgpa") if (profile.get("education")) else None
        if cgpa is not None and not isinstance(cgpa, (int, float)):
            try:
                cgpa = float(cgpa)
            except (TypeError, ValueError):
                cgpa = None
        skills = list(profile.get("skills") or [])
        if isinstance(skills, list):
            skills = [s.get("name", s) if isinstance(s, dict) else str(s) for s in skills]
        projects = list(profile.get("projects") or [])
        certifications = list(profile.get("certifications") or [])
        placement_status = user.get("placement_status")
        return jsonify({
            "role": "STUDENT",
            "name": full_name,
            "branch": user.get("branch") or user.get("branch_code") or "",
            "cgpa": cgpa,
            "skills": skills,
            "projects": projects,
            "certifications": certifications,
            "linkedin_url": profile.get("linkedin_url"),
            "portfolio_url": profile.get("portfolio_url"),
            "placement_status": placement_status,
            "about": (profile.get("about") or "").strip() or None,
        }), 200

    if role == ROLE_ALUMNI:
        skills = list(profile.get("skills") or [])
        if isinstance(skills, list):
            skills = [s.get("name", s) if isinstance(s, dict) else str(s) for s in skills]
        company = profile.get("current_company") or ""
        designation = profile.get("designation") or ""
        mentorship_availability = profile.get("mentorship_availability") or profile.get("open_to_mentorship") or True
        return jsonify({
            "role": "ALUMNI",
            "name": full_name,
            "company": company,
            "designation": designation,
            "skills": skills,
            "mentorship_availability": mentorship_availability,
            "linkedin_url": profile.get("linkedin_url"),
            "about": (profile.get("bio") or profile.get("about") or "").strip() or None,
        }), 200

    return jsonify({"error": "Profile not found"}), 404


@app.route("/api/profile/share-info", methods=["GET"])
@login_required
def api_profile_share_info():
    """Return public_profile_url and qr_code_url for current user (STUDENT/ALUMNI only)."""
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    role = (user.get("role") or user.get("user_type") or "").strip().upper()
    if role not in (ROLE_STUDENT, ROLE_ALUMNI):
        return jsonify({"error": "Not available for your role"}), 403
    slug = user.get("public_slug")
    if not slug:
        return jsonify({"error": "Public profile not ready"}), 404
    base_url = (request.host_url or "").rstrip("/") or "https://yourdomain.com"
    return jsonify({
        "public_slug": slug,
        "public_profile_url": f"{base_url}/profile/{slug}",
        "qr_code_url": user.get("qr_code_url") or None,
    }), 200


@app.route("/api/users/<user_id>/profile", methods=["GET"])
@login_required
def api_public_profile(user_id):
    """
    Get any user's public profile for viewing.
    Returns profile data visible to other users.
    """
    current_user = get_logged_in_user()
    if not current_user:
        return jsonify({"error": "Not authenticated"}), 401

    try:
        oid = ObjectId(user_id)
    except Exception:
        return jsonify({"error": "Invalid user id"}), 400

    user = db["users"].find_one({"_id": oid})
    if not user:
        return jsonify({"error": "User not found"}), 404
    role_ut = (user.get("role") or user.get("user_type") or "").strip().upper()
    ut_lower = (user.get("user_type") or "").strip().lower()
    if role_ut == ROLE_FACULTY or ut_lower == "faculty":
        return jsonify({"error": "Profile not available"}), 404
    if role_ut == ROLE_COORDINATOR or ut_lower == "coordinator":
        return jsonify({"error": "Profile not available"}), 404

    is_own_profile = str(current_user["_id"]) == str(user["_id"])
    if not is_own_profile and user_hidden_from_campuslink_discovery(user):
        return jsonify({"error": "User not found"}), 404

    profile = user.get("profile") or {}
    full_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or None

    # Check connection status
    connection_status = None
    connection_id = None
    is_requester = False
    if not is_own_profile:
        connection = db["connections"].find_one({
            "$or": [
                {"requester_id": current_user["_id"], "recipient_id": user["_id"]},
                {"requester_id": user["_id"], "recipient_id": current_user["_id"]}
            ]
        })
        if connection:
            connection_status = connection.get("status")
            connection_id = str(connection.get("_id"))
            is_requester = connection.get("requester_id") == current_user["_id"]
    
    # Count connections
    connection_count = db["connections"].count_documents({
        "$or": [
            {"requester_id": user["_id"], "status": CONNECTION_ACCEPTED},
            {"recipient_id": user["_id"], "status": CONNECTION_ACCEPTED}
        ]
    })

    # Mentoring availability: when viewer is student and profile owner is alumni
    mentoring_availability = None
    if not is_own_profile and (current_user.get("user_type") or "").strip().lower() == "student" and (user.get("user_type") or "").strip().lower() == "alumni":
        mentees = user.get("mentees") or []
        slots_full = len(mentees) >= MAX_ALUMNI_MENTEES
        has_mentor = current_user.get("mentor_id") is not None
        has_pending = db["mentoring_requests"].find_one({
            "student_id": current_user["_id"],
            "alumni_id": user["_id"],
            "status": "pending",
        }) is not None
        mentorship_settings = (user.get("alumni_settings") or {}).get("mentorship") or {}
        accepting_requests = mentorship_settings.get("allow_mentorship_requests") is not False
        can_request = accepting_requests and not has_mentor and not slots_full and not has_pending
        mentoring_availability = {
            "can_request": can_request,
            "slots_full": slots_full,
            "has_pending": has_pending,
            "has_mentor": has_mentor,
            "accepting_requests": accepting_requests,
        }

    # Get user's status (Student/Intern/Placed)
    user_status = "Student"
    if profile.get("current_status"):
        user_status = profile.get("current_status")
    elif profile.get("experience") and len(profile.get("experience", [])) > 0:
        user_status = "Intern"

    # Sort profile sections reverse chronologically for display (do not mutate stored profile)
    profile_data = {
        "education": list(profile.get("education") or []),
        "experience": list(profile.get("experience") or []),
        "projects": list(profile.get("projects") or []),
        "clubs": list(profile.get("clubs") or []),
        "certifications": list(profile.get("certifications") or []),
        "achievements": list(profile.get("achievements") or []),
    }
    sort_profile_sections_reverse_chronological(profile_data)

    return jsonify({
        "user": {
            "id": str(user.get("_id")),
            "name": full_name,
            "first_name": user.get("first_name"),
            "last_name": user.get("last_name"),
            "email": user.get("email") if is_own_profile else None,
            "branch": user.get("branch") or user.get("branch_code"),
            "roll_number": user.get("roll_number"),
            "user_type": user.get("user_type"),
            "verification_status": user.get("verification_status"),
            "profile_photo": profile.get("profile_photo"),
            "cover_photo": profile.get("cover_photo"),
            "headline": profile.get("headline") or profile.get("basic", {}).get("headline"),
            "location": profile.get("location") or profile.get("basic", {}).get("location"),
            "current_status": user_status,
            "connection_count": connection_count,
        },
        "profile": {
            "about": profile.get("about") or "",
            "cover_photo": profile.get("cover_photo"),
            "education": profile_data["education"],
            "experience": profile_data["experience"],
            "projects": profile_data["projects"],
            "skills": profile.get("skills") or [],
            "clubs": profile_data["clubs"],
            "certifications": profile_data["certifications"],
            "achievements": profile_data["achievements"],
            "student_resources": profile.get("student_resources") or profile.get("notes_for_students") or [],
            "languages": profile.get("languages") or [],
            "resume": None,
        },
        "is_own_profile": is_own_profile,
        "connection_status": connection_status,
        "connection_id": connection_id,
        "is_connection_requester": is_requester,
        "mentoring_availability": mentoring_availability,
    }), 200


# ---------- Mentor view profile (minimal, view-only for alumni reviewing student) ----------
@app.route("/mentor-view-profile/<student_id>")
@login_required
def mentor_view_profile_page(student_id):
    """Serve minimal view-only student profile for alumni who have pending/accepted request from this student."""
    alumni = get_logged_in_user()
    if not alumni or (alumni.get("user_type") or "").strip().lower() != "alumni":
        abort(403)
    try:
        student_oid = ObjectId(student_id)
    except Exception:
        abort(404)
    allowed = db["mentoring_requests"].find_one({
        "alumni_id": alumni["_id"],
        "student_id": student_oid,
        "status": {"$in": ["pending", "accepted"]},
    })
    if not allowed:
        abort(403)
    return send_from_directory(app.static_folder, "mentor_view_profile.html")


@app.route("/api/mentor-view-profile/<student_id>", methods=["GET"])
@login_required
def api_mentor_view_profile(student_id):
    """Return full student profile for mentor view. Alumni can view only if they have pending/accepted request."""
    alumni = get_logged_in_user()
    if not alumni or (alumni.get("user_type") or "").strip().lower() != "alumni":
        return jsonify({"error": "Forbidden"}), 403
    try:
        student_oid = ObjectId(student_id)
    except Exception:
        return jsonify({"error": "Invalid student id"}), 400
    allowed = db["mentoring_requests"].find_one({
        "alumni_id": alumni["_id"],
        "student_id": student_oid,
        "status": {"$in": ["pending", "accepted"]},
    })
    if not allowed:
        return jsonify({"error": "Forbidden"}), 403
    student = db["users"].find_one({"_id": student_oid, "user_type": "student"})
    if not student:
        return jsonify({"error": "Student not found"}), 404
    profile = _profile_for_user(student)
    profile_data = {
        "education": list(profile.get("education") or []),
        "experience": list(profile.get("experience") or []),
        "projects": list(profile.get("projects") or []),
        "clubs": list(profile.get("clubs") or []),
        "certifications": list(profile.get("certifications") or []),
        "achievements": list(profile.get("achievements") or []),
    }
    sort_profile_sections_reverse_chronological(profile_data)
    return jsonify({
        "user": {
            "id": str(student["_id"]),
            "name": f"{student.get('first_name', '')} {student.get('last_name', '')}".strip(),
            "email": student.get("email"),
            "branch": student.get("branch_code") or student.get("branch"),
            "headline": profile.get("headline") or (profile.get("basic") or {}).get("headline"),
            "profile_photo": profile.get("profile_photo"),
        },
        "profile": {
            "about": profile.get("about") or "",
            "education": profile_data["education"],
            "experience": profile_data["experience"],
            "projects": profile_data["projects"],
            "skills": profile.get("skills") or [],
            "clubs": profile_data["clubs"],
            "certifications": profile_data["certifications"],
            "achievements": profile_data["achievements"],
        },
    }), 200


# ---------- Activity APIs ----------
@app.route("/api/users/<user_id>/activity", methods=["GET"])
@login_required
def api_user_activity(user_id):
    """
    Get a user's activity feed.
    Query params: type (post|comment|reaction|application), limit
    """
    current_user = get_logged_in_user()
    if not current_user:
        return jsonify({"error": "Not authenticated"}), 401

    try:
        oid = ObjectId(user_id)
    except Exception:
        return jsonify({"error": "Invalid user id"}), 400

    user = db["users"].find_one({"_id": oid})
    if not user:
        return jsonify({"error": "User not found"}), 404

    activity_type = request.args.get("type")
    limit = min(int(request.args.get("limit", 10)), 50)

    activities = get_user_activities(oid, activity_type, limit)
    
    # Enrich activities with reference data
    enriched = []
    for activity in activities:
        ref_id = activity.get("reference_id")
        ref_type = activity.get("reference_type")
        
        reference_data = {}
        if ref_type == "job" and ref_id:
            try:
                job = db["job_posts"].find_one({"_id": ObjectId(ref_id)})
                if job:
                    reference_data = {
                        "title": f"{job.get('role')} at {job.get('company_name')}",
                        "company": job.get("company_name"),
                        "role": job.get("role"),
                    }
            except Exception:
                pass
        elif ref_type == "post" and ref_id:
            try:
                post = db["posts"].find_one({"_id": ObjectId(ref_id)})
                if post:
                    reference_data = {
                        "title": post.get("title") or post.get("content", "")[:100],
                        "content_preview": (post.get("content") or "")[:200],
                    }
            except Exception:
                pass
        elif ref_type == "announcement" and ref_id:
            try:
                ann = db["announcements"].find_one({"_id": ObjectId(ref_id)})
                if ann:
                    reference_data = {
                        "title": ann.get("title"),
                        "content_preview": ((ann.get("description") or ann.get("body") or ""))[:200],
                    }
            except Exception:
                pass
        
        activity["reference_data"] = reference_data
        enriched.append(activity)

    return jsonify({"activities": enriched}), 200


# ---------- Posts API (for Activity tracking) ----------
@app.route("/api/posts", methods=["GET", "POST"])
@login_required
def api_posts():
    """
    GET: List recent posts
    POST: Create a new post (and track activity)
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    if request.method == "GET":
        limit = min(max(int(request.args.get("limit", 20)), 1), 100)
        skip = max(int(request.args.get("skip", 0)), 0)
        posts = []
        for doc in db["posts"].find({}).sort("created_at", -1).skip(skip).limit(limit):
            author = db["users"].find_one({"_id": doc.get("author_id")})
            author_name = f"{author.get('first_name', '')} {author.get('last_name', '')}".strip() if author else "Unknown"
            post_id = doc.get("_id")
            liked = bool(user and db["likes"].find_one({"post_id": post_id, "user_id": user["_id"]}))
            content = doc.get("content") or doc.get("description") or ""
            posts.append({
                "id": str(post_id),
                "content": content,
                "description": content,
                "body": content,
                "title": doc.get("title"),
                "post_type": doc.get("post_type") or "text",
                "media_url": doc.get("media_url"),
                "media_urls": doc.get("media_urls") or [],
                "media": doc.get("media") or [],
                "hashtags": doc.get("hashtags") or [],
                "tagged_users": [str(x) for x in (doc.get("tagged_users") or []) if x],
                "author_id": str(doc.get("author_id")),
                "author_name": author_name,
                "author": {"name": author_name, "role": (author.get("role") or "STUDENT") if author else "STUDENT"},
                "author_headline": (author.get("profile") or {}).get("headline") if author else None,
                "branch": (author.get("branch_code") or author.get("branch") or "") if author else "",
                "likes_count": doc.get("likes_count", 0),
                "comments_count": doc.get("comments_count", 0),
                "liked": liked,
                "created_at": doc.get("created_at").isoformat() if isinstance(doc.get("created_at"), datetime) else None,
            })
        return jsonify({"posts": posts}), 200

    # POST - Create new post
    data = request.get_json(silent=True) or {}
    content = _clean_multiline_str(data.get("content"), 2000) or ""
    
    if not content:
        return jsonify({"error": "Content is required"}), 400

    hashtags = []
    for m in re.findall(r"#([A-Za-z0-9_]{1,40})", content):
        t = m.lower()
        if t not in hashtags:
            hashtags.append(t)

    tagged_ids_raw = data.get("tagged_users") or []
    if not isinstance(tagged_ids_raw, list):
        tagged_ids_raw = []
    tagged_user_ids = []
    tagged_user_info = []
    seen = set()
    for raw_id in tagged_ids_raw:
        try:
            oid = ObjectId(str(raw_id))
        except Exception:
            continue
        if oid in seen:
            continue
        udoc = db["users"].find_one({"_id": oid}, {"first_name": 1, "last_name": 1, "role": 1})
        if not udoc:
            continue
        role = (udoc.get("role") or "").upper()
        if role not in {"STUDENT", "ALUMNI"}:
            continue
        seen.add(oid)
        tagged_user_ids.append(oid)
        tagged_user_info.append({
            "id": str(oid),
            "name": f"{udoc.get('first_name', '')} {udoc.get('last_name', '')}".strip() or "User",
            "role": role,
        })

    pst = _parse_post_settings_from_payload(data)
    post_doc = {
        "author_id": user["_id"],
        "post_type": "text",
        "content": content,
        "title": None,
        "description": content,
        "media_url": None,
        "hashtags": hashtags,
        "tagged_users": tagged_user_ids,
        "tagged_user_info": tagged_user_info,
        "likes": [],
        "likes_count": 0,
        "comments_count": 0,
        "settings": pst,
        "created_at": datetime.utcnow(),
    }
    
    result = db["posts"].insert_one(post_doc)
    
    # Track activity
    create_activity(
        user["_id"], 
        ACTIVITY_TYPE_POST, 
        result.inserted_id, 
        "post",
        {"content_preview": content[:100]}
    )
    sender_name = _user_display_name(user)
    for tagged_id in tagged_user_ids:
        create_post_notification(
            tagged_id,
            user["_id"],
            "mention",
            result.inserted_id,
            f"{sender_name} mentioned you in a post",
        )

    return jsonify({
        "message": "Post created",
        "id": str(result.inserted_id)
    }), 201


@app.route("/posts", methods=["GET"])
@login_required
def paginated_posts_alias():
    """
    Backward-compatible paginated posts endpoint for feed clients.
    Returns only STUDENT/ALUMNI media posts.
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    limit = min(max(int(request.args.get("limit", 10)), 1), 50)
    skip = max(int(request.args.get("skip", 0)), 0)
    posts = []
    cursor = db["posts"].find({}).sort("created_at", -1).skip(skip).limit(limit + 1)
    for doc in cursor:
        author = db["users"].find_one({"_id": doc.get("author_id")})
        role = ((author.get("role") or "STUDENT") if author else "STUDENT").upper()
        if role not in {"STUDENT", "ALUMNI"}:
            continue
        media_items = list(doc.get("media") or [])
        media_urls = [str(x).strip() for x in (doc.get("media_urls") or []) if isinstance(x, str) and str(x).strip()]
        media_url = (doc.get("media_url") or "").strip() if isinstance(doc.get("media_url"), str) else ""
        if not media_items:
            for u in media_urls:
                media_items.append({"type": ("video" if u.lower().endswith(".mp4") else "image"), "url": u})
            if media_url and media_url not in media_urls:
                media_items.insert(0, {"type": ("video" if media_url.lower().endswith(".mp4") else "image"), "url": media_url})
        if not media_items:
            continue
        author_name = f"{author.get('first_name', '')} {author.get('last_name', '')}".strip() if author else "Unknown"
        inter = _serialize_post_interaction_fields(doc, user)
        posts.append({
            "id": str(doc.get("_id")),
            "author_id": str(doc.get("author_id")),
            "author": {"name": author_name, "role": role},
            "author_profile_photo": _user_profile_photo_url(author),
            "content": doc.get("content") or "",
            "media_url": media_url,
            "media_urls": media_urls,
            "media": media_items,
            "hashtags": doc.get("hashtags") or [],
            "tagged_users": [str(x) for x in (doc.get("tagged_users") or []) if x],
            "tagged_user_info": doc.get("tagged_user_info") or [],
            "likes_count": inter["likes_count"],
            "comments_count": inter["comments_count"],
            "liked": inter["liked"],
            "settings": inter["settings"],
            "likes_count_hidden": inter["likes_count_hidden"],
            "comments_count_hidden": inter["comments_count_hidden"],
            "created_at": doc.get("created_at").isoformat() if isinstance(doc.get("created_at"), datetime) else None,
        })
    has_more = len(posts) > limit
    posts = posts[:limit]
    return jsonify({"posts": posts, "has_more": has_more, "next_skip": skip + len(posts)}), 200


@app.route("/api/posts/media", methods=["POST"])
@login_required
def api_posts_media():
    """
    Create a media-first post.
    Rules:
    - media file is required
    - text is optional
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    content = _clean_multiline_str(request.form.get("content"), 2000) or ""
    caption = content
    # hashtag extraction, e.g. #placement
    hashtags = []
    for m in re.findall(r"#([A-Za-z0-9_]{1,40})", caption):
        t = m.lower()
        if t not in hashtags:
            hashtags.append(t)

    tagged_ids_raw = request.form.getlist("tagged_users[]") or request.form.getlist("tagged_users")
    tagged_user_ids = []
    tagged_user_info = []
    seen_tagged = set()
    for raw_id in tagged_ids_raw:
        try:
            oid = ObjectId(str(raw_id))
        except Exception:
            continue
        if oid in seen_tagged:
            continue
        udoc = db["users"].find_one({"_id": oid}, {"first_name": 1, "last_name": 1, "role": 1})
        if not udoc:
            continue
        role = (udoc.get("role") or "").upper()
        if role not in {"STUDENT", "ALUMNI"}:
            continue
        seen_tagged.add(oid)
        tagged_user_ids.append(oid)
        tagged_user_info.append({
            "id": str(oid),
            "name": f"{udoc.get('first_name', '')} {udoc.get('last_name', '')}".strip() or "User",
            "role": role,
        })
    media_file = request.files.get("file") or request.files.get("media")
    if not media_file or not media_file.filename:
        return jsonify({"error": "Media file is required."}), 400
    ext = _extract_file_ext(media_file.filename)
    if ext in ALLOWED_IMAGE_EXTENSIONS:
        max_size = MAX_IMAGE_SIZE
        resource_type = "image"
        media_type = "image"
    elif ext in ALLOWED_VIDEO_EXTENSIONS:
        max_size = MAX_VIDEO_SIZE
        resource_type = "video"
        media_type = "video"
    else:
        return jsonify({"error": "Only JPG/JPEG/PNG/MP4 are allowed."}), 400
    try:
        media_file.stream.seek(0, os.SEEK_END)
        size = media_file.stream.tell()
        media_file.stream.seek(0)
    except Exception:
        size = None
    if size and size > max_size:
        return jsonify({"error": "Media file exceeds allowed size."}), 400
    uploaded, upload_err = upload_to_cloudinary(
        media_file,
        _cloudinary_user_folder_path(user, "posts"),
        resource_type=resource_type,
        public_id_prefix="post_media",
    )
    if upload_err:
        return jsonify({"error": upload_err}), 400
    primary_media_url = uploaded.get("secure_url")
    media_items = [{"type": media_type, "url": primary_media_url}]
    image_urls = [primary_media_url] if media_type == "image" else []

    pst = _parse_post_settings_from_form()
    post_doc = {
        "author_id": user["_id"],
        "post_type": "media",
        "content": caption,
        "title": None,
        "description": caption,
        "media_url": primary_media_url,
        "media_urls": image_urls,
        "media": media_items,
        "media_type": media_type,
        "hashtags": hashtags,
        "tagged_users": tagged_user_ids,
        "tagged_user_info": tagged_user_info,
        "likes": [],
        "likes_count": 0,
        "comments_count": 0,
        "settings": pst,
        "created_at": datetime.utcnow(),
    }

    result = db["posts"].insert_one(post_doc)
    create_activity(
        user["_id"],
        ACTIVITY_TYPE_POST,
        result.inserted_id,
        "post",
        {"content_preview": (content[:100] if content else "Media post"), "post_type": "media"},
    )
    sender_name = _user_display_name(user)
    for tagged_id in tagged_user_ids:
        create_post_notification(
            tagged_id,
            user["_id"],
            "mention",
            result.inserted_id,
            f"{sender_name} mentioned you in a post",
        )

    return jsonify({"message": "Post created", "id": str(result.inserted_id)}), 201


@app.route("/api/posts/<post_id>/comments", methods=["GET", "POST"])
@login_required
def api_post_comments(post_id):
    """
    GET: List comments on a post
    POST: Add a comment to a post (and track activity)
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    try:
        oid = ObjectId(post_id)
    except Exception:
        return jsonify({"error": "Invalid post id"}), 400

    post = db["posts"].find_one({"_id": oid})
    if not post:
        return jsonify({"error": "Post not found"}), 404

    if request.method == "GET":
        comments = []
        for doc in db["comments"].find({"post_id": oid, "parent_id": None}).sort("created_at", -1):
            author = db["users"].find_one({"_id": doc.get("user_id")})
            author_name = f"{author.get('first_name', '')} {author.get('last_name', '')}".strip() if author else "Unknown"
            likes = list(doc.get("likes") or [])
            comments.append({
                "id": str(doc.get("_id")),
                "content": doc.get("text") or doc.get("content"),
                "author_id": str(doc.get("user_id") or doc.get("author_id")),
                "author_name": author_name,
                "likes_count": len(likes),
                "created_at": doc.get("created_at").isoformat() if isinstance(doc.get("created_at"), datetime) else None,
            })
        return jsonify({"comments": comments}), 200

    # POST - Add comment
    data = request.get_json(silent=True) or {}
    content = _clean_str(data.get("content"), 2000) or ""
    
    if not content:
        return jsonify({"error": "Content is required"}), 400

    if not _normalized_post_settings(post.get("settings"))["comments_enabled"]:
        return jsonify({"error": "Comments are turned off for this post."}), 403

    now = datetime.utcnow()
    comment_doc = {
        "post_id": oid,
        "user_id": user["_id"],
        "text": content,
        "parent_id": None,
        "likes": [],
        "created_at": now,
        "updated_at": now,
    }
    
    result = db["comments"].insert_one(comment_doc)
    _recompute_post_comments_count(oid)
    
    # Track activity
    create_activity(
        user["_id"], 
        ACTIVITY_TYPE_COMMENT, 
        oid, 
        "post",
        {"content_preview": content[:100], "post_preview": (post.get("content") or "")[:50]}
    )
    create_post_notification(
        post.get("author_id"),
        user["_id"],
        "comment",
        oid,
        f"{_user_display_name(user)} commented on your post",
    )
    _notify_comment_mentions_in_text(oid, user, content)

    return jsonify({
        "message": "Comment added",
        "id": str(result.inserted_id)
    }), 201


def _serialize_embedded_comment(comment_obj: dict):
    if not isinstance(comment_obj, dict):
        return None
    author_id = comment_obj.get("user_id") or comment_obj.get("author_id")
    author = db["users"].find_one({"_id": author_id}, {"first_name": 1, "last_name": 1, "name": 1}) if author_id else None
    author_name = _user_display_name(author) if author else "Unknown"
    text = _clean_str(comment_obj.get("text") or comment_obj.get("content"), 2000) or ""
    ts = comment_obj.get("timestamp") or comment_obj.get("created_at")
    replies_out = []
    for reply in (comment_obj.get("replies") or []):
        if not isinstance(reply, dict):
            continue
        r_author_id = reply.get("user_id") or reply.get("author_id")
        r_author = db["users"].find_one({"_id": r_author_id}, {"first_name": 1, "last_name": 1, "name": 1}) if r_author_id else None
        r_name = _user_display_name(r_author) if r_author else "Unknown"
        r_text = _clean_str(reply.get("text") or reply.get("content"), 2000) or ""
        r_ts = reply.get("timestamp") or reply.get("created_at")
        replies_out.append({
            "user_id": str(r_author_id) if r_author_id else None,
            "author_name": r_name,
            "text": r_text,
            "timestamp": to_utc_iso(r_ts),
        })
    replies_out.sort(key=lambda r: r.get("timestamp") or "", reverse=False)
    return {
        "user_id": str(author_id) if author_id else None,
        "author_name": author_name,
        "text": text,
        "timestamp": to_utc_iso(ts),
        "replies": replies_out,
    }


@app.route("/comments/<post_id>", methods=["GET"])
@login_required
def api_comments_by_post(post_id):
    """
    Fetch comments for one post.
    Defaults to latest 2 top-level comments (newest first); ?all=1 expands reply previews in feed.
    ?page=1&per_page=20 paginates top-level comments (full replies under each parent).
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        oid = ObjectId(post_id)
    except Exception:
        return jsonify({"error": "Invalid post id"}), 400

    post = db["posts"].find_one({"_id": oid}, {"comments_count": 1})
    if not post:
        return jsonify({"error": "Post not found"}), 404

    comments_coll = db["comments"]
    parent_query = {"post_id": oid, "parent_id": None}
    total_count = comments_coll.count_documents({"post_id": oid})
    total_parents = comments_coll.count_documents(parent_query)

    _uproj = {"first_name": 1, "last_name": 1, "name": 1, "profile": 1, "user_type": 1, "role": 1}

    page_param = request.args.get("page")
    if page_param is not None and str(page_param).strip() != "":
        try:
            page = max(int(page_param), 1)
        except Exception:
            page = 1
        per_page = min(max(int(request.args.get("per_page", 20)), 1), 100)
        skip = (page - 1) * per_page
        all_flag = True
        parent_cursor = comments_coll.find(parent_query).sort("created_at", -1).skip(skip).limit(per_page)
        has_more = (skip + per_page) < total_parents
    else:
        page = None
        per_page = None
        has_more = None
        all_flag = str(request.args.get("all", "")).lower() in {"1", "true", "yes"}
        limit = max(int(request.args.get("limit", 2)), 1)
        parent_cursor = comments_coll.find(parent_query).sort("created_at", -1)
        if not all_flag:
            parent_cursor = parent_cursor.limit(limit)

    comments = []
    for doc in parent_cursor:
        author = db["users"].find_one({"_id": doc.get("user_id")}, _uproj)
        replies_cursor = comments_coll.find({"parent_id": doc.get("_id")}).sort("created_at", 1)
        replies_all = []
        for rdoc in replies_cursor:
            r_author = db["users"].find_one({"_id": rdoc.get("user_id")}, _uproj)
            r_likes = list(rdoc.get("likes") or [])
            r_likes = [ObjectId(x) if isinstance(x, str) else x for x in r_likes]
            replies_all.append({
                "id": str(rdoc.get("_id")),
                "user_id": str(rdoc.get("user_id")) if rdoc.get("user_id") else None,
                "author_name": _user_display_name(r_author),
                "author_profile_photo": _user_profile_photo_url(r_author),
                "text": _clean_str(rdoc.get("text") or rdoc.get("content"), 2000) or "",
                "timestamp": to_utc_iso(rdoc.get("created_at")),
                "updated_at": to_utc_iso(rdoc.get("updated_at")),
                "likes_count": len(r_likes),
                "liked": user.get("_id") in r_likes,
                "parent_id": str(doc.get("_id")),
            })
        reply_preview = replies_all if all_flag else replies_all[:2]
        likes = list(doc.get("likes") or [])
        likes = [ObjectId(x) if isinstance(x, str) else x for x in likes]
        comments.append({
            "id": str(doc.get("_id")),
            "user_id": str(doc.get("user_id")) if doc.get("user_id") else None,
            "parent_id": None,
            "author_name": _user_display_name(author),
            "author_profile_photo": _user_profile_photo_url(author),
            "text": _clean_str(doc.get("text") or doc.get("content"), 2000) or "",
            "timestamp": to_utc_iso(doc.get("created_at")),
            "updated_at": to_utc_iso(doc.get("updated_at")),
            "likes_count": len(likes),
            "liked": user.get("_id") in likes,
            "replies": reply_preview,
            "reply_count": len(replies_all),
            "has_more_replies": (len(replies_all) > len(reply_preview)),
        })

    out: dict = {"comments": comments, "count": total_count, "total_parents": total_parents}
    if page is not None:
        out["page"] = page
        out["per_page"] = per_page
        out["has_more"] = bool(has_more)
    return jsonify(out), 200


@app.route("/api/posts/<post_id>/like", methods=["POST", "DELETE"])
@login_required
def api_post_like(post_id):
    """
    POST: Like a post (and track activity)
    DELETE: Unlike a post
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    try:
        oid = ObjectId(post_id)
    except Exception:
        return jsonify({"error": "Invalid post id"}), 400

    post = db["posts"].find_one({"_id": oid})
    if not post:
        return jsonify({"error": "Post not found"}), 404

    likes = list(post.get("likes") or [])
    likes = [ObjectId(x) if isinstance(x, str) else x for x in likes]
    uid = user["_id"]
    if not likes:
        for ld in db["likes"].find({"post_id": oid}):
            u = ld.get("user_id")
            if u and u not in likes:
                likes.append(u)
        if likes:
            db["posts"].update_one({"_id": oid}, {"$set": {"likes": likes, "likes_count": len(likes)}})

    if request.method == "POST":
        if uid in likes:
            return jsonify({"message": "Already liked", "likes_count": len(likes), "liked": True}), 200
        new_likes = likes + [uid]
        db["posts"].update_one(
            {"_id": oid},
            {"$set": {"likes": new_likes, "likes_count": len(new_likes)}},
        )
        _sync_likes_collection_with_post(oid, uid, True)
        create_activity(
            user["_id"],
            ACTIVITY_TYPE_REACTION,
            oid,
            "post",
            {"reaction_type": "like", "post_preview": (post.get("content") or "")[:50]},
        )
        create_post_notification(
            post.get("author_id"),
            user["_id"],
            "like",
            oid,
            f"{_user_display_name(user)} liked your post",
        )
        return jsonify({"message": "Liked", "likes_count": len(new_likes), "liked": True}), 200

    # DELETE - Unlike
    if uid not in likes:
        return jsonify({"message": "Not liked", "likes_count": len(likes), "liked": False}), 200
    new_likes = [x for x in likes if x != uid]
    db["posts"].update_one(
        {"_id": oid},
        {"$set": {"likes": new_likes, "likes_count": len(new_likes)}},
    )
    _sync_likes_collection_with_post(oid, uid, False)
    return jsonify({"message": "Unliked", "likes_count": len(new_likes), "liked": False}), 200


@app.route("/toggle-like/<post_id>", methods=["POST"])
@login_required
def api_toggle_like(post_id):
    """
    Toggle like on a post. Stores likes as array of user_ids in post document.
    Returns updated like count and liked status as JSON.
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        oid = ObjectId(post_id)
    except Exception:
        return jsonify({"error": "Invalid post id"}), 400
    post = db["posts"].find_one({"_id": oid})
    if not post:
        return jsonify({"error": "Post not found"}), 404
    user_id = user["_id"]
    likes = list(post.get("likes") or [])
    if not all(isinstance(x, ObjectId) for x in likes):
        likes = [ObjectId(x) if isinstance(x, str) else x for x in likes]
    if user_id in likes:
        new_likes = [x for x in likes if x != user_id]
        liked = False
    else:
        new_likes = likes + [user_id]
        liked = True
    db["posts"].update_one(
        {"_id": oid},
        {"$set": {"likes": new_likes, "likes_count": len(new_likes)}}
    )
    _sync_likes_collection_with_post(oid, user_id, liked)
    if liked:
        create_post_notification(
            post.get("author_id"),
            user["_id"],
            "like",
            oid,
            f"{_user_display_name(user)} liked your post",
        )
    updated = db["posts"].find_one({"_id": oid}) or post
    inter = _serialize_post_interaction_fields(updated, user)
    return jsonify({
        "likes_count": inter["likes_count"],
        "liked": inter["liked"],
        "likes_count_hidden": inter["likes_count_hidden"],
    }), 200


@app.route("/add-comment/<post_id>", methods=["POST"])
@login_required
def api_add_comment(post_id):
    """
    Add a comment to a post. Stores comments in post document as
    [{ user_id, text, timestamp }, ...]. Returns updated comment count and comment object.
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    data = request.get_json(silent=True) or {}
    text = _clean_str(data.get("text") or data.get("content"), 2000) or ""
    if not text:
        return jsonify({"error": "Comment text is required"}), 400
    try:
        oid = ObjectId(post_id)
    except Exception:
        return jsonify({"error": "Invalid post id"}), 400
    post = db["posts"].find_one({"_id": oid})
    if not post:
        return jsonify({"error": "Post not found"}), 404
    if not _normalized_post_settings(post.get("settings"))["comments_enabled"]:
        return jsonify({"error": "Comments are turned off for this post."}), 403
    now = datetime.utcnow()
    insert_result = db["comments"].insert_one({
        "post_id": oid,
        "user_id": user["_id"],
        "text": text,
        "parent_id": None,
        "likes": [],
        "created_at": now,
        "updated_at": now,
    })
    new_count = _recompute_post_comments_count(oid)
    create_post_notification(
        post.get("author_id"),
        user["_id"],
        "comment",
        oid,
        f"{_user_display_name(user)} commented on your post",
    )
    _notify_comment_mentions_in_text(oid, user, text)
    return jsonify({
        "comments_count": new_count,
        "comment": {
            "id": str(insert_result.inserted_id),
            "user_id": str(user["_id"]),
            "author_name": _user_display_name(user),
            "text": text,
            "timestamp": now.isoformat(),
            "updated_at": now.isoformat(),
            "likes_count": 0,
            "liked": False,
            "replies": [],
            "reply_count": 0,
            "has_more_replies": False,
        },
    }), 201


@app.route("/add-reply/<comment_id>", methods=["POST"])
@login_required
def api_add_reply(comment_id):
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    data = request.get_json(silent=True) or {}
    text = _clean_str(data.get("text") or data.get("content"), 2000) or ""
    if not text:
        return jsonify({"error": "Reply text is required"}), 400
    try:
        parent_oid = ObjectId(comment_id)
    except Exception:
        return jsonify({"error": "Invalid comment id"}), 400
    parent = db["comments"].find_one({"_id": parent_oid})
    if not parent:
        return jsonify({"error": "Comment not found"}), 404
    if parent.get("parent_id"):
        return jsonify({"error": "Replies can only be added to top-level comments"}), 400
    post_for_reply = db["posts"].find_one({"_id": parent.get("post_id")})
    if post_for_reply and not _normalized_post_settings(post_for_reply.get("settings"))["comments_enabled"]:
        return jsonify({"error": "Comments are turned off for this post."}), 403
    now = datetime.utcnow()
    result = db["comments"].insert_one({
        "post_id": parent.get("post_id"),
        "user_id": user["_id"],
        "text": text,
        "parent_id": parent_oid,
        "likes": [],
        "created_at": now,
        "updated_at": now,
    })
    if parent.get("post_id"):
        _recompute_post_comments_count(parent["post_id"])
    parent_author = parent.get("user_id")
    if parent_author and parent_author != user["_id"]:
        create_post_notification(
            parent_author,
            user["_id"],
            "comment",
            parent.get("post_id"),
            f"{_user_display_name(user)} replied to your comment",
        )
    _notify_comment_mentions_in_text(parent.get("post_id"), user, text)
    return jsonify({
        "message": "Reply added",
        "reply": {
            "id": str(result.inserted_id),
            "user_id": str(user["_id"]),
            "author_name": _user_display_name(user),
            "text": text,
            "timestamp": now.isoformat(),
            "updated_at": now.isoformat(),
            "likes_count": 0,
            "liked": False,
            "parent_id": str(parent_oid),
        },
    }), 201


@app.route("/toggle-comment-like/<comment_id>", methods=["POST"])
@login_required
def api_toggle_comment_like(comment_id):
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        oid = ObjectId(comment_id)
    except Exception:
        return jsonify({"error": "Invalid comment id"}), 400
    cdoc = db["comments"].find_one({"_id": oid})
    if not cdoc:
        return jsonify({"error": "Comment not found"}), 404
    likes = list(cdoc.get("likes") or [])
    likes = [ObjectId(x) if isinstance(x, str) else x for x in likes]
    uid = user["_id"]
    if uid in likes:
        likes = [x for x in likes if x != uid]
        liked = False
    else:
        likes.append(uid)
        liked = True
    db["comments"].update_one({"_id": oid}, {"$set": {"likes": likes, "updated_at": datetime.utcnow()}})
    if liked:
        author_id = cdoc.get("user_id")
        post_oid = cdoc.get("post_id")
        if author_id and author_id != uid and post_oid:
            create_notification(
                author_id,
                f"{_user_display_name(user)} liked your comment",
                notification_type="comment_like",
                reference_id=oid,
                reference_type="comment",
                post_id=post_oid,
                sender_id=user["_id"],
                metadata={"comment_id": str(oid), "post_id": str(post_oid)},
            )
    return jsonify({"likes_count": len(likes), "liked": liked}), 200


@app.route("/edit-comment/<comment_id>", methods=["POST"])
@login_required
def api_edit_comment(comment_id):
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        oid = ObjectId(comment_id)
    except Exception:
        return jsonify({"error": "Invalid comment id"}), 400
    cdoc = db["comments"].find_one({"_id": oid})
    if not cdoc:
        return jsonify({"error": "Comment not found"}), 404
    if str(cdoc.get("user_id")) != str(user.get("_id")):
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    text = _clean_str(data.get("text") or data.get("content"), 2000) or ""
    if not text:
        return jsonify({"error": "Comment text is required"}), 400
    now = datetime.utcnow()
    db["comments"].update_one({"_id": oid}, {"$set": {"text": text, "updated_at": now}})
    return jsonify({"message": "Comment updated", "text": text, "updated_at": now.isoformat()}), 200


@app.route("/delete-comment/<comment_id>", methods=["POST"])
@login_required
def api_delete_comment(comment_id):
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        oid = ObjectId(comment_id)
    except Exception:
        return jsonify({"error": "Invalid comment id"}), 400
    cdoc = db["comments"].find_one({"_id": oid})
    if not cdoc:
        return jsonify({"error": "Comment not found"}), 404
    if str(cdoc.get("user_id")) != str(user.get("_id")):
        return jsonify({"error": "Forbidden"}), 403
    post_id = cdoc.get("post_id")
    delete_query = {"$or": [{"_id": oid}, {"parent_id": oid}]}
    db["comments"].delete_many(delete_query)
    if post_id:
        _recompute_post_comments_count(post_id)
    return jsonify({"message": "Comment deleted"}), 200


@app.route("/edit-post/<post_id>", methods=["POST"])
@login_required
def api_edit_post(post_id):
    """
    Edit post caption/hashtags/tagged users for post owner only.
    Media remains required and unchanged.
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        oid = ObjectId(post_id)
    except Exception:
        return jsonify({"error": "Invalid post id"}), 400
    post = db["posts"].find_one({"_id": oid})
    if not post:
        return jsonify({"error": "Post not found"}), 404
    if str(post.get("author_id")) != str(user.get("_id")):
        return jsonify({"error": "Forbidden"}), 403
    has_media = bool(post.get("media_url") or (post.get("media_urls") or []) or (post.get("media") or []))
    if not has_media:
        return jsonify({"error": "Post media is required"}), 400

    data = request.get_json(silent=True) or {}
    caption = _clean_multiline_str(data.get("content") or data.get("caption"), 2000) or ""
    hashtags = []
    for m in re.findall(r"#([A-Za-z0-9_]{1,40})", caption):
        t = m.lower()
        if t not in hashtags:
            hashtags.append(t)

    tagged_ids_raw = data.get("tagged_users") or []
    if not isinstance(tagged_ids_raw, list):
        tagged_ids_raw = []
    tagged_user_ids = []
    tagged_user_info = []
    seen = set()
    for raw_id in tagged_ids_raw:
        try:
            toid = ObjectId(str(raw_id))
        except Exception:
            continue
        if toid in seen:
            continue
        udoc = db["users"].find_one({"_id": toid}, {"first_name": 1, "last_name": 1, "role": 1})
        if not udoc:
            continue
        role = (udoc.get("role") or "").upper()
        if role not in {"STUDENT", "ALUMNI"}:
            continue
        seen.add(toid)
        tagged_user_ids.append(toid)
        tagged_user_info.append({
            "id": str(toid),
            "name": f"{udoc.get('first_name', '')} {udoc.get('last_name', '')}".strip() or "User",
            "role": role,
        })

    prev_tagged = set(str(x) for x in (post.get("tagged_users") or []))
    set_fields = {
        "content": caption,
        "description": caption,
        "hashtags": hashtags,
        "tagged_users": tagged_user_ids,
        "tagged_user_info": tagged_user_info,
        "updated_at": datetime.utcnow(),
    }
    if "settings" in data or any(k in data for k in ("comments_enabled", "show_like_count", "show_comment_count")):
        set_fields["settings"] = _parse_post_settings_from_payload(data)
    db["posts"].update_one(
        {"_id": oid},
        {"$set": set_fields},
    )
    sender_name = _user_display_name(user)
    for tagged_id in tagged_user_ids:
        if str(tagged_id) in prev_tagged:
            continue
        create_post_notification(
            tagged_id,
            user["_id"],
            "mention",
            oid,
            f"{sender_name} mentioned you in a post",
        )
    return jsonify({"message": "Post updated"}), 200


@app.route("/delete-post/<post_id>", methods=["POST"])
@login_required
def api_delete_post(post_id):
    """
    Delete post for owner only. Best-effort Cloudinary cleanup.
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        oid = ObjectId(post_id)
    except Exception:
        return jsonify({"error": "Invalid post id"}), 400
    post = db["posts"].find_one({"_id": oid})
    if not post:
        return jsonify({"error": "Post not found"}), 404
    if str(post.get("author_id")) != str(user.get("_id")):
        return jsonify({"error": "Forbidden"}), 403

    db["posts"].delete_one({"_id": oid})
    db["likes"].delete_many({"post_id": oid})
    db["comments"].delete_many({"post_id": oid})
    return jsonify({"message": "Post deleted"}), 200


@app.route("/hashtag/<tag>")
@login_required
def hashtag_feed_page(tag):
    """
    Hashtag feed query endpoint.
    """
    clean_tag = (tag or "").strip().lower()
    if not clean_tag:
        return jsonify({"tag": "", "posts": []}), 200
    user = get_logged_in_user()
    posts = []
    for doc in db["posts"].find({"hashtags": clean_tag}).sort("created_at", -1):
        media_items = list(doc.get("media") or [])
        media_urls = [str(x).strip() for x in (doc.get("media_urls") or []) if isinstance(x, str) and str(x).strip()]
        media_url = (doc.get("media_url") or "").strip() if isinstance(doc.get("media_url"), str) else None
        if not media_items:
            for u in media_urls:
                media_items.append({"type": ("video" if u.lower().endswith(".mp4") else "image"), "url": u})
            if media_url and media_url not in media_urls:
                media_items.insert(0, {"type": ("video" if media_url.lower().endswith(".mp4") else "image"), "url": media_url})
        if not media_items:
            continue
        author = db["users"].find_one({"_id": doc.get("author_id")})
        role = ((author.get("role") or "STUDENT") if author else "STUDENT").upper()
        if role not in {"STUDENT", "ALUMNI"}:
            continue
        author_name = f"{author.get('first_name', '')} {author.get('last_name', '')}".strip() if author else "Unknown"
        inter = _serialize_post_interaction_fields(doc, user)
        posts.append({
            "id": str(doc.get("_id")),
            "author_id": str(doc.get("author_id")),
            "author": {"name": author_name, "role": role},
            "author_profile_photo": _user_profile_photo_url(author),
            "content": doc.get("content") or "",
            "media_url": media_url,
            "media_urls": media_urls,
            "media": media_items,
            "hashtags": doc.get("hashtags") or [],
            "tagged_users": [str(x) for x in (doc.get("tagged_users") or []) if x],
            "tagged_user_info": doc.get("tagged_user_info") or [],
            "likes_count": inter["likes_count"],
            "comments_count": inter["comments_count"],
            "liked": inter["liked"],
            "settings": inter["settings"],
            "likes_count_hidden": inter["likes_count_hidden"],
            "comments_count_hidden": inter["comments_count_hidden"],
            "created_at": doc.get("created_at").isoformat() if isinstance(doc.get("created_at"), datetime) else None,
        })
    return jsonify({"tag": clean_tag, "posts": posts}), 200


@app.route("/api/posts/<post_id>", methods=["GET"])
@login_required
def api_get_single_post(post_id):
    """Fetch one post payload for share view."""
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        oid = ObjectId(post_id)
    except Exception:
        return jsonify({"error": "Invalid post id"}), 400
    doc = db["posts"].find_one({"_id": oid})
    if not doc:
        return jsonify({"error": "Post not found"}), 404
    author = db["users"].find_one({"_id": doc.get("author_id")})
    author_name = f"{author.get('first_name', '')} {author.get('last_name', '')}".strip() if author else "Unknown"
    inter = _serialize_post_interaction_fields(doc, user)
    media_items = list(doc.get("media") or [])
    media_urls = [str(x).strip() for x in (doc.get("media_urls") or []) if isinstance(x, str) and str(x).strip()]
    media_url = doc.get("media_url")
    if not media_items:
        for u in media_urls:
            media_items.append({"type": ("video" if u.lower().endswith(".mp4") else "image"), "url": u})
        if isinstance(media_url, str) and media_url and media_url not in media_urls:
            media_items.insert(0, {"type": ("video" if media_url.lower().endswith(".mp4") else "image"), "url": media_url})
    return jsonify({
        "post": {
            "id": str(oid),
            "author_id": str(doc.get("author_id")),
            "author": {"name": author_name, "role": ((author.get("role") or "STUDENT") if author else "STUDENT")},
            "author_profile_photo": _user_profile_photo_url(author),
            "content": doc.get("content") or doc.get("description") or "",
            "media_url": doc.get("media_url"),
            "media_urls": media_urls,
            "media": media_items,
            "likes_count": inter["likes_count"],
            "comments_count": inter["comments_count"],
            "liked": inter["liked"],
            "settings": inter["settings"],
            "likes_count_hidden": inter["likes_count_hidden"],
            "comments_count_hidden": inter["comments_count_hidden"],
            "created_at": to_utc_iso(doc.get("created_at")),
        }
    }), 200


@app.route("/api/users/<user_id>/posts", methods=["GET"])
@login_required
def api_user_posts(user_id):
    """Return posts created by one user only, latest first."""
    viewer = get_logged_in_user()
    if not viewer:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        user_oid = ObjectId(user_id)
    except Exception:
        return jsonify({"error": "Invalid user id"}), 400
    user_doc = db["users"].find_one({"_id": user_oid})
    if not user_doc:
        return jsonify({"error": "User not found"}), 404
    if str(viewer["_id"]) != str(user_oid) and user_hidden_from_campuslink_discovery(user_doc):
        return jsonify({"error": "User not found"}), 404
    limit = min(max(int(request.args.get("limit", 3)), 1), 100)
    posts = []
    for doc in db["posts"].find({"author_id": user_oid}).sort("created_at", -1).limit(limit):
        media_items = list(doc.get("media") or [])
        media_urls = [str(x).strip() for x in (doc.get("media_urls") or []) if isinstance(x, str) and str(x).strip()]
        media_url = (doc.get("media_url") or "").strip() if isinstance(doc.get("media_url"), str) else ""
        if not media_items:
            for u in media_urls:
                media_items.append({"type": ("video" if u.lower().endswith(".mp4") else "image"), "url": u})
            if media_url and media_url not in media_urls:
                media_items.insert(0, {"type": ("video" if media_url.lower().endswith(".mp4") else "image"), "url": media_url})
        if not media_items:
            continue
        inter = _serialize_post_interaction_fields(doc, viewer)
        posts.append({
            "id": str(doc.get("_id")),
            "author_id": str(user_oid),
            "author": {"name": _user_display_name(user_doc), "role": (user_doc.get("role") or "STUDENT")},
            "author_profile_photo": _user_profile_photo_url(user_doc),
            "content": doc.get("content") or "",
            "media_url": media_url or None,
            "media_urls": media_urls,
            "media": media_items,
            "likes_count": inter["likes_count"],
            "comments_count": inter["comments_count"],
            "liked": inter["liked"],
            "settings": inter["settings"],
            "likes_count_hidden": inter["likes_count_hidden"],
            "comments_count_hidden": inter["comments_count_hidden"],
            "created_at": to_utc_iso(doc.get("created_at")),
        })
    return jsonify({"posts": posts}), 200


@app.route("/user-posts/<user_id>")
@login_required
def user_posts_page(user_id):
    return send_from_directory(app.static_folder, "user_posts.html")


@app.route("/post/<post_id>/comments")
@login_required
def post_comments_thread_page(post_id):
    """Full threaded comments page (minimal chrome, opens in new tab from feed)."""
    return send_from_directory(app.static_folder, "post_comments.html")


@app.route("/post/<post_id>")
@login_required
def post_share_view(post_id):
    """Single-post page for shared links (post only)."""
    return send_from_directory(app.static_folder, "post_view.html")


@app.route("/share-post/<post_id>", methods=["POST"])
@login_required
def api_share_post(post_id):
    """
    Share post with accepted connections.
    Body: { connection_user_ids: [user_id, ...] }
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        post_oid = ObjectId(post_id)
    except Exception:
        return jsonify({"error": "Invalid post id"}), 400
    post = db["posts"].find_one({"_id": post_oid})
    if not post:
        return jsonify({"error": "Post not found"}), 404
    data = request.get_json(silent=True) or {}
    ids = data.get("connection_user_ids") or []
    if not isinstance(ids, list):
        ids = []
    sent = 0
    sender_name = _user_display_name(user)
    base_url = request.host_url.rstrip("/")
    link = f"{base_url}/post/{str(post_oid)}"
    for raw in ids:
        try:
            target_oid = ObjectId(str(raw))
        except Exception:
            continue
        if target_oid == user["_id"]:
            continue
        conn = db["connections"].find_one({
            "$or": [
                {"requester_id": user["_id"], "recipient_id": target_oid, "status": CONNECTION_ACCEPTED},
                {"requester_id": target_oid, "recipient_id": user["_id"], "status": CONNECTION_ACCEPTED},
            ]
        })
        if not conn:
            continue
        create_notification(
            target_oid,
            f"{sender_name} shared a post with you",
            notification_type="share",
            reference_id=post_oid,
            reference_type="post",
            metadata={"sender_id": str(user["_id"]), "share_link": link},
        )
        try:
            db["shared_posts"].insert_one({
                "from_user": user["_id"],
                "to_user": target_oid,
                "post_id": post_oid,
                "timestamp": datetime.utcnow(),
            })
        except Exception:
            pass
        sent += 1
    return jsonify({"message": "Post shared", "sent": sent, "share_link": link}), 200


@app.route("/share_post", methods=["POST"])
@login_required
def api_share_post_body():
    """Same as /share-post/<post_id> but post_id in JSON body."""
    data = request.get_json(silent=True) or {}
    pid = data.get("post_id")
    if not pid:
        return jsonify({"error": "post_id is required"}), 400
    return api_share_post(str(pid))


@app.route("/like_post/<post_id>", methods=["POST"])
@login_required
def alias_like_post_toggle(post_id):
    return api_toggle_like(post_id)


@app.route("/get_comments/<post_id>", methods=["GET"])
@login_required
def alias_get_comments(post_id):
    return api_comments_by_post(post_id)


@app.route("/reply_comment/<comment_id>", methods=["POST"])
@login_required
def alias_reply_comment(comment_id):
    return api_add_reply(comment_id)


@app.route("/add_comment/<post_id>", methods=["POST"])
@login_required
def alias_add_comment_underscore(post_id):
    return api_add_comment(post_id)


@app.route("/edit_comment/<comment_id>", methods=["PUT", "POST"])
@login_required
def alias_edit_comment(comment_id):
    return api_edit_comment(comment_id)


@app.route("/delete_comment/<comment_id>", methods=["POST", "DELETE"])
@login_required
def alias_delete_comment(comment_id):
    return api_delete_comment(comment_id)


# ---------- Connection APIs ----------
@app.route("/api/connections", methods=["GET"])
@login_required
def api_connections():
    """
    Get current user's connections.
    Query params: status (pending|accepted|rejected)
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    status = (request.args.get("status") or "").upper()
    
    query = {
        "$or": [
            {"requester_id": user["_id"]},
            {"recipient_id": user["_id"]}
        ]
    }
    if status in {CONNECTION_PENDING, CONNECTION_ACCEPTED, CONNECTION_REJECTED}:
        query["status"] = status

    connections = []
    for doc in db["connections"].find(query).sort("created_at", -1):
        # Determine the other user
        other_id = doc.get("recipient_id") if doc.get("requester_id") == user["_id"] else doc.get("requester_id")
        other_user = db["users"].find_one({"_id": other_id})

        if other_user and user_hidden_from_campuslink_discovery(other_user):
            continue

        if other_user:
            other_name = f"{other_user.get('first_name', '')} {other_user.get('last_name', '')}".strip()
            other_profile = other_user.get("profile") or {}
            connections.append({
                "id": str(doc.get("_id")),
                "user_id": str(other_id),
                "name": other_name,
                "headline": other_profile.get("headline") or other_profile.get("basic", {}).get("headline"),
                "profile_photo": other_profile.get("profile_photo"),
                "status": doc.get("status"),
                "is_requester": doc.get("requester_id") == user["_id"],
                "created_at": doc.get("created_at").isoformat() if isinstance(doc.get("created_at"), datetime) else None,
            })

    return jsonify({"connections": connections}), 200


@app.route("/api/connections/request", methods=["POST"])
@login_required
def api_connection_request():
    """
    Send a connection request to another user.
    Body: { "user_id": "..." }
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json(silent=True) or {}
    target_id = data.get("user_id")
    
    if not target_id:
        return jsonify({"error": "user_id is required"}), 400

    try:
        target_oid = ObjectId(target_id)
    except Exception:
        return jsonify({"error": "Invalid user id"}), 400

    if target_oid == user["_id"]:
        return jsonify({"error": "Cannot connect with yourself"}), 400

    target_user = db["users"].find_one({"_id": target_oid})
    if not target_user:
        return jsonify({"error": "User not found"}), 404
    if user_hidden_from_campuslink_discovery(target_user):
        return jsonify({"error": "User not found"}), 404

    t_role = (target_user.get("role") or "").strip().upper()
    t_ut = (target_user.get("user_type") or "").strip().lower()
    if t_role not in (ROLE_STUDENT, ROLE_ALUMNI) and t_ut not in ("student", "alumni"):
        return jsonify({"error": "You can only connect with students or alumni."}), 400

    # Check if connection already exists
    existing = db["connections"].find_one({
        "$or": [
            {"requester_id": user["_id"], "recipient_id": target_oid},
            {"requester_id": target_oid, "recipient_id": user["_id"]}
        ]
    })
    
    if existing:
        return jsonify({
            "message": "Connection already exists",
            "status": existing.get("status")
        }), 200

    # Create connection request
    connection_result = db["connections"].insert_one({
        "requester_id": user["_id"],
        "recipient_id": target_oid,
        "status": CONNECTION_PENDING,
        "created_at": datetime.utcnow(),
    })

    # Notify the recipient
    requester_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    create_notification(
        target_oid,
        f"{requester_name} wants to connect with you.",
        notification_type="connection_request",
        reference_id=user["_id"],
        reference_type="profile",
        metadata={
            "connection_id": str(connection_result.inserted_id),
            "requester_name": requester_name,
            "action_required": True
        }
    )

    return jsonify({"message": "Connection request sent", "status": CONNECTION_PENDING}), 201


@app.route("/api/connections/<connection_id>/respond", methods=["POST"])
@login_required
def api_connection_respond(connection_id):
    """
    Accept or reject a connection request.
    Body: { "action": "accept" | "reject" }
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    try:
        conn_oid = ObjectId(connection_id)
    except Exception:
        return jsonify({"error": "Invalid connection id"}), 400

    connection = db["connections"].find_one({
        "_id": conn_oid,
        "recipient_id": user["_id"],
        "status": CONNECTION_PENDING
    })
    
    if not connection:
        return jsonify({"error": "Connection request not found"}), 404

    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").lower()
    
    if action not in {"accept", "reject"}:
        return jsonify({"error": "action must be 'accept' or 'reject'"}), 400

    new_status = CONNECTION_ACCEPTED if action == "accept" else CONNECTION_REJECTED
    
    db["connections"].update_one(
        {"_id": conn_oid},
        {"$set": {"status": new_status, "responded_at": datetime.utcnow()}}
    )

    # Notify the requester
    requester = db["users"].find_one({"_id": connection.get("requester_id")})
    if requester:
        responder_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
        if action == "accept":
            create_notification(
                requester["_id"],
                f"{responder_name} accepted your connection request.",
                notification_type="connection",
                reference_id=user["_id"],
                reference_type="profile"
            )

    return jsonify({"message": f"Connection {action}ed", "status": new_status}), 200


# ---------- Messaging APIs ----------


def _chat_conversation_folder_id(a: ObjectId, b: ObjectId) -> str:
    sa, sb = str(a), str(b)
    return f"{sa}_{sb}" if sa < sb else f"{sb}_{sa}"


def _student_department(user):
    """Return normalized department (branch_code) for a student user."""
    return normalize_branch_code(user.get("branch_code") or user.get("branch"))


@app.route("/api/messages/conversations", methods=["GET"])
@login_required
def api_conversations():
    """
    Get all conversations for the current user.
    Excludes help threads from partner list. For students, prepends one "Help" conversation.
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    # Only normal (non-help) messages for partner list
    base_match = {
        "$and": [
            {"$or": [
                {"sender_id": user["_id"]},
                {"recipient_id": user["_id"]}
            ]},
            {"$or": [
                {"thread_type": {"$exists": False}},
                {"thread_type": {"$ne": "help"}}
            ]}
        ]
    }
    pipeline = [
        {"$match": base_match},
        {"$sort": {"created_at": -1}},
        {"$group": {
            "_id": {
                "$cond": [
                    {"$eq": ["$sender_id", user["_id"]]},
                    "$recipient_id",
                    "$sender_id"
                ]
            },
            "last_message": {"$first": "$content"},
            "last_message_at": {"$first": "$created_at"},
            "unread_count": {
                "$sum": {
                    "$cond": [
                        {"$and": [
                            {"$eq": ["$recipient_id", user["_id"]]},
                            {"$eq": ["$is_read", False]}
                        ]},
                        1,
                        0
                    ]
                }
            }
        }}
    ]

    conversations = []
    for doc in db["messages"].aggregate(pipeline):
        other_user = db["users"].find_one({"_id": doc.get("_id")})
        if other_user and user_hidden_from_campuslink_discovery(other_user):
            continue
        if other_user:
            other_name = f"{other_user.get('first_name', '')} {other_user.get('last_name', '')}".strip()
            other_profile = other_user.get("profile") or {}
            conversations.append({
                "user_id": str(doc.get("_id")),
                "name": other_name,
                "headline": other_profile.get("headline") or other_profile.get("basic", {}).get("headline"),
                "profile_photo": _profile_photo_url(other_profile.get("profile_photo")),
                "last_message": doc.get("last_message"),
                "last_message_at": to_utc_iso(doc.get("last_message_at")),
                "unread_count": doc.get("unread_count", 0),
            })

    # Student: prepend Help conversation (one per department)
    ut = (user.get("user_type") or "").strip().lower()
    role = (user.get("role") or "").strip().upper()
    if ut == "student" or role == ROLE_STUDENT:
        dept = _student_department(user)
        if dept:
            help_thread = db["message_groups"].find_one({
                "type": "help",
                "student_id": user["_id"],
                "department_id": dept,
            })
            if help_thread:
                last_msg = db["messages"].find_one(
                    {"thread_id": help_thread["_id"], "thread_type": "help"},
                    sort=[("created_at", -1)]
                )
                unread_c = db["messages"].count_documents({
                    "thread_id": help_thread["_id"],
                    "thread_type": "help",
                    "sender_id": {"$ne": user["_id"]},
                    "is_read": False,
                })
                conversations.insert(0, {
                    "user_id": "help",
                    "thread_id": str(help_thread["_id"]),
                    "name": "Help",
                    "headline": None,
                    "profile_photo": None,
                    "last_message": (last_msg or {}).get("content"),
                    "last_message_at": to_utc_iso((last_msg or {}).get("created_at")),
                    "unread_count": unread_c,
                })
            else:
                conversations.insert(0, {
                    "user_id": "help",
                    "thread_id": None,
                    "name": "Help",
                    "headline": None,
                    "profile_photo": None,
                    "last_message": None,
                    "last_message_at": None,
                    "unread_count": 0,
                })

    return jsonify({"conversations": conversations}), 200


@app.route("/api/messages/help", methods=["GET", "POST"])
@login_required
def api_messages_help():
    """
    Student-only. GET: get or create help thread and return messages (other_user name is 'Help').
    POST: send message to help thread (create thread if needed).
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    ut = (user.get("user_type") or "").strip().lower()
    role = (user.get("role") or "").strip().upper()
    if ut != "student" and role != ROLE_STUDENT:
        return jsonify({"error": "Only students can use Help"}), 403

    dept = _student_department(user)
    if not dept:
        return jsonify({"error": "Department not set. Cannot use Help."}), 400

    if request.method == "GET":
        thread = db["message_groups"].find_one({
            "type": "help",
            "student_id": user["_id"],
            "department_id": dept,
        })
        if not thread:
            return jsonify({
                "messages": [],
                "other_user": {"id": "help", "name": "Help", "headline": None, "profile_photo": None},
                "thread_id": None,
            }), 200
        # Mark messages from faculty as read
        db["messages"].update_many(
            {
                "thread_id": thread["_id"],
                "thread_type": "help",
                "sender_id": {"$ne": user["_id"]},
                "is_read": False,
            },
            {"$set": {"is_read": True}}
        )
        messages = []
        for doc in db["messages"].find(
            {"thread_id": thread["_id"], "thread_type": "help"}
        ).sort("created_at", 1).limit(100):
            is_mine = doc.get("sender_id") == user["_id"]
            messages.append({
                "id": str(doc.get("_id")),
                "content": doc.get("content"),
                "sender_id": str(doc.get("sender_id")),
                "is_own": is_mine,
                "is_mine": is_mine,
                "created_at": to_utc_iso(doc.get("created_at")),
            })
        return jsonify({
            "messages": messages,
            "other_user": {"id": "help", "name": "Help", "headline": None, "profile_photo": None},
            "thread_id": str(thread["_id"]),
        }), 200

    # POST - send help message
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "Content is required"}), 400

    thread = db["message_groups"].find_one({
        "type": "help",
        "student_id": user["_id"],
        "department_id": dept,
    })
    if not thread:
        thread_doc = {
            "type": "help",
            "student_id": user["_id"],
            "department_id": dept,
            "participants": [user["_id"], dept],
            "created_at": datetime.utcnow(),
        }
        ins = db["message_groups"].insert_one(thread_doc)
        thread = {"_id": ins.inserted_id, **thread_doc}

    message_doc = {
        "sender_id": user["_id"],
        "recipient_id": None,
        "thread_id": thread["_id"],
        "thread_type": "help",
        "content": content,
        "is_read": False,
        "created_at": datetime.utcnow(),
    }
    result = db["messages"].insert_one(message_doc)
    return jsonify({"message": "Message sent", "id": str(result.inserted_id), "thread_id": str(thread["_id"])}), 201


@app.route("/api/messages/<user_id>", methods=["GET", "POST"])
@login_required
def api_messages(user_id):
    """
    GET: Get messages between current user and specified user
    POST: Send a message to specified user
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    try:
        other_oid = ObjectId(user_id)
    except Exception:
        return jsonify({"error": "Invalid user id"}), 400

    other_user = db["users"].find_one({"_id": other_oid})
    if not other_user:
        return jsonify({"error": "User not found"}), 404

    if request.method == "GET":
        # Mark messages as read
        db["messages"].update_many(
            {"sender_id": other_oid, "recipient_id": user["_id"], "is_read": False},
            {"$set": {"is_read": True}}
        )
        
        messages = []
        for doc in db["messages"].find({
            "$or": [
                {"sender_id": user["_id"], "recipient_id": other_oid},
                {"sender_id": other_oid, "recipient_id": user["_id"]}
            ]
        }).sort("created_at", 1).limit(100):
            is_mine = doc.get("sender_id") == user["_id"]
            messages.append({
                "id": str(doc.get("_id")),
                "content": doc.get("content"),
                "attachment_url": doc.get("attachment_url"),
                "sender_id": str(doc.get("sender_id")),
                "is_own": is_mine,
                "is_mine": is_mine,
                "created_at": to_utc_iso(doc.get("created_at")),
            })
        
        # Get other user info
        other_name = f"{other_user.get('first_name', '')} {other_user.get('last_name', '')}".strip()
        other_profile = other_user.get("profile") or {}
        
        return jsonify({
            "messages": messages,
            "other_user": {
                "id": str(other_user.get("_id")),
                "name": other_name,
                "headline": other_profile.get("headline") or other_profile.get("basic", {}).get("headline"),
                "profile_photo": _profile_photo_url(other_profile.get("profile_photo")),
            }
        }), 200

    # POST — JSON text only (attachments disabled)
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    attachment_url = None
    if not content:
        return jsonify({"error": "Message text is required"}), 400

    message_doc = {
        "sender_id": user["_id"],
        "recipient_id": other_oid,
        "content": content or ("Attachment" if attachment_url else ""),
        "attachment_url": attachment_url,
        "is_read": False,
        "created_at": datetime.utcnow(),
    }

    result = db["messages"].insert_one(message_doc)

    # Notify recipient
    sender_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    create_notification(
        other_oid,
        f"New message from {sender_name}",
        notification_type="message",
        reference_id=user["_id"],
        reference_type="conversation"
    )

    return jsonify({
        "message": "Message sent",
        "id": str(result.inserted_id)
    }), 201


# ---------- Profile Photo Upload ----------
@app.route("/api/student/profile/photo", methods=["POST", "DELETE"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_student_profile_photo():
    """
    POST: Upload profile photo
    DELETE: Remove profile photo
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    if request.method == "DELETE":
        profile = _profile_for_user(user)
        profile["profile_photo"] = None
        _save_profile(user, profile)
        return jsonify({"message": "Photo removed"}), 200

    image_file = request.files.get("file") or request.files.get("photo")
    if not image_file or not image_file.filename:
        return jsonify({"error": "Profile photo file is required."}), 400
    ext = _extract_file_ext(image_file.filename)
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify({"error": "Only JPG/JPEG/PNG are allowed."}), 400
    uploaded, upload_err = upload_to_cloudinary(
        image_file,
        _cloudinary_user_folder_path(user, "profile_photo"),
        resource_type="image",
        public_id_prefix="profile_photo",
    )
    if upload_err:
        return jsonify({"error": upload_err}), 400
    profile = _profile_for_user(user)
    profile["profile_photo"] = {
        "secure_url": uploaded.get("secure_url"),
        "public_id": uploaded.get("public_id"),
        "folder": uploaded.get("folder"),
    }
    completion = _save_profile(user, profile)
    return jsonify({"message": "Photo updated", "profile_photo": profile["profile_photo"], "profile_completion": completion}), 200


@app.route("/api/student/profile/cover-photo", methods=["POST", "DELETE"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_student_profile_cover_photo():
    """
    Optional cover photo upload/delete.
    Stored under campus/users/{user_id}/cover_photo/.
    """
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    profile = _profile_for_user(user)
    if request.method == "DELETE":
        profile["cover_photo"] = None
        _save_profile(user, profile)
        return jsonify({"message": "Cover photo removed"}), 200

    image_file = request.files.get("file") or request.files.get("cover_photo")
    if not image_file or not image_file.filename:
        return jsonify({"error": "Cover photo file is required."}), 400
    ext = _extract_file_ext(image_file.filename)
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify({"error": "Only JPG/JPEG/PNG are allowed."}), 400
    uploaded, upload_err = upload_to_cloudinary(
        image_file,
        _cloudinary_user_folder_path(user, "cover_photo"),
        resource_type="image",
        public_id_prefix="cover_photo",
    )
    if upload_err:
        return jsonify({"error": upload_err}), 400
    profile["cover_photo"] = {
        "secure_url": uploaded.get("secure_url"),
        "public_id": uploaded.get("public_id"),
        "folder": uploaded.get("folder"),
    }
    completion = _save_profile(user, profile)
    return jsonify({"message": "Cover photo updated", "cover_photo": profile["cover_photo"], "profile_completion": completion}), 200


# ---------- About Section API ----------
@app.route("/api/student/profile/about", methods=["PUT"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_student_profile_about():
    """Update the About section of profile."""
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json(silent=True) or {}
    about = (data.get("about") or "").strip()

    profile = _profile_for_user(user)
    profile["about"] = about
    
    completion = _save_profile(user, profile)
    return jsonify({"message": "About updated", "profile_completion": completion}), 200


# ---------- Certifications API ----------
def _upload_profile_highlight_image(file_storage, user: dict, public_id_prefix: str) -> tuple[str | None, str | None]:
    """Upload a single proof image; returns (secure_url, error_message)."""
    if not file_storage or not file_storage.filename:
        return None, None
    ext = _extract_file_ext(file_storage.filename)
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return None, "Only JPG/JPEG/PNG are allowed."
    try:
        file_storage.stream.seek(0, os.SEEK_END)
        size = file_storage.stream.tell()
        file_storage.stream.seek(0)
    except Exception:
        size = None
    if size and size > MAX_IMAGE_SIZE:
        return None, "File exceeds allowed size."
    uploaded, upload_err = upload_to_cloudinary(
        file_storage,
        _cloudinary_user_folder_path(user, "certificates"),
        resource_type="image",
        public_id_prefix=public_id_prefix,
    )
    if upload_err:
        return None, upload_err
    return uploaded.get("secure_url"), None


def _parse_certification_item_from_request(user: dict) -> tuple[dict, str | None]:
    """JSON body or multipart/form-data (fields + optional certificate_photo)."""
    if request.content_type and "multipart/form-data" in request.content_type:
        f = request.form
        item: dict = {
            "name": (f.get("name") or "").strip(),
            "issuer": (f.get("issuer") or "").strip(),
            "description": (f.get("description") or "").strip(),
            "credential_url": (f.get("credential_url") or "").strip(),
            "issue_month": (f.get("issue_month") or "").strip() or None,
            "issue_year": (f.get("issue_year") or "").strip() or None,
            "issue_date": (f.get("issue_date") or "").strip() or None,
            "expiry_month": (f.get("expiry_month") or "").strip() or None,
            "expiry_year": (f.get("expiry_year") or "").strip() or None,
            "expiry_date": (f.get("expiry_date") or "").strip() or None,
        }
        photo = request.files.get("certificate_photo") or request.files.get("photo")
        if photo and photo.filename:
            url, err = _upload_profile_highlight_image(photo, user, "certificate_photo")
            if err:
                return {}, err
            if url:
                item["media_url"] = url
        return item, None
    data = request.get_json(silent=True) or {}
    return (data.get("item") or {}), None


@app.route("/api/student/profile/certifications", methods=["POST"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_student_profile_certifications_post():
    user = get_logged_in_user()
    profile = _profile_for_user(user)
    raw_item, parse_err = _parse_certification_item_from_request(user)
    if parse_err:
        return jsonify({"error": parse_err}), 400
    if not isinstance(raw_item, dict):
        raw_item = {}
    item = _normalize_certification_item(raw_item)
    item = _add_item(profile, "certifications", item)
    feed_post_created, feed_post_message = _maybe_create_profile_highlight_post(
        user, "certification", item, "certifications"
    )
    completion = _save_profile(user, profile)
    return jsonify(
        {
            "item": item,
            "profile_completion": completion,
            "feed_post_created": feed_post_created,
            "feed_post_message": feed_post_message,
        }
    ), 201


@app.route("/api/student/profile/certifications/<item_id>", methods=["PUT", "DELETE"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_student_profile_certifications_item(item_id):
    user = get_logged_in_user()
    profile = _profile_for_user(user)
    if request.method == "PUT":
        raw_item, parse_err = _parse_certification_item_from_request(user)
        if parse_err:
            return jsonify({"error": parse_err}), 400
        raw_item = raw_item or {}
        if not isinstance(raw_item, dict):
            raw_item = {}
        updated = _update_item(profile, "certifications", item_id, _normalize_certification_item(raw_item))
        if not updated:
            return jsonify({"error": "Certification not found"}), 404
        feed_post_created, feed_post_message = _maybe_create_profile_highlight_post(
            user, "certification", updated, "certifications"
        )
        completion = _save_profile(user, profile)
        return jsonify(
            {
                "item": updated,
                "profile_completion": completion,
                "feed_post_created": feed_post_created,
                "feed_post_message": feed_post_message,
            }
        ), 200

    deleted = _delete_item(profile, "certifications", item_id)
    if not deleted:
        return jsonify({"error": "Certification not found"}), 404
    completion = _save_profile(user, profile)
    return jsonify({"message": "Deleted", "profile_completion": completion}), 200


# ---------- Achievements API ----------
def _parse_achievement_item_from_request(user: dict) -> tuple[dict, str | None]:
    if request.content_type and "multipart/form-data" in request.content_type:
        f = request.form
        issue_date = (f.get("issue_date") or f.get("date") or "").strip() or None
        item: dict = {
            "title": (f.get("title") or "").strip(),
            "associated_with": (f.get("associated_with") or f.get("issuer") or "").strip(),
            "issuer": (f.get("issuer") or f.get("associated_with") or "").strip(),
            "description": (f.get("description") or "").strip(),
            "issue_month": (f.get("issue_month") or "").strip() or None,
            "issue_year": (f.get("issue_year") or "").strip() or None,
            "issue_date": issue_date,
            "date": issue_date,
        }
        photo = request.files.get("photo") or request.files.get("achievement_photo")
        if photo and photo.filename:
            url, err = _upload_profile_highlight_image(photo, user, "achievement_photo")
            if err:
                return {}, err
            if url:
                item["media_url"] = url
        return item, None
    data = request.get_json(silent=True) or {}
    return (data.get("item") or {}), None


@app.route("/api/student/profile/achievements", methods=["POST"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_student_profile_achievements_post():
    user = get_logged_in_user()
    profile = _profile_for_user(user)
    raw_item, parse_err = _parse_achievement_item_from_request(user)
    if parse_err:
        return jsonify({"error": parse_err}), 400
    if not isinstance(raw_item, dict):
        raw_item = {}
    item = _normalize_achievement_item(raw_item)
    item = _add_item(profile, "achievements", item)
    feed_post_created, feed_post_message = _maybe_create_profile_highlight_post(
        user, "achievement", item, "achievements"
    )
    completion = _save_profile(user, profile)
    return jsonify(
        {
            "item": item,
            "profile_completion": completion,
            "feed_post_created": feed_post_created,
            "feed_post_message": feed_post_message,
        }
    ), 201


@app.route("/api/student/profile/achievements/<item_id>", methods=["PUT", "DELETE"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_student_profile_achievements_item(item_id):
    user = get_logged_in_user()
    profile = _profile_for_user(user)
    if request.method == "PUT":
        raw_item, parse_err = _parse_achievement_item_from_request(user)
        if parse_err:
            return jsonify({"error": parse_err}), 400
        raw_item = raw_item or {}
        if not isinstance(raw_item, dict):
            raw_item = {}
        updated = _update_item(profile, "achievements", item_id, _normalize_achievement_item(raw_item))
        if not updated:
            return jsonify({"error": "Achievement not found"}), 404
        feed_post_created, feed_post_message = _maybe_create_profile_highlight_post(
            user, "achievement", updated, "achievements"
        )
        completion = _save_profile(user, profile)
        return jsonify(
            {
                "item": updated,
                "profile_completion": completion,
                "feed_post_created": feed_post_created,
                "feed_post_message": feed_post_message,
            }
        ), 200

    deleted = _delete_item(profile, "achievements", item_id)
    if not deleted:
        return jsonify({"error": "Achievement not found"}), 404
    completion = _save_profile(user, profile)
    return jsonify({"message": "Deleted", "profile_completion": completion}), 200


@app.route("/api/student/profile/skills-media", methods=["POST"])
@login_required
@role_required("STUDENT", "ALUMNI")
def api_student_profile_skills_media():
    """Upload proof media for skills (screenshots, certs); stored under campus/users/{user_id}/skills_media/."""
    user = get_logged_in_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    media_file = request.files.get("file") or request.files.get("media")
    if not media_file or not media_file.filename:
        return jsonify({"error": "Media file is required."}), 400
    ext = _extract_file_ext(media_file.filename)
    if ext in ALLOWED_IMAGE_EXTENSIONS:
        resource_type = "image"
        max_size = MAX_IMAGE_SIZE
        media_type = "image"
    elif ext == "pdf":
        resource_type = "raw"
        max_size = MAX_DOC_SIZE
        media_type = "document"
    else:
        return jsonify({"error": "Only JPG/JPEG/PNG/PDF are allowed."}), 400
    try:
        media_file.stream.seek(0, os.SEEK_END)
        size = media_file.stream.tell()
        media_file.stream.seek(0)
    except Exception:
        size = None
    if size and size > max_size:
        return jsonify({"error": "File exceeds allowed size."}), 400
    uploaded, upload_err = upload_to_cloudinary(
        media_file,
        _cloudinary_user_folder_path(user, "certificates"),
        resource_type=resource_type,
        public_id_prefix="skill_proof",
    )
    if upload_err:
        return jsonify({"error": upload_err}), 400
    return jsonify(
        {
            "url": uploaded.get("secure_url"),
            "media": {
                "type": media_type,
                "url": uploaded.get("secure_url"),
                "public_id": uploaded.get("public_id"),
                "folder": uploaded.get("folder"),
            },
        }
    ), 201


# ---------- Languages API ----------
@app.route("/api/student/profile/languages", methods=["PUT"])
@login_required
@role_required("STUDENT")
def api_student_profile_languages():
    user = get_logged_in_user()
    profile = _profile_for_user(user)
    data = request.get_json(silent=True) or {}
    languages = data.get("languages") or []
    profile["languages"] = _normalize_languages_payload(languages)
    completion = _save_profile(user, profile)
    return jsonify({"message": "Languages updated", "profile_completion": completion}), 200


#
# Interests removed from backend (no API endpoint).
# Existing saved data in MongoDB may remain, but edit/profile endpoints no longer accept/update it.
#


# ---------- Current Status API ----------
@app.route("/api/student/profile/status", methods=["PUT"])
@login_required
@role_required("STUDENT")
def api_student_profile_status():
    """Update current status (Intern/Placed/Looking for opportunities)."""
    user = get_logged_in_user()
    profile = _profile_for_user(user)
    data = request.get_json(silent=True) or {}
    status_raw = data.get("status")
    status = _canonical_status(status_raw)
    if status is None and (status_raw is not None and str(status_raw).strip()):
        return jsonify({"error": f"Status must be one of: {', '.join(_STATUS_OPTIONS)}"}), 400
    # Default to looking-for-opportunities if missing/invalid (but don't raise if empty).
    profile["current_status"] = status or "Looking for opportunities"
    completion = _save_profile(user, profile)
    return jsonify({"message": "Status updated", "profile_completion": completion}), 200

def upload_file(file, folder_name):
    return upload_to_cloudinary(file, folder_name)


@app.route("/upload-test", methods=["GET", "POST"])
def upload_test():
    if request.method == "POST":
        return "Upload testing is disabled."

    return '''
        <h2>Upload Test Disabled</h2>
    '''

if __name__ == "__main__":
    app.run(debug=True)






