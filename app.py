import io
import os
import re
import random
import string
from datetime import date, datetime, timedelta
from functools import wraps

from dotenv import load_dotenv

load_dotenv()

from flask import (
    Flask,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_mail import Mail, Message
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text, and_
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, GradientFill, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.drawing.image import Image as XlImage
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "cambia_esta_clave_en_produccion")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL",
    "sqlite:///horarios.db",
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Configuración de Flask-Mail
app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "smtp.example.com")
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"] = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME", "")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD", "")
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_DEFAULT_SENDER", "noreply@example.com")

MAX_WEEKLY_HOURS = 40.0
TOKEN_TTL_SECONDS = 60 * 60 * 12

db = SQLAlchemy(app)
mail = Mail(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    rol = db.Column(db.String(20), nullable=False, default="employee")
    first_name = db.Column(db.String(120), nullable=False, default="")
    last_name = db.Column(db.String(120), nullable=False, default="")
    tax_id = db.Column(db.String(40), nullable=False, default="")
    affiliation_number = db.Column(db.String(32), nullable=False, default="")
    email = db.Column(db.String(150), nullable=False, default="")
    phone = db.Column(db.String(20), nullable=False, default="")
    employment_type = db.Column(db.String(30), nullable=False, default="Interno")
    address = db.Column(db.String(200), nullable=False, default="")
    postal_code = db.Column(db.String(10), nullable=False, default="")
    city = db.Column(db.String(100), nullable=False, default="")
    province = db.Column(db.String(100), nullable=False, default="")
    country = db.Column(db.String(100), nullable=False, default="")
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def is_active(self):
        return self.active

    @property
    def is_admin(self):
        return self.rol == "admin"


class TimeEntry(db.Model):
    __tablename__ = "time_entries"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    work_date = db.Column(db.Date, nullable=False)
    check_in = db.Column(db.Time, nullable=False)
    meal_start = db.Column(db.Time, nullable=True)
    meal_end = db.Column(db.Time, nullable=True)
    pause_start = db.Column(db.Time, nullable=True)
    pause_end = db.Column(db.Time, nullable=True)
    overtime_start = db.Column(db.Time, nullable=True)
    overtime_end = db.Column(db.Time, nullable=True)
    check_out = db.Column(db.Time, nullable=False)
    comments = db.Column(db.Text, nullable=True)
    location_latitude = db.Column(db.Float, nullable=True)
    location_longitude = db.Column(db.Float, nullable=True)
    overtime_validated = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship("User", backref="entries")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    target_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    time_entry_id = db.Column(db.Integer, db.ForeignKey("time_entries.id"), nullable=True)
    entity_type = db.Column(db.String(30), nullable=False)
    entity_id = db.Column(db.Integer, nullable=True)
    action = db.Column(db.String(30), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    details = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    actor_user = db.relationship("User", foreign_keys=[actor_user_id])
    target_user = db.relationship("User", foreign_keys=[target_user_id])
    time_entry = db.relationship("TimeEntry", foreign_keys=[time_entry_id])


class CompanyProfile(db.Model):
    __tablename__ = "company_profile"

    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(150), nullable=False, default="")
    tax_id = db.Column(db.String(40), nullable=False, default="")
    fiscal_address = db.Column(db.String(255), nullable=False, default="")
    postal_code = db.Column(db.String(20), nullable=False, default="")
    city = db.Column(db.String(120), nullable=False, default="")
    province = db.Column(db.String(120), nullable=False, default="")
    country = db.Column(db.String(120), nullable=False, default="Espana")
    phone = db.Column(db.String(40), nullable=False, default="")
    referral_source = db.Column(db.String(120), nullable=False, default="")
    data_policy_accepted = db.Column(db.Boolean, nullable=False, default=False)
    processing_manager_accepted = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# Modelo para códigos de recuperación de contraseña
class PasswordResetCode(db.Model):
    __tablename__ = "password_reset_codes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    code = db.Column(db.String(12), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, nullable=False, default=False)

    user = db.relationship("User", backref="reset_codes")


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def parse_iso_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def parse_hhmm(value):
    return datetime.strptime(value, "%H:%M").time()


def parse_coordinate(value):
    if value in (None, ""):
        return None
    return round(float(value), 7)


def combine_dt(day_value, time_value):
    return datetime.combine(day_value, time_value)


def meal_hours(entry):
    if entry.meal_start and entry.meal_end:
        delta = combine_dt(entry.work_date, entry.meal_end) - combine_dt(entry.work_date, entry.meal_start)
        return max(0.0, delta.total_seconds() / 3600)
    return 0.0


def pause_hours(entry):
    if getattr(entry, "pause_start", None) and getattr(entry, "pause_end", None):
        delta = combine_dt(entry.work_date, entry.pause_end) - combine_dt(entry.work_date, entry.pause_start)
        return max(0.0, round(delta.total_seconds() / 3600, 2))
    return 0.0


def worked_hours(entry):
    total = combine_dt(entry.work_date, entry.check_out) - combine_dt(entry.work_date, entry.check_in)
    worked = total.total_seconds() / 3600 - meal_hours(entry) - pause_hours(entry)
    return max(0.0, round(worked, 2))


def overtime_hours(entry):
    if getattr(entry, "overtime_start", None) and getattr(entry, "overtime_end", None):
        delta = combine_dt(entry.work_date, entry.overtime_end) - combine_dt(entry.work_date, entry.overtime_start)
        return max(0.0, round(delta.total_seconds() / 3600, 2))
    return 0.0


def week_bounds(day_value):
    week_start = day_value - timedelta(days=day_value.weekday())
    return week_start, week_start + timedelta(days=6)


def weekly_hours_for_user(user_id, day_value):
    start, end = week_bounds(day_value)
    entries = TimeEntry.query.filter(
        TimeEntry.user_id == user_id,
        TimeEntry.work_date >= start,
        TimeEntry.work_date <= end,
    ).all()
    return round(sum(worked_hours(item) for item in entries), 2)


def weekly_breakdown_for_user(user_id, day_value):
    start, end = week_bounds(day_value)
    entries = TimeEntry.query.filter(
        TimeEntry.user_id == user_id,
        TimeEntry.work_date >= start,
        TimeEntry.work_date <= end,
    ).all()

    effective_hours = round(sum(worked_hours(item) for item in entries), 2)
    meal_total = round(sum(meal_hours(item) for item in entries), 2)
    pause_total = round(sum(pause_hours(item) for item in entries), 2)
    overtime_total = round(sum(overtime_hours(item) for item in entries), 2)
    over_limit_hours = round(max(0.0, effective_hours - MAX_WEEKLY_HOURS), 2)

    return {
        "week_start": start,
        "week_end": end,
        "effective_hours": effective_hours,
        "meal_hours": meal_total,
        "pause_hours": pause_total,
        "overtime_hours": overtime_total,
        "over_limit_hours": over_limit_hours,
    }


def validate_password_strength(password):
    if len(password) < 10:
        return "La contraseña debe tener al menos 10 caracteres"
    if not re.search(r"[A-Z]", password):
        return "La contraseña debe incluir una letra mayúscula"
    if not re.search(r"[a-z]", password):
        return "La contraseña debe incluir una letra minúscula"
    if not re.search(r"\d", password):
        return "La contraseña debe incluir un número"
    if not re.search(r"[^A-Za-z0-9]", password):
        return "La contraseña debe incluir un carácter especial"
    return None


def create_audit_log(actor_user_id, entity_type, action, reason, details, target_user_id=None, time_entry_id=None, entity_id=None):
    log = AuditLog(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        time_entry_id=time_entry_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        reason=reason.strip(),
        details=details,
    )
    db.session.add(log)
    return log


def can_edit_entry(user, entry):
    if user.is_admin:
        return True
    if entry.overtime_validated:
        return False
    return entry.user_id == user.id and entry.work_date == date.today()


def change_reason_required(reason):
    reason = (reason or "").strip()
    if not reason:
        return "Debes indicar el motivo del cambio"
    return None


def latest_audit_logs(limit=30):
    return AuditLog.query.order_by(AuditLog.created_at.desc()).limit(limit).all()


def request_user():
    if hasattr(request, "api_user"):
        return request.api_user
    return current_user


def monthly_entries(month, selected_user_id):
    month_start = datetime.strptime(month + "-01", "%Y-%m-%d").date()
    month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    entries = (
        TimeEntry.query.filter(
            TimeEntry.user_id == selected_user_id,
            TimeEntry.work_date >= month_start,
            TimeEntry.work_date < month_end,
        )
        .order_by(TimeEntry.work_date.asc())
        .all()
    )
    return month_start, month_end, entries


def report_employee_users():
    return (
        User.query.filter(User.rol != "admin")
        .order_by(User.first_name.asc(), User.last_name.asc(), User.username.asc())
        .all()
    )


def report_context(month):
    active_user = request_user()
    selected_user_id = active_user.id
    include_all = False

    if active_user.is_admin:
        available_users = report_employee_users()
        available_user_ids = {user.id for user in available_users}
        requested_user = (request.args.get("user_id") or "all").strip().lower()
        include_all = requested_user in {"", "all"}
        if not include_all:
            try:
                requested_user_id = int(requested_user)
            except ValueError:
                include_all = True
            else:
                if requested_user_id in available_user_ids:
                    selected_user_id = requested_user_id
                else:
                    include_all = True

    if include_all:
        month_start = datetime.strptime(month + "-01", "%Y-%m-%d").date()
        month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        entries = (
            TimeEntry.query.join(TimeEntry.user)
            .filter(
                TimeEntry.work_date >= month_start,
                TimeEntry.work_date < month_end,
                User.rol != "admin",
            )
            .order_by(TimeEntry.work_date.asc(), User.username.asc())
            .all()
        )
    else:
        _, _, entries = monthly_entries(month, selected_user_id)

    change_reasons = latest_change_reasons_for_entries(entries)
    selected_user = None if include_all else db.session.get(User, selected_user_id)

    return active_user, selected_user_id, selected_user, entries, change_reasons, include_all


def latest_change_reasons_for_entries(entries):
    entry_ids = [item.id for item in entries]
    if not entry_ids:
        return {}

    logs = (
        AuditLog.query.filter(
            AuditLog.time_entry_id.in_(entry_ids),
            AuditLog.action == "update",
        )
        .order_by(AuditLog.time_entry_id.asc(), AuditLog.created_at.asc(), AuditLog.id.asc())
        .all()
    )

    reasons_by_entry = {entry_id: [] for entry_id in entry_ids}
    for log in logs:
        reason_text = (log.reason or "").strip()
        change_time = log.created_at.strftime("%H:%M") if log.created_at else "--:--"
        if reason_text:
            reasons_by_entry.setdefault(log.time_entry_id, []).append(f"{change_time} (h) - {reason_text}")
        else:
            reasons_by_entry.setdefault(log.time_entry_id, []).append(f"{change_time} (h)")

    return {
        entry_id: "\n".join(lines) if lines else ""
        for entry_id, lines in reasons_by_entry.items()
    }


def serialize_entry(entry):
    return {
        "id": entry.id,
        "user_id": entry.user_id,
        "username": entry.user.username if entry.user else None,
        "work_date": entry.work_date.isoformat(),
        "check_in": entry.check_in.strftime("%H:%M"),
        "meal_start": entry.meal_start.strftime("%H:%M") if entry.meal_start else None,
        "meal_end": entry.meal_end.strftime("%H:%M") if entry.meal_end else None,
        "pause_start": entry.pause_start.strftime("%H:%M") if entry.pause_start else None,
        "pause_end": entry.pause_end.strftime("%H:%M") if entry.pause_end else None,
        "overtime_start": entry.overtime_start.strftime("%H:%M") if entry.overtime_start else None,
        "overtime_end": entry.overtime_end.strftime("%H:%M") if entry.overtime_end else None,
        "check_out": entry.check_out.strftime("%H:%M"),
        "comments": entry.comments or "",
        "meal_hours": meal_hours(entry),
        "pause_hours": pause_hours(entry),
        "worked_hours": worked_hours(entry),
        "overtime_hours": overtime_hours(entry),
        "location_latitude": entry.location_latitude,
        "location_longitude": entry.location_longitude,
        "overtime_validated": entry.overtime_validated,
        "editable": can_edit_entry(request_user(), entry) if (hasattr(request, "api_user") or current_user.is_authenticated) else False,
    }


def validate_entry_payload(payload):
    required = ["work_date", "check_in", "check_out"]
    missing = [field for field in required if not payload.get(field)]
    if missing:
        return f"Faltan campos obligatorios: {', '.join(missing)}", None

    try:
        work_date = parse_iso_date(payload["work_date"])
        check_in = parse_hhmm(payload["check_in"])
        check_out = parse_hhmm(payload["check_out"])
        meal_start = parse_hhmm(payload["meal_start"]) if payload.get("meal_start") else None
        meal_end = parse_hhmm(payload["meal_end"]) if payload.get("meal_end") else None
        pause_start = parse_hhmm(payload["pause_start"]) if payload.get("pause_start") else None
        pause_end = parse_hhmm(payload["pause_end"]) if payload.get("pause_end") else None
        overtime_start = parse_hhmm(payload["overtime_start"]) if payload.get("overtime_start") else None
        overtime_end = parse_hhmm(payload["overtime_end"]) if payload.get("overtime_end") else None
        location_latitude = parse_coordinate(payload.get("location_latitude"))
        location_longitude = parse_coordinate(payload.get("location_longitude"))
    except ValueError:
        return "Formato de fecha u hora invalido", None

    if bool(location_latitude is not None) != bool(location_longitude is not None):
        return "Debes informar latitud y longitud para guardar la geolocalización", None

    if location_latitude is not None and not -90 <= location_latitude <= 90:
        return "La latitud de geolocalización está fuera de rango", None

    if location_longitude is not None and not -180 <= location_longitude <= 180:
        return "La longitud de geolocalización está fuera de rango", None

    if combine_dt(work_date, check_out) <= combine_dt(work_date, check_in):
        return "La hora de salida debe ser mayor que la de entrada", None

    if bool(meal_start) != bool(meal_end):
        return "Debes informar inicio y fin de comida", None

    if meal_start and meal_end:
        if combine_dt(work_date, meal_end) <= combine_dt(work_date, meal_start):
            return "El fin de comida debe ser mayor que el inicio de comida", None
        if combine_dt(work_date, meal_start) < combine_dt(work_date, check_in) or combine_dt(work_date, meal_end) > combine_dt(work_date, check_out):
            return "La comida debe estar dentro de la jornada", None

    if bool(pause_start) != bool(pause_end):
        return "Debes informar inicio y fin de pausa", None

    if pause_start and pause_end:
        if combine_dt(work_date, pause_end) <= combine_dt(work_date, pause_start):
            return "El fin de pausa debe ser mayor que el inicio de pausa", None
        if combine_dt(work_date, pause_start) < combine_dt(work_date, check_in) or combine_dt(work_date, pause_end) > combine_dt(work_date, check_out):
            return "La pausa debe estar dentro de la jornada", None

    if bool(overtime_start) != bool(overtime_end):
        return "Debes informar inicio y fin de horas extra", None

    if overtime_start and overtime_end:
        overtime_start_dt = combine_dt(work_date, overtime_start)
        overtime_end_dt = combine_dt(work_date, overtime_end)
        check_out_dt = combine_dt(work_date, check_out)

        if combine_dt(work_date, overtime_end) <= combine_dt(work_date, overtime_start):
            return "El fin de horas extra debe ser mayor que el inicio de horas extra", None

        if overtime_start_dt < check_out_dt:
            return "Las horas extra deben empezar despues de la salida de la jornada", None

    intervals = [
        ("comida", meal_start, meal_end),
        ("pausa", pause_start, pause_end),
        ("horas extra", overtime_start, overtime_end),
    ]
    active_intervals = [(label, start, end) for label, start, end in intervals if start and end]
    for index, (left_label, left_start, left_end) in enumerate(active_intervals):
        for right_label, right_start, right_end in active_intervals[index + 1:]:
            if combine_dt(work_date, left_start) < combine_dt(work_date, right_end) and combine_dt(work_date, right_start) < combine_dt(work_date, left_end):
                return f"{left_label.capitalize()} y {right_label} no pueden solaparse", None

    return None, {
        "work_date": work_date,
        "check_in": check_in,
        "meal_start": meal_start,
        "meal_end": meal_end,
        "pause_start": pause_start,
        "pause_end": pause_end,
        "overtime_start": overtime_start,
        "overtime_end": overtime_end,
        "check_out": check_out,
        "comments": (payload.get("comments") or "").strip(),
        "location_latitude": location_latitude,
        "location_longitude": location_longitude,
    }


def create_api_token(user):
    return serializer.dumps({"user_id": user.id, "rol": user.rol, "role": user.rol})


def resolve_api_user():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None

    token = auth.split(" ", 1)[1].strip()
    if not token:
        return None

    try:
        data = serializer.loads(token, max_age=TOKEN_TTL_SECONDS)
    except (BadSignature, SignatureExpired):
        return None

    user_id = data.get("user_id")
    if not user_id:
        return None

    user = db.session.get(User, int(user_id))
    if not user or not user.active:
        return None

    return user


def api_auth_required(admin_only=False):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            api_user = resolve_api_user()
            if not api_user:
                return jsonify({"error": "No autorizado"}), 401
            if admin_only and not api_user.is_admin:
                return jsonify({"error": "Permisos insuficientes"}), 403
            request.api_user = api_user
            return func(*args, **kwargs)

        return wrapper

    return decorator


def ensure_users_password_column_compatibility():
    inspector = inspect(db.engine)
    table_names = set(inspector.get_table_names())
    if "users" not in table_names:
        return

    columns = {item["name"] for item in inspector.get_columns("users")}
    if "password_hash" not in columns and "password" in columns:
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE users RENAME COLUMN password TO password_hash"))

    inspector = inspect(db.engine)
    columns = {item["name"] for item in inspector.get_columns("users")}
    if "rol" not in columns and "role" in columns:
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE users RENAME COLUMN role TO rol"))


def ensure_users_profile_columns():
    inspector = inspect(db.engine)
    table_names = set(inspector.get_table_names())
    if "users" not in table_names:
        return

    columns = {item["name"] for item in inspector.get_columns("users")}
    missing_columns = []
    if "first_name" not in columns:
        missing_columns.append("ALTER TABLE users ADD COLUMN first_name VARCHAR(120) NOT NULL DEFAULT ''")
    if "last_name" not in columns:
        missing_columns.append("ALTER TABLE users ADD COLUMN last_name VARCHAR(120) NOT NULL DEFAULT ''")
    if "tax_id" not in columns:
        missing_columns.append("ALTER TABLE users ADD COLUMN tax_id VARCHAR(40) NOT NULL DEFAULT ''")
    if "affiliation_number" not in columns:
        missing_columns.append("ALTER TABLE users ADD COLUMN affiliation_number VARCHAR(32) NOT NULL DEFAULT ''")
    if "email" not in columns:
        missing_columns.append("ALTER TABLE users ADD COLUMN email VARCHAR(150) NOT NULL DEFAULT ''")
    if "phone" not in columns:
        missing_columns.append("ALTER TABLE users ADD COLUMN phone VARCHAR(20) NOT NULL DEFAULT ''")
    if "employment_type" not in columns:
        missing_columns.append("ALTER TABLE users ADD COLUMN employment_type VARCHAR(30) NOT NULL DEFAULT ''")
    if "address" not in columns:
        missing_columns.append("ALTER TABLE users ADD COLUMN address VARCHAR(200) NOT NULL DEFAULT ''")
    if "postal_code" not in columns:
        missing_columns.append("ALTER TABLE users ADD COLUMN postal_code VARCHAR(10) NOT NULL DEFAULT ''")
    if "city" not in columns:
        missing_columns.append("ALTER TABLE users ADD COLUMN city VARCHAR(100) NOT NULL DEFAULT ''")
    if "province" not in columns:
        missing_columns.append("ALTER TABLE users ADD COLUMN province VARCHAR(100) NOT NULL DEFAULT ''")
    if "country" not in columns:
        missing_columns.append("ALTER TABLE users ADD COLUMN country VARCHAR(100) NOT NULL DEFAULT ''")

    if missing_columns:
        with db.engine.begin() as conn:
            for statement in missing_columns:
                conn.execute(text(statement))


def ensure_time_entries_geolocation_columns():
    inspector = inspect(db.engine)
    table_names = set(inspector.get_table_names())
    if "time_entries" not in table_names:
        return

    columns = {item["name"] for item in inspector.get_columns("time_entries")}
    statements = []
    if "location_latitude" not in columns:
        statements.append("ALTER TABLE time_entries ADD COLUMN location_latitude FLOAT")
    if "location_longitude" not in columns:
        statements.append("ALTER TABLE time_entries ADD COLUMN location_longitude FLOAT")
    if "pause_start" not in columns:
        statements.append("ALTER TABLE time_entries ADD COLUMN pause_start TIME")
    if "pause_end" not in columns:
        statements.append("ALTER TABLE time_entries ADD COLUMN pause_end TIME")
    if "overtime_start" not in columns:
        statements.append("ALTER TABLE time_entries ADD COLUMN overtime_start TIME")
    if "overtime_end" not in columns:
        statements.append("ALTER TABLE time_entries ADD COLUMN overtime_end TIME")

    if statements:
        with db.engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))


