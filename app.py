import io
import os
import re
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
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from openpyxl import Workbook
from openpyxl.styles import Alignment
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "cambia_esta_clave_en_produccion")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL",
    "sqlite:///horarios.db",
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

MAX_WEEKLY_HOURS = 40.0
TOKEN_TTL_SECONDS = 60 * 60 * 12

db = SQLAlchemy(app)
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


def report_context(month):
    active_user = request_user()
    selected_user_id = active_user.id
    include_all = False

    if active_user.is_admin:
        requested_user = (request.args.get("user_id") or "all").strip().lower()
        include_all = requested_user in {"", "all"}
        if not include_all:
            selected_user_id = int(requested_user)

    if include_all:
        month_start = datetime.strptime(month + "-01", "%Y-%m-%d").date()
        month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        entries = (
            TimeEntry.query.join(TimeEntry.user)
            .filter(
                TimeEntry.work_date >= month_start,
                TimeEntry.work_date < month_end,
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
        reason_text = (log.reason or "-").strip() or "-"
        change_time = log.created_at.strftime("%H:%M") if log.created_at else "--:--"
        reasons_by_entry.setdefault(log.time_entry_id, []).append(f"{change_time} (h) - {reason_text}")

    return {
        entry_id: "\n".join(lines) if lines else "-"
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
        rol = "employee"

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

    users = User.query.filter_by(rol="employee").order_by(User.username.asc()).all()
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
    
    try:
        month_start = datetime.strptime(f"{month}-01", "%Y-%m-%d").date()
    except ValueError:
        month = date.today().strftime("%Y-%m")
        month_start = datetime.strptime(f"{month}-01", "%Y-%m-%d").date()

    if month_start.month == 12:
        month_end_exclusive = month_start.replace(year=month_start.year + 1, month=1, day=1)
    else:
        month_end_exclusive = month_start.replace(month=month_start.month + 1, day=1)

    entries = (
        TimeEntry.query.join(TimeEntry.user)
        .filter(
            TimeEntry.work_date >= month_start,
            TimeEntry.work_date < month_end_exclusive,
        )
        .order_by(TimeEntry.work_date.desc(), User.username.asc())
        .all()
    )

    change_reasons = latest_change_reasons_for_entries(entries)

    return render_template(
        "validate_hours.html",
        entries=entries,
        month=month,
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

    users = User.query.order_by(User.username.asc()).all() if active_user.is_admin else []

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
    active_user, selected_user_id, _selected_user, entries, change_reasons, include_all = report_context(month)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Control horario"
    headers = [
        "Fecha",
        "Empleado",
        "Entrada",
        "Salida",
        "Horas efectivas",
        "Horas comida",
        "Horas pausa",
        "Horas extra",
        "Estado",
        "Motivos del cambio",
    ]
    sheet.append(headers)

    for item in entries:
        full_name = f"{(item.user.first_name or '').strip()} {(item.user.last_name or '').strip()}".strip()
        row = [
            item.work_date.isoformat(),
            full_name or item.user.username,
            item.check_in.strftime("%H:%M"),
            item.check_out.strftime("%H:%M"),
            worked_hours(item),
            meal_hours(item),
            pause_hours(item),
            overtime_hours(item),
            "VALIDADO" if item.overtime_validated else "PENDIENTE",
            change_reasons.get(item.id, "-"),
        ]
        sheet.append(row)

    cause_col = headers.index("Motivos del cambio") + 1
    for row_idx in range(2, len(entries) + 2):
        sheet.cell(row=row_idx, column=cause_col).alignment = Alignment(wrap_text=True, vertical="top")

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)

    target_label = "todos" if include_all else str(selected_user_id)
    filename = f"reporte_{target_label}_{month}.xlsx"
    return send_file(output, as_attachment=True, download_name=filename, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/report/pdf")
@login_required
def report_pdf():
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    active_user, selected_user_id, selected_user, entries, change_reasons, include_all = report_context(month)
    company_profile = get_company_profile()

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 44

    logo_path = os.path.join(app.static_folder, "Control_Horario_v.3.png")
    if os.path.exists(logo_path):
        pdf.drawImage(logo_path, width - 150, y - 28, width=100, height=28, preserveAspectRatio=True, mask='auto')

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(40, y, company_profile.company_name or "Superpekes")
    y -= 12
    pdf.setFont("Helvetica", 9)
    city_country = ", ".join([part for part in [company_profile.city, company_profile.country] if part])
    line2_parts = [
        f"CIF: {company_profile.tax_id}" if company_profile.tax_id else "",
        company_profile.fiscal_address or "",
        city_country,
        f"Tel: {company_profile.phone}" if company_profile.phone else "",
    ]
    line2_text = " | ".join([part for part in line2_parts if part])
    if line2_text:
        pdf.drawString(40, y, line2_text[:95])
        y -= 14
    else:
        y -= 6

    pdf.line(40, y, width - 40, y)
    y -= 14

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, "Informe oficial de control horario")
    y -= 20

    pdf.setFont("Helvetica", 10)
    selected_label = "Todos"
    if selected_user:
        full_name = f"{(selected_user.first_name or '').strip()} {(selected_user.last_name or '').strip()}".strip()
        selected_label = full_name or selected_user.username
    pdf.drawString(40, y, f"Empleado: {selected_label}")
    y -= 15
    pdf.drawString(40, y, f"Mes: {month}")
    y -= 25

    def draw_pdf_table_header(current_y):
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(40, current_y, "Fecha")
        pdf.drawString(95, current_y, "Empleado")
        pdf.drawString(165, current_y, "Entrada")
        pdf.drawString(210, current_y, "Salida")
        pdf.drawString(250, current_y, "Efect.")
        pdf.drawString(290, current_y, "Comida")
        pdf.drawString(336, current_y, "Pausa")
        pdf.drawString(374, current_y, "Extra")
        pdf.drawString(408, current_y, "Estado")
        pdf.drawString(450, current_y, "Motivos")
        return current_y - 14

    y = draw_pdf_table_header(y)

    pdf.setFont("Helvetica", 9)
    for item in entries:
        reason_lines = (change_reasons.get(item.id, "-") or "-").splitlines()
        if not reason_lines:
            reason_lines = ["-"]

        needed_height = max(13, len(reason_lines) * 10)
        if y - needed_height < 60:
            pdf.showPage()
            y = height - 50
            y = draw_pdf_table_header(y)
            pdf.setFont("Helvetica", 9)

        pdf.drawString(40, y, item.work_date.isoformat())
        full_name = f"{(item.user.first_name or '').strip()} {(item.user.last_name or '').strip()}".strip()
        pdf.drawString(95, y, (full_name or item.user.username or "-")[:12])
        pdf.drawString(165, y, item.check_in.strftime("%H:%M"))
        pdf.drawString(210, y, item.check_out.strftime("%H:%M"))
        pdf.drawString(250, y, f"{worked_hours(item):.2f}")
        pdf.drawString(290, y, f"{meal_hours(item):.2f}")
        pdf.drawString(336, y, f"{pause_hours(item):.2f}")
        pdf.drawString(374, y, f"{overtime_hours(item):.2f}")
        pdf.drawString(408, y, "VALIDADO" if item.overtime_validated else "PENDIENTE")

        line_y = y
        for line in reason_lines:
            pdf.drawString(450, line_y, line[:24])
            line_y -= 10
        y -= needed_height

    pdf.save()
    buffer.seek(0)
    target_label = "todos" if include_all else str(selected_user_id)
    filename = f"reporte_{target_label}_{month}.pdf"
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
        target_user_id = int(request.args["user_id"])

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


with app.app_context():
    db.create_all()
    ensure_users_password_column_compatibility()
    ensure_users_profile_columns()
    ensure_time_entries_geolocation_columns()
    ensure_default_admin()


if __name__ == "__main__":
    app.run(debug=False)