def ensure_default_admin():
    admin = User.query.filter_by(username="admin").first()
    if admin is None:
        admin = User(
            username="admin",
            password_hash=generate_password_hash(os.getenv("DEFAULT_ADMIN_PASSWORD", "Admin123!")),
            rol="admin",
            active=True,
        )
        db.session.add(admin)
        db.session.commit()


def get_company_profile():
    profile = CompanyProfile.query.order_by(CompanyProfile.id.asc()).first()
    if profile is None:
        profile = CompanyProfile()
        db.session.add(profile)
        db.session.commit()
    return profile


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET" and current_user.is_authenticated:
        # Fuerza mostrar siempre login al entrar en la web, incluso si el navegador restaura sesión.
        logout_user()

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        if user and user.active and check_password_hash(user.password_hash, password):
            if user.is_admin:
                flash("Este inicio de sesión es solo para empleados", "login")
                return render_template("login.html", mode="login")
            login_user(user)
            return redirect(url_for("calendar"))

        flash("Credenciales inválidas o usuario inactivo", "login")

    return render_template("login.html", mode="login")


@app.route("/register", methods=["POST"])
def register():
    if not current_user.is_authenticated:
        flash("Solo un administrador puede registrar usuarios", "login")
        return redirect(url_for("login"))

    if not current_user.is_admin:
        flash("Solo un administrador puede registrar usuarios", "login")
        return redirect(url_for("calendar"))

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    confirm = request.form.get("confirm_password", "")

    if not username or not password:
        flash("Usuario y contraseña son obligatorios", "register")
    elif len(password) < 8:
        flash("La contraseña debe tener al menos 8 caracteres", "register")
    elif password != confirm:
        flash("Las contraseñas no coinciden", "register")
    elif User.query.filter_by(username=username).first():
        flash("Ese nombre de usuario ya está en uso", "register")
    else:
        new_user = User(
            username=username,
            password_hash=generate_password_hash(password),
            rol="employee",
            active=True,
        )
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for("admin_users"))

    return redirect(url_for("admin_users"))


@app.route("/forgot-password", methods=["POST"])
def forgot_password():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("calendar"))

    username = request.form.get("username", "").strip()
    new_password = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    if not username or not new_password or not confirm:
        flash("Completa usuario y las dos contraseñas", "forgot")
        return render_template("login.html", mode="forgot")

    if new_password != confirm:
        flash("Las contraseñas no coinciden", "forgot")
        return render_template("login.html", mode="forgot")

    password_error = validate_password_strength(new_password)
    if password_error:
        flash(password_error, "forgot")
        return render_template("login.html", mode="forgot")

    user = User.query.filter_by(username=username).first()
    if not user or not user.active:
        flash("Usuario no encontrado o inactivo", "forgot")
        return render_template("login.html", mode="forgot")
    if user.is_admin:
        flash("La recuperación desde esta pantalla aplica solo a empleados", "forgot")
        return render_template("login.html", mode="forgot")

    user.password_hash = generate_password_hash(new_password)
    create_audit_log(
        actor_user_id=user.id,
        target_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        action="password_reset",
        reason="Recuperación de contraseña desde inicio de sesión",
        details="Cambio de contraseña sin sesión activa",
    )
    db.session.commit()
    flash("Contraseña actualizada. Ya puedes iniciar sesión", "login")
    return render_template("login.html", mode="login")


@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    if request.method == "GET" and current_user.is_authenticated:
        # Evita entrar directamente al panel admin al reabrir navegador con sesión restaurada.
        logout_user()

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        if user and user.active and not user.is_admin and check_password_hash(user.password_hash, password):
            flash("Acceso Denegado", "login")
            return redirect(url_for("login"))

        if user and user.active and user.is_admin and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("admin_dashboard"))

        flash("Credenciales de administrador inválidas", "admin_login")
        return render_template("admin_login.html", mode="login")

    return render_template("admin_login.html", mode="login")


@app.route("/admin-forgot-password", methods=["POST"])
def admin_forgot_password():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for("admin_dashboard"))
        flash("Acceso denegado", "login")
        return redirect(url_for("calendar"))

    username = request.form.get("username", "").strip()
    new_password = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    if not username or not new_password or not confirm:
        flash("Completa usuario y las dos contraseñas", "admin_forgot")
        return render_template("admin_login.html", mode="forgot")

    if new_password != confirm:
        flash("Las contraseñas no coinciden", "admin_forgot")
        return render_template("admin_login.html", mode="forgot")

    password_error = validate_password_strength(new_password)
    if password_error:
        flash(password_error, "admin_forgot")
        return render_template("admin_login.html", mode="forgot")

    user = User.query.filter_by(username=username).first()
    if not user or not user.active:
        flash("Usuario no encontrado o inactivo", "admin_forgot")
        return render_template("admin_login.html", mode="forgot")
    if not user.is_admin:
        flash("Este formulario aplica solo a administradores", "admin_forgot")
        return render_template("admin_login.html", mode="forgot")

    user.password_hash = generate_password_hash(new_password)
    create_audit_log(
        actor_user_id=user.id,
        target_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        action="password_reset",
        reason="Recuperación de contraseña desde admin-login",
        details="Cambio de contraseña de administrador sin sesión activa",
    )
    db.session.commit()

    flash("Contraseña de administrador actualizada. Ya puedes iniciar sesión", "admin_login")
    return render_template("admin_login.html", mode="login")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("home"))


@app.route("/")
def home():
    return redirect(url_for("login"))


@app.route("/calendar")
@login_required
def calendar():
    day_value = date.today()
    if request.args.get("day"):
        try:
            day_value = parse_iso_date(request.args["day"])
        except ValueError:
            flash("Dia invalido")

    selected_user_id = current_user.id
    users = []

    if current_user.is_admin:
        users = User.query.filter_by(rol="employee").order_by(User.username.asc()).all()

        if request.args.get("user_id"):
            try:
                requested_user_id = int(request.args["user_id"])
                if any(user.id == requested_user_id for user in users):
                    selected_user_id = requested_user_id
                elif users:
                    selected_user_id = users[0].id
                    flash("Empleado invalido")
            except ValueError:
                flash("Empleado invalido")
                if users:
                    selected_user_id = users[0].id
        elif users:
            selected_user_id = users[0].id

    # Monthly bounds
    month_start = day_value.replace(day=1)
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1, day=1) - timedelta(days=1)

    selected_user = db.session.get(User, selected_user_id)

    entries = (
        TimeEntry.query.filter(
            TimeEntry.user_id == selected_user_id,
            TimeEntry.work_date >= month_start,
            TimeEntry.work_date <= month_end,
        )
        .order_by(TimeEntry.work_date.asc())
        .all()
    )

    entries_by_day_map = {}
    for item in entries:
        entries_by_day_map.setdefault(item.work_date, []).append(item)

    # Build dict for JS calendar rendering
    month_entries_dict = {}
    for d, day_entries in entries_by_day_map.items():
        entry = day_entries[0]
        month_entries_dict[d.isoformat()] = {
            "id": entry.id,
            "check_in": entry.check_in.strftime("%H:%M") if entry.check_in else "",
            "check_out": entry.check_out.strftime("%H:%M") if entry.check_out else "",
            "meal_start": entry.meal_start.strftime("%H:%M") if entry.meal_start else "",
            "meal_end": entry.meal_end.strftime("%H:%M") if entry.meal_end else "",
            "pause_start": entry.pause_start.strftime("%H:%M") if entry.pause_start else "",
            "pause_end": entry.pause_end.strftime("%H:%M") if entry.pause_end else "",
            "overtime_start": entry.overtime_start.strftime("%H:%M") if entry.overtime_start else "",
            "overtime_end": entry.overtime_end.strftime("%H:%M") if entry.overtime_end else "",
            "meal_hours": round(meal_hours(entry), 2),
            "pause_hours": round(pause_hours(entry), 2),
            "worked_hours": round(worked_hours(entry), 2),
            "overtime_hours": round(overtime_hours(entry), 2),
            "comments": entry.comments or "",
            "editable": can_edit_entry(current_user, entry),
            "overtime_validated": entry.overtime_validated,
        }

    selected_entry = entries_by_day_map.get(day_value, [None])[0]

    # Weekly metrics for the week containing selected day (across month boundaries)
    weekly_stats = weekly_breakdown_for_user(selected_user_id, day_value)

    allow_entry_edit = bool(selected_entry and can_edit_entry(current_user, selected_entry))

    return render_template(
        "calendar.html",
        month_start=month_start,
        month_end=month_end,
        entries=entries,
        selected_day=day_value,
        selected_user=selected_user,
        users=users,
        selected_entry=selected_entry,
        allow_entry_edit=allow_entry_edit,
        weekly_total=weekly_stats["effective_hours"],
        weekly_meal_total=weekly_stats["meal_hours"],
        weekly_pause_total=weekly_stats["pause_hours"],
        weekly_overtime_total=weekly_stats["overtime_hours"],
        weekly_over_limit_hours=weekly_stats["over_limit_hours"],
        week_start=weekly_stats["week_start"],
        week_end=weekly_stats["week_end"],
        max_weekly_hours=MAX_WEEKLY_HOURS,
        today=date.today(),
        worked_hours=worked_hours,
        overtime_hours=overtime_hours,
        meal_hours=meal_hours,
        pause_hours=pause_hours,
        month_entries_dict=month_entries_dict,
    )


@app.route("/add_entry", methods=["POST"])
@login_required
def add_entry():
    if current_user.is_admin:
        flash("Los administradores no pueden crear registros desde esta pantalla")
        return redirect(url_for("calendar"))
    payload = {
        "work_date": request.form.get("work_date"),
        "check_in": request.form.get("check_in"),
        "meal_start": request.form.get("meal_start"),
        "meal_end": request.form.get("meal_end"),
        "pause_start": request.form.get("pause_start"),
        "pause_end": request.form.get("pause_end"),
        "overtime_start": request.form.get("overtime_start"),
        "overtime_end": request.form.get("overtime_end"),
        "check_out": request.form.get("check_out"),
        "comments": request.form.get("comments"),
        "location_latitude": request.form.get("location_latitude"),
        "location_longitude": request.form.get("location_longitude"),
    }

    error, normalized = validate_entry_payload(payload)
    if error:
        flash(error)
        return redirect(url_for("calendar"))

    target_user_id = current_user.id
    if current_user.is_admin and request.form.get("user_id"):
        target_user_id = int(request.form["user_id"])

    # Empleado: solo puede crear su registro del dia actual.
    if not current_user.is_admin and normalized["work_date"] != date.today():
        flash("Solo puedes registrar la jornada del dia actual")
        return redirect(url_for("calendar"))

    exists = TimeEntry.query.filter_by(user_id=target_user_id, work_date=normalized["work_date"]).first()
    if exists:
        flash("Ya existe un registro para ese dia. No se permiten ediciones")
        return redirect(url_for("calendar", user_id=target_user_id, day=normalized["work_date"].isoformat()))

    candidate = TimeEntry(
        user_id=target_user_id,
        work_date=normalized["work_date"],
        check_in=normalized["check_in"],
        meal_start=normalized["meal_start"],
        meal_end=normalized["meal_end"],
        pause_start=normalized["pause_start"],
        pause_end=normalized["pause_end"],
        overtime_start=normalized["overtime_start"],
        overtime_end=normalized["overtime_end"],
        check_out=normalized["check_out"],
        comments=normalized["comments"],
        location_latitude=normalized["location_latitude"],
        location_longitude=normalized["location_longitude"],
    )

    projected = weekly_hours_for_user(target_user_id, normalized["work_date"]) + worked_hours(candidate)
    if projected > MAX_WEEKLY_HOURS:
        flash("No puedes superar 40 horas efectivas semanales")
        return redirect(url_for("calendar", user_id=target_user_id, day=normalized["work_date"].isoformat()))

    db.session.add(candidate)
    db.session.flush()
    create_audit_log(
        actor_user_id=current_user.id,
        target_user_id=target_user_id,
        time_entry_id=candidate.id,
        entity_type="time_entry",
        entity_id=candidate.id,
        action="create",
        reason="Alta inicial de jornada",
        details=f"Entrada {candidate.check_in.strftime('%H:%M')} / Salida {candidate.check_out.strftime('%H:%M')}",
    )
    db.session.commit()

    flash("Registro guardado")
    return redirect(url_for("calendar", user_id=target_user_id, day=normalized["work_date"].isoformat()))


@app.route("/entries/<int:entry_id>/update", methods=["POST"])
@login_required
def update_entry(entry_id):
    entry = db.session.get(TimeEntry, entry_id)
    if not entry:
        flash("Registro no encontrado")
        return redirect(url_for("calendar"))

    if not can_edit_entry(current_user, entry):
        if entry.overtime_validated and not current_user.is_admin:
            flash("Este registro ya ha sido validado por el administrador y no puede modificarse")
        else:
            flash("No tienes permisos para modificar este registro")
        return redirect(url_for("calendar", user_id=entry.user_id, day=entry.work_date.isoformat()))

    reason = request.form.get("change_reason")
    reason_error = change_reason_required(reason)
    if reason_error:
        flash(reason_error)
        return redirect(url_for("calendar", user_id=entry.user_id, day=entry.work_date.isoformat()))

    payload = {
        "work_date": entry.work_date.isoformat(),
        "check_in": request.form.get("check_in"),
        "meal_start": request.form.get("meal_start"),
        "meal_end": request.form.get("meal_end"),
        "pause_start": request.form.get("pause_start"),
        "pause_end": request.form.get("pause_end"),
        "overtime_start": request.form.get("overtime_start"),
        "overtime_end": request.form.get("overtime_end"),
        "check_out": request.form.get("check_out"),
        "comments": request.form.get("comments"),
        "location_latitude": request.form.get("location_latitude"),
        "location_longitude": request.form.get("location_longitude"),
    }
    error, normalized = validate_entry_payload(payload)
    if error:
        flash(error)
        return redirect(url_for("calendar", user_id=entry.user_id, day=entry.work_date.isoformat()))

    original_week_hours = weekly_hours_for_user(entry.user_id, entry.work_date) - worked_hours(entry)
    updated_candidate = TimeEntry(
        user_id=entry.user_id,
        work_date=entry.work_date,
        check_in=normalized["check_in"],
        meal_start=normalized["meal_start"],
        meal_end=normalized["meal_end"],
        pause_start=normalized["pause_start"],
        pause_end=normalized["pause_end"],
        overtime_start=normalized["overtime_start"],
        overtime_end=normalized["overtime_end"],
        check_out=normalized["check_out"],
        comments=normalized["comments"],
        location_latitude=normalized["location_latitude"],
        location_longitude=normalized["location_longitude"],
    )
    projected = original_week_hours + worked_hours(updated_candidate)
    if projected > MAX_WEEKLY_HOURS:
        flash("La modificación supera 40 horas efectivas semanales")
        return redirect(url_for("calendar", user_id=entry.user_id, day=entry.work_date.isoformat()))

    previous = serialize_entry(entry)
    entry.check_in = normalized["check_in"]
    entry.meal_start = normalized["meal_start"]
    entry.meal_end = normalized["meal_end"]
    entry.pause_start = normalized["pause_start"]
    entry.pause_end = normalized["pause_end"]
    entry.overtime_start = normalized["overtime_start"]
    entry.overtime_end = normalized["overtime_end"]
    entry.check_out = normalized["check_out"]
    entry.comments = normalized["comments"]
    entry.location_latitude = normalized["location_latitude"]
    entry.location_longitude = normalized["location_longitude"]
    entry.overtime_validated = False

    create_audit_log(
        actor_user_id=current_user.id,
        target_user_id=entry.user_id,
        time_entry_id=entry.id,
        entity_type="time_entry",
        entity_id=entry.id,
        action="update",
        reason=reason,
        details=f"Antes={previous}; Despues={serialize_entry(entry)}",
    )
    db.session.commit()
    flash("Registro actualizado. Las horas extra quedan pendientes de nueva validación.")
    return redirect(url_for("calendar", user_id=entry.user_id, day=entry.work_date.isoformat()))


@app.route("/admin/users/<int:user_id>/reset-password", methods=["POST"])
@login_required
def reset_user_password(user_id):
    if not current_user.is_admin:
        flash("Acceso denegado")
        return redirect(url_for("calendar"))

    user = db.session.get(User, user_id)
    if not user:
        flash("Usuario no encontrado")
        return redirect(url_for("admin_users"))

    if user.rol != "employee":
        flash("Solo se pueden gestionar empleados desde esta sección")
        return redirect(url_for("admin_users"))

    new_password = request.form.get("new_password", "")
    reason = request.form.get("change_reason")

    password_error = validate_password_strength(new_password)
    if password_error:
        flash(password_error)
        return redirect(url_for("admin_users"))

    reason_error = change_reason_required(reason)
    if reason_error:
        flash(reason_error)
        return redirect(url_for("admin_users"))

    user.password_hash = generate_password_hash(new_password)
    create_audit_log(
        actor_user_id=current_user.id,
        target_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        action="password_reset",
        reason=reason,
        details="Reinicio de contraseña desde administración",
    )
    db.session.commit()
    flash("Contraseña reiniciada correctamente")
    return redirect(url_for("admin_users"))


@app.route("/admin", methods=["GET"])
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash("Acceso denegado")
        return redirect(url_for("calendar"))

    users = User.query.order_by(User.username.asc()).all()
    total_users = len(users)
    active_users = sum(1 for user in users if user.active)
    employee_users = sum(1 for user in users if user.rol == "employee")
    today_entries = TimeEntry.query.filter(TimeEntry.work_date == date.today()).count()
    recent_entries = (
        TimeEntry.query.order_by(TimeEntry.created_at.desc())
        .limit(8)
        .all()
    )

    return render_template(
        "admin_dashboard.html",
        total_users=total_users,
        active_users=active_users,
        employee_users=employee_users,
        today_entries=today_entries,
        recent_entries=recent_entries,
    )


@app.route("/admin/company", methods=["GET", "POST"])
@login_required
def admin_company():
    if not current_user.is_admin:
        flash("Acceso denegado")
        return redirect(url_for("calendar"))

    profile = get_company_profile()

    if request.method == "POST":
        profile.company_name = (request.form.get("company_name") or "").strip()
        profile.tax_id = (request.form.get("tax_id") or "").strip()
        profile.fiscal_address = (request.form.get("fiscal_address") or "").strip()
        profile.postal_code = (request.form.get("postal_code") or "").strip()
        profile.city = (request.form.get("city") or "").strip()
        profile.province = (request.form.get("province") or "").strip()
        profile.country = (request.form.get("country") or "").strip() or "Espana"
        profile.phone = (request.form.get("phone") or "").strip()
        profile.referral_source = (request.form.get("referral_source") or "").strip()
        profile.data_policy_accepted = bool(request.form.get("data_policy_accepted"))
        profile.processing_manager_accepted = bool(request.form.get("processing_manager_accepted"))

        create_audit_log(
            actor_user_id=current_user.id,
            entity_type="company_profile",
            entity_id=profile.id,
            action="update",
            reason="Actualizacion de datos de empresa",
            details=f"Empresa={profile.company_name}; CIF={profile.tax_id}; Ciudad={profile.city}",
        )
        db.session.commit()
        flash("Datos de empresa guardados correctamente")
        return redirect(url_for("admin_company"))

    users = User.query.order_by(User.username.asc()).all()
    return render_template(
        "admin_company.html",
        profile=profile,
        total_users=len(users),
        active_users=sum(1 for user in users if user.active),
        employee_users=sum(1 for user in users if user.rol == "employee"),
    )


@app.route("/admin/users", methods=["GET", "POST"])
@login_required
def admin_users():
    if not current_user.is_admin:
        flash("Acceso denegado")
        return redirect(url_for("calendar"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        tax_id = request.form.get("tax_id", "").strip()
        affiliation_number = request.form.get("affiliation_number", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        employment_type = "Interno"
        address = request.form.get("address", "").strip()
        postal_code = request.form.get("postal_code", "").strip()
        city = request.form.get("city", "").strip()
        province = request.form.get("province", "").strip()
        country = request.form.get("country", "España").strip() or "España"
        rol = request.form.get("rol", "employee")

        # Validar campos obligatorios
        if not username or not password:
            flash("Usuario y password son obligatorios")
            return redirect(url_for("admin_users"))
        if not first_name or not last_name or not tax_id or not affiliation_number or not email:
            flash("Nombre, Apellidos, CIF/NIF/DNI, Nº Afiliación y Correo son obligatorios")
            return redirect(url_for("admin_users"))
        if any(char.isspace() for char in tax_id):
            flash("El CIF/NIF/DNI no puede contener espacios")
            return redirect(url_for("admin_users"))
        if not address or not postal_code or not city or not province or not country:
            flash("Dirección, Código postal, Ciudad, Provincia y País son obligatorios")
            return redirect(url_for("admin_users"))

        password_error = validate_password_strength(password)
        if password_error:
            flash(password_error)
            return redirect(url_for("admin_users"))

        if User.query.filter_by(username=username).first():
            flash("Ese usuario ya existe")
            return redirect(url_for("admin_users"))

        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            first_name=first_name,
            last_name=last_name,
            tax_id=tax_id,
            affiliation_number=affiliation_number,
            email=email,
            phone=phone,
            employment_type=employment_type,
            address=address,
            postal_code=postal_code,
            city=city,
            province=province,
            country=country,
            rol=rol,
            active=True,
        )
        db.session.add(user)
        db.session.flush()
        create_audit_log(
            actor_user_id=current_user.id,
            target_user_id=user.id,
            entity_type="user",
            entity_id=user.id,
            action="create",
            reason="Alta de usuario por administración",
            details=f"Usuario {username} con rol {rol}",
        )
        db.session.commit()
        flash("Usuario creado")
        return redirect(url_for("admin_users"))

    users = User.query.order_by(User.username.asc()).all()
    response = make_response(render_template("admin_users.html", users=users))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@login_required
def toggle_user(user_id):
    if not current_user.is_admin:
        flash("Acceso denegado")
        return redirect(url_for("calendar"))

    user = db.session.get(User, user_id)
    if not user:
        flash("Usuario no encontrado")
        return redirect(url_for("admin_users"))

    if user.rol != "employee":
        flash("Solo se pueden gestionar empleados desde esta sección")
        return redirect(url_for("admin_users"))

    if user.id == current_user.id:
        flash("No puedes desactivar tu propia cuenta")
        return redirect(url_for("admin_users"))

    reason = request.form.get("change_reason")
    reason_error = change_reason_required(reason)
    if reason_error:
        flash(reason_error)
        return redirect(url_for("admin_users"))

    user.active = not user.active
    create_audit_log(
        actor_user_id=current_user.id,
        target_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        action="status_change",
        reason=reason,
        details=f"Nuevo estado activo={user.active}",
    )
    db.session.commit()
    flash("Estado actualizado")
    return redirect(url_for("admin_users"))


@app.route("/admin/validate-hours", methods=["GET"])
@login_required
def admin_validate_hours():
    if not current_user.is_admin:
        flash("Acceso denegado")
        return redirect(url_for("calendar"))

    month = request.args.get("month") or date.today().strftime("%Y-%m")
    selected_user_id = (request.args.get("user_id") or "all").strip()
    
    try:
        month_start = datetime.strptime(f"{month}-01", "%Y-%m-%d").date()
    except ValueError:
        month = date.today().strftime("%Y-%m")
        month_start = datetime.strptime(f"{month}-01", "%Y-%m-%d").date()

    if month_start.month == 12:
        month_end_exclusive = month_start.replace(year=month_start.year + 1, month=1, day=1)
    else:
        month_end_exclusive = month_start.replace(month=month_start.month + 1, day=1)

    users = (
        User.query
        .filter(User.rol != "admin", User.active.is_(True))
        .order_by(User.first_name.asc(), User.last_name.asc(), User.username.asc())
        .all()
    )

    user_ids = {str(user.id) for user in users}
    if selected_user_id != "all" and selected_user_id not in user_ids:
        selected_user_id = "all"

    query = (
        TimeEntry.query.join(TimeEntry.user)
        .filter(
            TimeEntry.work_date >= month_start,
            TimeEntry.work_date < month_end_exclusive,
        )
    )
    if selected_user_id != "all":
        query = query.filter(TimeEntry.user_id == int(selected_user_id))

    entries = query.order_by(TimeEntry.work_date.desc(), User.username.asc()).all()

    change_reasons = latest_change_reasons_for_entries(entries)

    return render_template(
        "validate_hours.html",
        entries=entries,
        month=month,
        users=users,
        selected_user_id=selected_user_id,
        worked_hours=worked_hours,
        meal_hours=meal_hours,
        pause_hours=pause_hours,
        overtime_hours=overtime_hours,
        change_reasons=change_reasons,
    )


@app.route("/admin/toggle-validation/<int:entry_id>", methods=["POST"])
@login_required
def toggle_validation(entry_id):
    if not current_user.is_admin:
        return jsonify({"error": "Acceso denegado"}), 403

    entry = db.session.get(TimeEntry, entry_id)
    if not entry:
        return jsonify({"error": "Registro no encontrado"}), 404

    # La pantalla de validación solo permite marcar como validado.
    if entry.overtime_validated:
        return jsonify({
            "success": True,
            "validated": True,
            "status": "Validado",
        })

    entry.overtime_validated = True
    create_audit_log(
        actor_user_id=current_user.id,
        target_user_id=entry.user_id,
        time_entry_id=entry.id,
        entity_type="time_entry",
        entity_id=entry.id,
        action="toggle_validation",
        reason="Registro validado por admin",
        details=f"Horas: {worked_hours(entry):.2f}h, Estado: validado",
    )
    db.session.commit()

    return jsonify({
        "success": True,
        "validated": True,
        "status": "Validado",
    })


@app.route("/report")
@login_required
def report():
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    active_user, selected_user_id, selected_user, entries, change_reasons, include_all = report_context(month)
    company_profile = get_company_profile()

    users = report_employee_users() if active_user.is_admin else []

    total = round(sum(worked_hours(item) for item in entries), 2)

    return render_template(
        "report.html",
        month=month,
        users=users,
        company_profile=company_profile,
        include_all=include_all,
        selected_user_id=selected_user_id,
        selected_user=selected_user,
        entries=entries,
        change_reasons=change_reasons,
        total=total,
        worked_hours=worked_hours,
        overtime_hours=overtime_hours,
        meal_hours=meal_hours,
        pause_hours=pause_hours,
    )


@app.route("/report/excel")
@login_required
def report_excel():
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    active_user, selected_user_id, selected_user, entries, change_reasons, include_all = report_context(month)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Parte de Tiempo"
    company_profile = get_company_profile()

    company_name = (company_profile.company_name or "Superpekes").strip()
    company_city = (company_profile.city or "").strip()
    company_country = (company_profile.country or "").strip()
    company_city_country = ", ".join([part for part in [company_city, company_country] if part])
    company_line = " | ".join(
        [
            part
            for part in [
                f"CIF: {company_profile.tax_id}" if company_profile.tax_id else "",
                company_profile.fiscal_address or "",
                company_city_country,
                f"Tel: {company_profile.phone}" if company_profile.phone else "",
            ]
            if part
        ]
    )

    if selected_user:
        full_name = f"{(selected_user.first_name or '').strip()} {(selected_user.last_name or '').strip()}".strip()
        employee_name = full_name or selected_user.username or "-"
        employee_id = selected_user.affiliation_number or "-"
        employee_department = selected_user.employment_type or "-"
    else:
        employee_name = "Todos"
        employee_id = "-"
        employee_department = "-"

    dark_blue = "1E3A5F"
    mid_blue = "2F6D94"
    light_blue = "DCEEFF"
    white = "FFFFFF"
    line_blue = "9BB7D4"

    col_widths = {"A": 12, "B": 10, "C": 10, "D": 15, "E": 13, "F": 12, "G": 12, "H": 30}
    for col, width in col_widths.items():
        sheet.column_dimensions[col].width = width

    sheet.merge_cells("A1:H2")
    title_cell = sheet["A1"]
    title_cell.value = ""
    title_cell.fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 38
    sheet.row_dimensions[2].height = 38

    xl_logo = None
    logo_original_width = 1.0
    logo_original_height = 1.0
    logo_path = os.path.join(app.static_folder, "img", "Logo_parte de tiempo.png")
    if os.path.exists(logo_path):
        xl_logo = XlImage(logo_path)
        logo_original_width = max(float(xl_logo.width), 1.0)
        logo_original_height = max(float(xl_logo.height), 1.0)
        sheet.add_image(xl_logo, "A1")

    # Row 3 as a visible spacer under the logo banner.
    sheet.row_dimensions[3].height = 20

    info_rows = [
        ("Nombre del empleado:", employee_name, "Titulo:", "-"),
        ("Nª de afiliacion:", employee_id, "Supervisor:", "-"),
        ("Departamento:", employee_department, "Mes:", month),
    ]
    info_start = 4
    for idx, (l1, v1, l2, v2) in enumerate(info_rows):
        row = info_start + idx
        sheet.cell(row=row, column=1, value=l1).font = Font(bold=True, color=dark_blue)
        sheet.cell(row=row, column=2, value=v1).alignment = Alignment(horizontal="left")
        sheet.cell(row=row, column=4, value=l2).font = Font(bold=True, color=dark_blue)
        sheet.cell(row=row, column=5, value=v2).alignment = Alignment(horizontal="left")

    table_headers = [
        "FECHA",
        "ENTRADA",
        "SALIDA",
        "HORAS EFECTIVAS",
        "HORAS COMIDA",
        "HORAS PAUSA",
        "HORAS EXTRAS",
        "MOTIVO DEL CAMBIO",
    ]
    header_top_row = 8
    header_bottom_row = 9
    header_fill = GradientFill(
        type="linear",
        degree=90,
        stop=("CCE6FA", "ADD3F2"),
    )
    header_border = Border(
        left=Side(style="thin", color=line_blue),
        right=Side(style="thin", color=line_blue),
        top=Side(style="thin", color=line_blue),
        bottom=Side(style="thin", color=line_blue),
    )
    header_top_border = Border(
        left=Side(style="thin", color=line_blue),
        right=Side(style="thin", color=line_blue),
        top=Side(style="thin", color=line_blue),
        bottom=Side(style=None),
    )
    header_bottom_border = Border(
        left=Side(style="thin", color=line_blue),
        right=Side(style="thin", color=line_blue),
        top=Side(style=None),
        bottom=Side(style="thin", color=line_blue),
    )

    # Same visual scale as validate_hours table headers (small size) and no bold.
    header_text_color = "1E3A8A"
    header_font = Font(bold=False, size=10, color=header_text_color)

    for col, header in enumerate(table_headers, start=1):
        col_letter = get_column_letter(col)
        sheet.merge_cells(f"{col_letter}{header_top_row}:{col_letter}{header_bottom_row}")
        words = header.split(" ")
        display_header = f"{words[0]}\n{' '.join(words[1:])}" if len(words) > 1 else header
        cell = sheet.cell(row=header_top_row, column=col, value=display_header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        cell.border = header_border

    sheet.row_dimensions[header_top_row].height = 24
    sheet.row_dimensions[header_bottom_row].height = 0

    border = Border(
        left=Side(style="thin", color=line_blue),
        right=Side(style="thin", color=line_blue),
        top=Side(style="thin", color=line_blue),
        bottom=Side(style="thin", color=line_blue),
    )

    total_regular = 0.0
    total_meal = 0.0
    total_pause = 0.0
    total_overtime = 0.0
    data_row = header_bottom_row + 1
    rendered_rows = 0

    for item in entries:
        regular = worked_hours(item)
        meal = meal_hours(item)
        pause = pause_hours(item)
        overtime = overtime_hours(item)
        total_regular += regular
        total_meal += meal
        total_pause += pause
        total_overtime += overtime
        reason_lines = [line.strip() for line in (change_reasons.get(item.id, "") or "").splitlines() if line.strip()]
        reason = "\n".join(reason_lines)

        values = [
            item.work_date.isoformat(),
            item.check_in.strftime("%H:%M") if item.check_in else "-",
            item.check_out.strftime("%H:%M") if item.check_out else "-",
            f"{regular:.2f}",
            f"{meal:.2f}",
            f"{pause:.2f}",
            f"{overtime:.2f}",
            reason[:120],
        ]
        for col, value in enumerate(values, start=1):
            cell = sheet.cell(row=data_row, column=col, value=value)
            cell.border = border
            if col in {2, 3, 4, 5, 6, 7}:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col == 8:
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        sheet.row_dimensions[data_row].height = max(22, (len(reason_lines) or 1) * 14)
        data_row += 1
        rendered_rows += 1

    while rendered_rows < 9:
        for col in range(1, 9):
            cell = sheet.cell(row=data_row, column=col, value="")
            cell.border = border
        sheet.row_dimensions[data_row].height = 22
        data_row += 1
        rendered_rows += 1

    summary_row = data_row + 1
    firma_cell = sheet.cell(row=summary_row, column=1, value="Firma")
    firma_cell.font = header_font
    firma_cell.fill = header_fill
    firma_cell.alignment = Alignment(horizontal="left", vertical="center")
    firma_cell.border = border

    white_fill = PatternFill(start_color=white, end_color=white, fill_type="solid")
    for col in range(2, 6):
        cell = sheet.cell(row=summary_row, column=col, value="")
        cell.fill = white_fill
        cell.border = Border()
        cell.alignment = Alignment(horizontal="center", vertical="center")

    totals_labels = [
        (6, "H.EFECTIVAS", f"{total_regular:.2f} h"),
        (7, "H.PAUSA", f"{total_pause:.2f} h"),
        (8, "H.EXTRAS", f"{total_overtime:.2f} h"),
    ]
    summary_label_fill = header_fill
    box_side = Side(style="thin", color=line_blue)
    label_row = summary_row - 1
    for col, label, value in totals_labels:
        col_letter = get_column_letter(col)
        sheet.merge_cells(f"{col_letter}{label_row}:{col_letter}{summary_row}")
        # Celda superior (label_row): borde top + left + right
        block_cell = sheet.cell(row=label_row, column=col, value=f"{label}\n{value}")
        block_cell.font = header_font
        block_cell.fill = summary_label_fill
        block_cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        block_cell.border = Border(
            left=box_side, right=box_side, top=box_side, bottom=box_side,
        )
        # Celda inferior (summary_row): borde bottom + left + right
        # (openpyxl necesita esto para que el borde inferior de la celda combinada sea visible)
        bottom_cell = sheet.cell(row=summary_row, column=col)
        bottom_cell.fill = summary_label_fill
        bottom_cell.border = Border(
            left=box_side, right=box_side, bottom=box_side,
        )

    def estimate_excel_text_width(value: object) -> float:
        """Estimate display width used by Excel for a cell value."""
        if value is None:
            return 0.0
        text = str(value)
        lines = text.splitlines() or [text]
        widest = 0.0
        for line in lines:
            line_w = 0.0
            for ch in line:
                if ch in "WM@%#":
                    line_w += 1.35
                elif ch.isupper():
                    line_w += 1.15
                elif ch.isdigit():
                    line_w += 1.0
                else:
                    line_w += 0.95
            widest = max(widest, line_w)
        return widest

    # Intelligent auto-fit for all columns based on visible content.
    # Merged cells are weighted by merged span to avoid inflating one column.
    merged_spans = {
        (rng.min_row, rng.min_col): (rng.max_col - rng.min_col + 1)
        for rng in sheet.merged_cells.ranges
    }
    for col in range(1, 9):
        col_letter = get_column_letter(col)
        max_width = 0.0
        for row in range(1, summary_row + 1):
            cell = sheet.cell(row=row, column=col)
            value = cell.value
            if value in (None, ""):
                continue
            span_cols = merged_spans.get((row, col), 1)
            est_width = estimate_excel_text_width(value)
            if span_cols > 1:
                est_width /= span_cols
            max_width = max(max_width, est_width)
        # Clamp keeps print layout stable but still responsive to content.
        sheet.column_dimensions[col_letter].width = min(max(9, max_width + 2.5), 52)

    if xl_logo is not None:
        # Match logo width to final width of columns A:D after auto-fit.
        target_width_px = int(
            sum((((sheet.column_dimensions[get_column_letter(c)].width or 8.43) * 7) + 5) for c in range(1, 5))
            * 1.60
        )
        scale = target_width_px / logo_original_width
        xl_logo.width = int(logo_original_width * scale)
        xl_logo.height = int(logo_original_height * scale)

        # Keep enough row height so the logo stays sharp and fully visible.
        required_points = (xl_logo.height * 0.75) + 2
        row_height = max(24, required_points / 2)
        sheet.row_dimensions[1].height = row_height
        sheet.row_dimensions[2].height = row_height

    # Keep full table inside page width when printing/exporting to PDF.
    sheet.print_area = f"A1:H{summary_row}"
    sheet.sheet_view.showGridLines = False
    sheet.print_options.gridLines = False
    sheet.page_setup.orientation = "portrait"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.page_margins.left = 0.4
    sheet.page_margins.right = 0.4
    sheet.page_margins.top = 0.4
    sheet.page_margins.bottom = 0.4
    sheet.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True, autoPageBreaks=False)

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)

    target_label = "todos" if include_all else str(selected_user_id)
    filename = f"parte_tiempo_{target_label}_{month}.xlsx"
    return send_file(output, as_attachment=True, download_name=filename, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/report/pdf")
@login_required
def report_pdf():
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    active_user, selected_user_id, selected_user, entries, change_reasons, include_all = report_context(month)
    company_profile = get_company_profile()

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    page_width, page_height = A4

    company_name = (company_profile.company_name or "Superpekes").strip()
    city_country = ", ".join([part for part in [company_profile.city, company_profile.country] if part])
    company_line = " | ".join(
        [
            part
            for part in [
                f"CIF: {company_profile.tax_id}" if company_profile.tax_id else "",
                company_profile.fiscal_address or "",
                city_country,
                f"Tel: {company_profile.phone}" if company_profile.phone else "",
            ]
            if part
        ]
    )

    if selected_user:
        full_name = f"{(selected_user.first_name or '').strip()} {(selected_user.last_name or '').strip()}".strip()
        employee_name = full_name or selected_user.username or "-"
        employee_id = selected_user.affiliation_number or "-"
        employee_department = selected_user.employment_type or "-"
    else:
        employee_name = "Todos"
        employee_id = "-"
        employee_department = "-"

    rows = []
    total_regular = 0.0
    total_pause = 0.0
    total_overtime = 0.0
    for item in entries:
        regular = worked_hours(item)
        meal = meal_hours(item)
        pause = pause_hours(item)
        overtime = overtime_hours(item)
        total_regular += regular
        total_pause += pause
        total_overtime += overtime
        reason_lines = [line.strip() for line in (change_reasons.get(item.id, "") or "").splitlines() if line.strip()]
        rows.append(
            [
                item.work_date.isoformat() if item.work_date else "-",
                item.check_in.strftime("%H:%M") if item.check_in else "-",
                item.check_out.strftime("%H:%M") if item.check_out else "-",
                f"{regular:.2f}",
                f"{meal:.2f}",
                f"{pause:.2f}",
                f"{overtime:.2f}",
                reason_lines,
            ]
        )

    while len(rows) < 9:
        rows.append(["", "", "", "", "", "", "", []])

    def draw_header_block() -> float:
        top = page_height - 24

        # Fill top strip so no white band appears when printing.
        pdf.setFillColorRGB(0.55, 0.67, 0.80)
        pdf.rect(0, top, page_width, 24, fill=1, stroke=0)

        pdf.setFillColorRGB(0.55, 0.67, 0.80)
        pdf.rect(0, top - 98, page_width, 98, fill=1, stroke=0)

        pdf.setFillColorRGB(0.12, 0.25, 0.45)
        path = pdf.beginPath()
        path.moveTo(140, top - 6)
        path.lineTo(page_width, top - 6)
        path.lineTo(page_width, top - 52)
        path.lineTo(228, top - 52)
        path.lineTo(162, top - 6)
        path.close()
        pdf.drawPath(path, fill=1, stroke=0)

        title_text = "PARTE DE TIEMPO"
        title_x = (page_width / 2) + 118
        title_y = top - 36

        # 3D text effect: layered dark offsets plus bright front text.
        pdf.setFont("Helvetica-Bold", 20)
        pdf.setFillColorRGB(0.04, 0.12, 0.28)
        pdf.drawCentredString(title_x + 2.8, title_y - 2.6, title_text)
        pdf.setFillColorRGB(0.08, 0.19, 0.37)
        pdf.drawCentredString(title_x + 1.6, title_y - 1.4, title_text)
        pdf.setFillColorRGB(0.12, 0.27, 0.49)
        pdf.drawCentredString(title_x + 0.8, title_y - 0.8, title_text)
        pdf.setFillColorRGB(1, 1, 1)
        pdf.drawCentredString(title_x, title_y, title_text)

        logo_path = os.path.join(app.static_folder, "img", "Logo Superpekes.png")
        if os.path.exists(logo_path):
            pdf.drawImage(logo_path, 24, top - 60, width=88, height=67, preserveAspectRatio=True, mask="auto")

        band_y = top - 110
        pdf.setFillColorRGB(0.17, 0.43, 0.58)
        pdf.roundRect(24, band_y, 340, 22, 11, fill=1, stroke=0)
        pdf.setFillColorRGB(1, 1, 1)
        pdf.setFont("Helvetica-Bold", 13)
        pdf.drawString(34, band_y + 6, "EMPRESA")

        pdf.setFillGray(0.15)
        pdf.setFont("Helvetica", 8)
        pdf.drawString(24, band_y - 11, company_line or "-")

        left_x = 24
        right_x = 318
        info_y = band_y - 34
        label_font_size = 8
        value_font_size = 8

        pdf.setFont("Helvetica-Bold", label_font_size)
        pdf.drawString(left_x, info_y, "Nombre del empleado:")
        pdf.drawString(left_x, info_y - 14, "Nª de afiliacion:")
        pdf.drawString(left_x, info_y - 28, "Departamento:")

        pdf.drawString(right_x, info_y, "Titulo:")
        pdf.drawString(right_x, info_y - 14, "Supervisor:")
        pdf.drawString(right_x, info_y - 28, "Mes:")

        pdf.setFont("Helvetica", value_font_size)
        pdf.drawString(left_x + 120, info_y, employee_name)
        pdf.drawString(left_x + 120, info_y - 14, employee_id)
        pdf.drawString(left_x + 120, info_y - 28, employee_department)

        pdf.drawString(right_x + 54, info_y, "-")
        pdf.drawString(right_x + 54, info_y - 14, "-")
        pdf.drawString(right_x + 54, info_y - 28, month)

        return info_y - 40

    def draw_table_header(y_pos: float, col_widths: list[int], headers: list[str]) -> float:
        x = 24
        total_width = sum(col_widths)
        top_h = 13
        bottom_h = 13
        total_h = top_h + bottom_h

        # Smooth blue gradient like the metrics block, without visible banding.
        pdf.saveState()
        clip_path = pdf.beginPath()
        clip_path.rect(x, y_pos - total_h, total_width, total_h)
        pdf.clipPath(clip_path, stroke=0, fill=0)

        top_color = (0.80, 0.90, 0.98)
        bottom_color = (0.68, 0.83, 0.95)
        steps = 40
        step_h = total_h / steps
        for i in range(steps):
            t = i / max(steps - 1, 1)
            r = top_color[0] + (bottom_color[0] - top_color[0]) * t
            g = top_color[1] + (bottom_color[1] - top_color[1]) * t
            b = top_color[2] + (bottom_color[2] - top_color[2]) * t
            pdf.setFillColorRGB(r, g, b)
            y_step = y_pos - (i + 1) * step_h
            pdf.rect(x, y_step, total_width, step_h + 0.4, fill=1, stroke=0)
        pdf.restoreState()

        pdf.setFillColorRGB(0.12, 0.23, 0.47)
        pdf.setFont("Helvetica", 7)
        cx = x
        for idx, header in enumerate(headers):
            words = header.split(" ")
            top_text = words[0]
            bottom_text = " ".join(words[1:]) if len(words) > 1 else ""
            pad_x = cx + 4
            if bottom_text:
                pdf.drawString(pad_x, y_pos - 9, top_text)
                pdf.drawString(pad_x, y_pos - 22, bottom_text)
            else:
                pdf.drawString(pad_x, y_pos - 15, top_text)
            cx += col_widths[idx]

        # Solo líneas verticales y borde exterior; sin línea horizontal intermedia.
        pdf.setStrokeColorRGB(0.63, 0.77, 0.90)
        cx = x
        for width in col_widths:
            pdf.line(cx, y_pos - total_h, cx, y_pos)
            cx += width
        pdf.line(cx, y_pos - total_h, cx, y_pos)
        pdf.line(x, y_pos, x + total_width, y_pos)
        pdf.line(x, y_pos - total_h, x + total_width, y_pos - total_h)

        return y_pos - total_h

    table_headers = [
        "FECHA",
        "ENTRADA",
        "SALIDA",
        "HORAS EFECTIVAS",
        "HORAS COMIDA",
        "HORAS PAUSA",
        "HORAS EXTRAS",
        "MOTIVO DEL CAMBIO",
    ]
    col_widths = [52, 46, 46, 66, 58, 56, 56, 167]
    row_height = 20

    y = draw_header_block()
    y = draw_table_header(y, col_widths, table_headers)

    x_origin = 24
    pdf.setFillGray(0.2)
    pdf.setFont("Helvetica", 8)
    line_h = 10  # altura por línea de motivo

    for row in rows:
        reason_list = row[7] if isinstance(row[7], list) else ([row[7]] if row[7] else [])
        dyn_row_height = max(row_height, len(reason_list) * line_h + 8) if reason_list else row_height

        if y - dyn_row_height < 92:
            pdf.showPage()
            y = draw_header_block()
            y = draw_table_header(y, col_widths, table_headers)
            pdf.setFillGray(0.2)
            pdf.setFont("Helvetica", 8)

        cx = x_origin
        for idx, value in enumerate(row):
            if idx == 7:
                if reason_list:
                    for li, rline in enumerate(reason_list):
                        ty = y - 10 - li * line_h
                        pdf.drawString(cx + 4, ty, rline[:60])
                # columna vacía si no hay motivos
            else:
                text = value or ""
                pdf.drawCentredString(cx + col_widths[idx] / 2, y - 16, text)
            cx += col_widths[idx]

        pdf.setStrokeColorRGB(0.73, 0.78, 0.83)
        pdf.line(x_origin, y - dyn_row_height, x_origin + sum(col_widths), y - dyn_row_height)
        y -= dyn_row_height

    signature_width = 300
    totals_width = 210

    # Keep signature and totals anchored to the bottom area of A4.
    footer_anchor_y = 48
    signature_line_y = footer_anchor_y + 18

    pdf.setStrokeColorRGB(0.18, 0.45, 0.68)
    pdf.line(x_origin, signature_line_y, x_origin + signature_width, signature_line_y)
    pdf.setFillGray(0.25)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(x_origin, signature_line_y + 6, "Firma")

    totals_x = x_origin + sum(col_widths) - totals_width
    totals_y = footer_anchor_y + 2
    totals_h = 28
    section_w = totals_width / 3

    # Same blue family as table headers, with smooth vertical interpolation.
    pdf.saveState()
    clip_path = pdf.beginPath()
    clip_path.roundRect(totals_x, totals_y, totals_width, totals_h, 11)
    pdf.clipPath(clip_path, stroke=0, fill=0)

    top_color = (0.80, 0.90, 0.98)
    bottom_color = (0.68, 0.83, 0.95)
    steps = 36
    step_h = totals_h / steps
    for i in range(steps):
        t = i / max(steps - 1, 1)
        r = top_color[0] + (bottom_color[0] - top_color[0]) * t
        g = top_color[1] + (bottom_color[1] - top_color[1]) * t
        b = top_color[2] + (bottom_color[2] - top_color[2]) * t
        pdf.setFillColorRGB(r, g, b)
        y_step = totals_y + totals_h - (i + 1) * step_h
        pdf.rect(totals_x, y_step, totals_width, step_h + 0.6, fill=1, stroke=0)
    pdf.restoreState()

    pdf.setStrokeColorRGB(0.56, 0.72, 0.88)
    pdf.roundRect(totals_x, totals_y, totals_width, totals_h, 11, fill=0, stroke=1)
    pdf.setLineWidth(0.6)
    pdf.line(totals_x + section_w, totals_y + 4, totals_x + section_w, totals_y + totals_h - 4)
    pdf.line(totals_x + 2 * section_w, totals_y + 4, totals_x + 2 * section_w, totals_y + totals_h - 4)

    metrics = [
        ("H.EFECTIVAS", total_regular),
        ("H.PAUSA", total_pause),
        ("H.EXTRAS", total_overtime),
    ]
    for idx, (label, value) in enumerate(metrics):
        cx = totals_x + section_w * idx + section_w / 2
        pdf.setFillColorRGB(0.12, 0.23, 0.47)
        pdf.setFont("Helvetica", 6.4)
        pdf.drawCentredString(cx, totals_y + 18, label)
        pdf.setFont("Helvetica-Bold", 8.8)
        pdf.drawCentredString(cx, totals_y + 8, f"{value:.2f} h")

    footer = "www.superpekes.es"
    footer_parts = [part for part in [company_profile.fiscal_address, city_country, company_profile.phone] if part]
    if footer_parts:
        footer += " | " + " | ".join(footer_parts)
    pdf.setFillGray(0.45)
    pdf.setFont("Helvetica", 8)
    pdf.drawCentredString(page_width / 2, 28, footer[:120])

    pdf.save()
    buffer.seek(0)
    target_label = "todos" if include_all else str(selected_user_id)
    filename = f"parte_tiempo_{target_label}_{month}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")


# -------------------------
# REST API
# -------------------------

@app.post("/api/auth/login")
def api_login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    user = User.query.filter_by(username=username).first()
    if not user or not user.active or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Credenciales invalidas"}), 401

    return jsonify(
        {
            "token": create_api_token(user),
            "token_type": "Bearer",
            "expires_in": TOKEN_TTL_SECONDS,
            "user": {
                "id": user.id,
                "username": user.username,
                "rol": user.rol,
            },
        }
    )


@app.get("/api/me")
@api_auth_required()
def api_me():
    user = request.api_user
    return jsonify({"id": user.id, "username": user.username, "rol": user.rol, "active": user.active})


@app.get("/api/users")
@api_auth_required(admin_only=True)
def api_users_list():
    users = User.query.order_by(User.username.asc()).all()
    return jsonify(
        [
            {
                "id": u.id,
                "username": u.username,
                "rol": u.rol,
                "active": u.active,
                "created_at": u.created_at.isoformat(),
            }
            for u in users
        ]
    )


@app.post("/api/users")
@api_auth_required(admin_only=True)
def api_users_create():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    rol = (data.get("rol") or data.get("role") or "employee").strip()

    if not username or not password:
        return jsonify({"error": "username y password son obligatorios"}), 400
    if rol not in {"employee", "admin"}:
        return jsonify({"error": "rol debe ser employee o admin"}), 400
    password_error = validate_password_strength(password)
    if password_error:
        return jsonify({"error": password_error}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "El usuario ya existe"}), 409

    user = User(username=username, password_hash=generate_password_hash(password), rol=rol, active=True)
    db.session.add(user)
    db.session.flush()
    create_audit_log(
        actor_user_id=request.api_user.id,
        target_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        action="create",
        reason="Alta de usuario desde API",
        details=f"Usuario {username} con rol {rol}",
    )
    db.session.commit()

    return jsonify({"id": user.id, "username": user.username, "rol": user.rol, "active": user.active}), 201


@app.patch("/api/users/<int:user_id>/status")
@api_auth_required(admin_only=True)
def api_user_toggle(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "Usuario no encontrado"}), 404

    data = request.get_json(silent=True) or {}
    active = data.get("active")
    reason = data.get("change_reason")
    if active is None:
        return jsonify({"error": "active es obligatorio"}), 400
    reason_error = change_reason_required(reason)
    if reason_error:
        return jsonify({"error": reason_error}), 400

    user.active = bool(active)
    create_audit_log(
        actor_user_id=request.api_user.id,
        target_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        action="status_change",
        reason=reason,
        details=f"Nuevo estado activo={user.active}",
    )
    db.session.commit()
    return jsonify({"id": user.id, "active": user.active})


@app.patch("/api/users/<int:user_id>/password")
@api_auth_required(admin_only=True)
def api_user_reset_password(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "Usuario no encontrado"}), 404

    data = request.get_json(silent=True) or {}
    new_password = data.get("new_password") or ""
    reason = data.get("change_reason")

    password_error = validate_password_strength(new_password)
    if password_error:
        return jsonify({"error": password_error}), 400

    reason_error = change_reason_required(reason)
    if reason_error:
        return jsonify({"error": reason_error}), 400

    user.password_hash = generate_password_hash(new_password)
    create_audit_log(
        actor_user_id=request.api_user.id,
        target_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        action="password_reset",
        reason=reason,
        details="Reinicio de contraseña desde API",
    )
    db.session.commit()
    return jsonify({"id": user.id, "password_reset": True})


@app.get("/api/entries")
@api_auth_required()
def api_entries_list():
    api_user = request.api_user
    day_raw = request.args.get("day") or date.today().isoformat()

    try:
        day_value = parse_iso_date(day_raw)
    except ValueError:
        return jsonify({"error": "day debe tener formato YYYY-MM-DD"}), 400

    target_user_id = api_user.id
    if api_user.is_admin and request.args.get("user_id"):
        target_user_id = int(request.args["user_id"])

    start, end = week_bounds(day_value)
    entries = (
        TimeEntry.query.filter(
            TimeEntry.user_id == target_user_id,
            TimeEntry.work_date >= start,
            TimeEntry.work_date <= end,
        )
        .order_by(TimeEntry.work_date.asc())
        .all()
    )

    return jsonify(
        {
            "user_id": target_user_id,
            "week_start": start.isoformat(),
            "week_end": end.isoformat(),
            "weekly_hours": round(sum(worked_hours(item) for item in entries), 2),
            "entries": [serialize_entry(item) for item in entries],
        }
    )


@app.post("/api/entries")
@api_auth_required()
def api_entries_create():
    api_user = request.api_user
    data = request.get_json(silent=True) or {}

    error, normalized = validate_entry_payload(data)
    if error:
        return jsonify({"error": error}), 400

    target_user_id = api_user.id
    if api_user.is_admin and data.get("user_id"):
        target_user_id = int(data["user_id"])

    if not api_user.is_admin and normalized["work_date"] != date.today():
        return jsonify({"error": "Solo puedes crear el registro del dia actual"}), 403

    existing = TimeEntry.query.filter_by(user_id=target_user_id, work_date=normalized["work_date"]).first()
    if existing:
        return jsonify({"error": "Ya existe un registro para ese dia"}), 409

    candidate = TimeEntry(
        user_id=target_user_id,
        work_date=normalized["work_date"],
        check_in=normalized["check_in"],
        meal_start=normalized["meal_start"],
        meal_end=normalized["meal_end"],
        check_out=normalized["check_out"],
        comments=normalized["comments"],
        location_latitude=normalized["location_latitude"],
        location_longitude=normalized["location_longitude"],
    )

    projected = weekly_hours_for_user(target_user_id, normalized["work_date"]) + worked_hours(candidate)
    if projected > MAX_WEEKLY_HOURS:
        return jsonify({"error": "No se puede superar 40 horas efectivas semanales"}), 422

    db.session.add(candidate)
    db.session.flush()
    create_audit_log(
        actor_user_id=api_user.id,
        target_user_id=target_user_id,
        time_entry_id=candidate.id,
        entity_type="time_entry",
        entity_id=candidate.id,
        action="create",
        reason="Alta inicial de jornada desde API",
        details=f"Entrada {candidate.check_in.strftime('%H:%M')} / Salida {candidate.check_out.strftime('%H:%M')}",
    )
    db.session.commit()
    return jsonify(serialize_entry(candidate)), 201


@app.patch("/api/entries/<int:entry_id>")
@api_auth_required()
def api_entry_update(entry_id):
    api_user = request.api_user
    entry = db.session.get(TimeEntry, entry_id)
    if not entry:
        return jsonify({"error": "Registro no encontrado"}), 404
    if not can_edit_entry(api_user, entry):
        if entry.overtime_validated and not api_user.is_admin:
            return jsonify({"error": "Este registro ya ha sido validado por el administrador y no puede modificarse"}), 403
        return jsonify({"error": "No tienes permisos para modificar este registro"}), 403

    data = request.get_json(silent=True) or {}
    reason = data.get("change_reason")
    reason_error = change_reason_required(reason)
    if reason_error:
        return jsonify({"error": reason_error}), 400

    payload = {
        "work_date": entry.work_date.isoformat(),
        "check_in": data.get("check_in"),
        "meal_start": data.get("meal_start"),
        "meal_end": data.get("meal_end"),
        "check_out": data.get("check_out"),
        "comments": data.get("comments"),
    }
    error, normalized = validate_entry_payload(payload)
    if error:
        return jsonify({"error": error}), 400

    original_week_hours = weekly_hours_for_user(entry.user_id, entry.work_date) - worked_hours(entry)
    updated_candidate = TimeEntry(
        user_id=entry.user_id,
        work_date=entry.work_date,
        check_in=normalized["check_in"],
        meal_start=normalized["meal_start"],
        meal_end=normalized["meal_end"],
        check_out=normalized["check_out"],
        comments=normalized["comments"],
        location_latitude=normalized["location_latitude"],
        location_longitude=normalized["location_longitude"],
    )
    projected = original_week_hours + worked_hours(updated_candidate)
    if projected > MAX_WEEKLY_HOURS:
        return jsonify({"error": "La modificación supera 40 horas efectivas semanales"}), 422

    previous = serialize_entry(entry)
    entry.check_in = normalized["check_in"]
    entry.meal_start = normalized["meal_start"]
    entry.meal_end = normalized["meal_end"]
    entry.check_out = normalized["check_out"]
    entry.comments = normalized["comments"]
    entry.location_latitude = normalized["location_latitude"]
    entry.location_longitude = normalized["location_longitude"]
    entry.overtime_validated = False
    create_audit_log(
        actor_user_id=api_user.id,
        target_user_id=entry.user_id,
        time_entry_id=entry.id,
        entity_type="time_entry",
        entity_id=entry.id,
        action="update",
        reason=reason,
        details=f"Antes={previous}; Despues={serialize_entry(entry)}",
    )
    db.session.commit()
    result = serialize_entry(entry)
    result["needs_revalidation"] = True
    result["message"] = "Registro actualizado. Las horas extra quedan pendientes de nueva validación."
    return jsonify(result)


@app.post("/api/entries/<int:entry_id>/validate")
@api_auth_required(admin_only=True)
def api_entry_validate(entry_id):
    entry = db.session.get(TimeEntry, entry_id)
    if not entry:
        return jsonify({"error": "Registro no encontrado"}), 404

    entry.overtime_validated = True
    create_audit_log(
        actor_user_id=request.api_user.id,
        target_user_id=entry.user_id,
        time_entry_id=entry.id,
        entity_type="time_entry",
        entity_id=entry.id,
        action="validate_overtime",
        reason="Validación administrativa del registro desde API",
        details=f"Registro validado desde API. Horas extra detectadas: {overtime_hours(entry):.2f}",
    )
    db.session.commit()
    return jsonify({"id": entry.id, "overtime_validated": entry.overtime_validated})


@app.get("/api/audit-logs")
@api_auth_required(admin_only=True)
def api_audit_logs():
    logs = latest_audit_logs(limit=100)
    return jsonify(
        [
            {
                "id": log.id,
                "actor_user_id": log.actor_user_id,
                "target_user_id": log.target_user_id,
                "time_entry_id": log.time_entry_id,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "action": log.action,
                "reason": log.reason,
                "details": log.details,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]
    )


@app.get("/api/reports/monthly")
@api_auth_required()
def api_monthly_report():
    api_user = request.api_user
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    target_user_id = api_user.id

    if api_user.is_admin and request.args.get("user_id"):
        try:
            requested_user_id = int(request.args["user_id"])
        except ValueError:
            return jsonify({"error": "user_id debe ser numerico y pertenecer a un empleado"}), 400

        report_user_ids = {user.id for user in report_employee_users()}
        if requested_user_id not in report_user_ids:
            return jsonify({"error": "user_id no corresponde a un empleado"}), 400

        target_user_id = requested_user_id

    try:
        _, _, entries = monthly_entries(month, target_user_id)
    except ValueError:
        return jsonify({"error": "month debe tener formato YYYY-MM"}), 400

    payload_entries = [serialize_entry(item) for item in entries]
    total = round(sum(item["worked_hours"] for item in payload_entries), 2)

    return jsonify({"user_id": target_user_id, "month": month, "total_hours": total, "entries": payload_entries})


@app.get("/api/reports/monthly/excel")
@api_auth_required()
def api_report_excel():
    return report_excel()


@app.get("/api/reports/monthly/pdf")
@api_auth_required()
def api_report_pdf():
    return report_pdf()


# ===== RECUPERACIÓN DE CONTRASEÑA PARA ADMINISTRADORES =====

def send_reset_code_email(to_email, code):
    """Envía un código de recuperación de contraseña al correo del administrador."""
    subject = "Código de recuperación de contraseña"
    body = f"Tu código de recuperación es: {code}\n\nEste código es válido por 10 minutos."
    msg = Message(subject=subject, recipients=[to_email], body=body)
    mail.send(msg)


@app.route("/admin-password-reset-request", methods=["GET", "POST"])
def admin_password_reset_request():
    """Solicita usuario y correo para enviar código de recuperación."""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        
        if not username or not email:
            flash("Completa usuario y correo electrónico", "admin_forgot")
            return render_template("admin_login.html", mode="forgot-request")

        user = User.query.filter_by(username=username, email=email, rol="admin", active=True).first()
        if not user:
            flash("Usuario o correo no válido", "admin_forgot")
            return render_template("admin_login.html", mode="forgot-request")

        # Generar código único de 6 dígitos
        code = ''.join(random.choices(string.digits, k=6))
        expires_at = datetime.utcnow() + timedelta(minutes=10)

        # Guardar código en la base de datos
        reset_code = PasswordResetCode(user_id=user.id, code=code, expires_at=expires_at)
        db.session.add(reset_code)
        db.session.commit()

        # Enviar el correo con el código
        try:
            send_reset_code_email(user.email, code)
            flash("Código enviado al correo electrónico si los datos son correctos", "admin_forgot")
        except Exception as e:
            flash("No se pudo enviar el correo. Contacta al administrador.", "admin_forgot")
        
        return render_template("admin_login.html", mode="forgot-verify", username=username)

    return render_template("admin_login.html", mode="forgot-request")


@app.route("/admin-password-reset-verify", methods=["POST"])
def admin_password_reset_verify():
    """Verifica el código y cambia la contraseña del administrador."""
    username = request.form.get("username", "").strip()
    code = request.form.get("code", "").strip().replace(" ", "")
    new_password = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    if not username or not code or not new_password or not confirm:
        flash("Completa todos los campos", "admin_forgot")
        return render_template("admin_login.html", mode="forgot-verify", username=username)

    if new_password != confirm:
        flash("Las contraseñas no coinciden", "admin_forgot")
        return render_template("admin_login.html", mode="forgot-verify", username=username)

    password_error = validate_password_strength(new_password)
    if password_error:
        flash(password_error, "admin_forgot")
        return render_template("admin_login.html", mode="forgot-verify", username=username)

    user = User.query.filter_by(username=username, rol="admin", active=True).first()
    if not user:
        flash("Usuario no válido", "admin_forgot")
        return render_template("admin_login.html", mode="forgot-verify", username=username)

    # Buscar código válido y no usado
    reset_code = PasswordResetCode.query.filter(
        and_(
            PasswordResetCode.user_id == user.id,
            PasswordResetCode.code == code,
            PasswordResetCode.used == False,
            PasswordResetCode.expires_at >= datetime.utcnow()
        )
    ).order_by(PasswordResetCode.created_at.desc()).first()

    if not reset_code:
        flash("Código inválido o expirado", "admin_forgot")
        return render_template("admin_login.html", mode="forgot-verify", username=username)

    # Marcar código como usado y actualizar contraseña
    reset_code.used = True
    user.password_hash = generate_password_hash(new_password)
    db.session.commit()

    create_audit_log(
        actor_user_id=user.id,
        target_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        action="password_reset",
        reason="Recuperación de contraseña admin con código",
        details="Cambio de contraseña de administrador con código de verificación",
    )

    flash("Contraseña restablecida con éxito. Ya puedes iniciar sesión.", "admin_login")
    return render_template("admin_login.html", mode="login")


with app.app_context():
    db.create_all()
    ensure_users_password_column_compatibility()
    ensure_users_profile_columns()
    ensure_time_entries_geolocation_columns()
    ensure_default_admin()


if __name__ == "__main__":
    app.run(debug=False)
