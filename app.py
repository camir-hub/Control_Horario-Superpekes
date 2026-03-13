import io
import os
import re
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (
    Flask,
    flash,
    jsonify,
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
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from openpyxl import Workbook
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
    role = db.Column(db.String(20), nullable=False, default="employee")
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def is_active(self):
        return self.active

    @property
    def is_admin(self):
        return self.role == "admin"


class TimeEntry(db.Model):
    __tablename__ = "time_entries"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    work_date = db.Column(db.Date, nullable=False)
    check_in = db.Column(db.Time, nullable=False)
    meal_start = db.Column(db.Time, nullable=True)
    meal_end = db.Column(db.Time, nullable=True)
    check_out = db.Column(db.Time, nullable=False)
    comments = db.Column(db.Text, nullable=True)
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


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def parse_iso_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def parse_hhmm(value):
    return datetime.strptime(value, "%H:%M").time()


def combine_dt(day_value, time_value):
    return datetime.combine(day_value, time_value)


def meal_hours(entry):
    if entry.meal_start and entry.meal_end:
        delta = combine_dt(entry.work_date, entry.meal_end) - combine_dt(entry.work_date, entry.meal_start)
        return max(0.0, delta.total_seconds() / 3600)
    return 0.0


def worked_hours(entry):
    total = combine_dt(entry.work_date, entry.check_out) - combine_dt(entry.work_date, entry.check_in)
    worked = total.total_seconds() / 3600 - meal_hours(entry)
    return max(0.0, round(worked, 2))


def overtime_hours(entry):
    return round(max(0.0, worked_hours(entry) - 8.0), 2)


def week_bounds(day_value):
    week_start = day_value - timedelta(days=day_value.weekday())
    return week_start, week_start + timedelta(days=6)


def week_days(day_value):
    start, _ = week_bounds(day_value)
    return [start + timedelta(days=i) for i in range(7)]


def weekly_hours_for_user(user_id, day_value):
    start, end = week_bounds(day_value)
    entries = TimeEntry.query.filter(
        TimeEntry.user_id == user_id,
        TimeEntry.work_date >= start,
        TimeEntry.work_date <= end,
    ).all()
    return round(sum(worked_hours(item) for item in entries), 2)


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
    return entry.user_id == user.id and entry.work_date == date.today()


def change_reason_required(reason):
    reason = (reason or "").strip()
    if not reason:
        return "Debes indicar la causa del cambio"
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


def serialize_entry(entry):
    return {
        "id": entry.id,
        "user_id": entry.user_id,
        "username": entry.user.username if entry.user else None,
        "work_date": entry.work_date.isoformat(),
        "check_in": entry.check_in.strftime("%H:%M"),
        "meal_start": entry.meal_start.strftime("%H:%M") if entry.meal_start else None,
        "meal_end": entry.meal_end.strftime("%H:%M") if entry.meal_end else None,
        "check_out": entry.check_out.strftime("%H:%M"),
        "comments": entry.comments or "",
        "meal_hours": meal_hours(entry),
        "worked_hours": worked_hours(entry),
        "overtime_hours": overtime_hours(entry),
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
    except ValueError:
        return "Formato de fecha u hora invalido", None

    if combine_dt(work_date, check_out) <= combine_dt(work_date, check_in):
        return "La hora de salida debe ser mayor que la de entrada", None

    if bool(meal_start) != bool(meal_end):
        return "Debes informar inicio y fin de comida", None

    if meal_start and meal_end:
        if combine_dt(work_date, meal_end) <= combine_dt(work_date, meal_start):
            return "El fin de comida debe ser mayor que el inicio de comida", None
        if combine_dt(work_date, meal_start) < combine_dt(work_date, check_in) or combine_dt(work_date, meal_end) > combine_dt(work_date, check_out):
            return "La comida debe estar dentro de la jornada", None

    return None, {
        "work_date": work_date,
        "check_in": check_in,
        "meal_start": meal_start,
        "meal_end": meal_end,
        "check_out": check_out,
        "comments": (payload.get("comments") or "").strip(),
    }


def create_api_token(user):
    return serializer.dumps({"user_id": user.id, "role": user.role})


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


def ensure_default_admin():
    admin = User.query.filter_by(username="admin").first()
    if admin is None:
        admin = User(
            username="admin",
            password_hash=generate_password_hash(os.getenv("DEFAULT_ADMIN_PASSWORD", "Admin123!")),
            role="admin",
            active=True,
        )
        db.session.add(admin)
        db.session.commit()


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        if user and user.active and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("calendar"))

        flash("Credenciales invalidas o usuario inactivo")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/")
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
        users = User.query.order_by(User.username.asc()).all()
        if request.args.get("user_id"):
            try:
                selected_user_id = int(request.args["user_id"])
            except ValueError:
                flash("Empleado invalido")

    days = week_days(day_value)
    selected_user = db.session.get(User, selected_user_id)

    entries = (
        TimeEntry.query.filter(
            TimeEntry.user_id == selected_user_id,
            TimeEntry.work_date >= days[0],
            TimeEntry.work_date <= days[-1],
        )
        .order_by(TimeEntry.work_date.asc())
        .all()
    )

    entries_by_day = {day_item: [] for day_item in days}
    for item in entries:
        entries_by_day[item.work_date].append(item)

    selected_entry = entries_by_day[day_value][0] if entries_by_day[day_value] else None

    daily_totals = {day_item: round(sum(worked_hours(item) for item in entries_by_day[day_item]), 2) for day_item in days}
    weekly_total = round(sum(daily_totals.values()), 2)
    allow_entry_edit = bool(selected_entry and can_edit_entry(current_user, selected_entry))

    return render_template(
        "calendar.html",
        days=days,
        selected_day=day_value,
        selected_user=selected_user,
        users=users,
        entries_by_day=entries_by_day,
        selected_entry=selected_entry,
        allow_entry_edit=allow_entry_edit,
        daily_totals=daily_totals,
        weekly_total=weekly_total,
        max_weekly_hours=MAX_WEEKLY_HOURS,
        today=date.today(),
        worked_hours=worked_hours,
        overtime_hours=overtime_hours,
        meal_hours=meal_hours,
    )


@app.get("/calendar/day-data")
@login_required
def calendar_day_data():
    day_raw = request.args.get("day")
    if not day_raw:
        return jsonify({"error": "Debe indicar day con formato YYYY-MM-DD"}), 400

    try:
        day_value = parse_iso_date(day_raw)
    except ValueError:
        return jsonify({"error": "Fecha inválida"}), 400

    selected_user_id = current_user.id
    if current_user.is_admin and request.args.get("user_id"):
        try:
            selected_user_id = int(request.args["user_id"])
        except ValueError:
            return jsonify({"error": "Empleado inválido"}), 400

    entries = (
        TimeEntry.query.filter(
            TimeEntry.user_id == selected_user_id,
            TimeEntry.work_date == day_value,
        )
        .order_by(TimeEntry.created_at.asc())
        .all()
    )

    entry = entries[0] if entries else None
    return jsonify(
        {
            "day": day_value.isoformat(),
            "label": day_value.strftime("%A %d/%m/%Y"),
            "user_id": selected_user_id,
            "has_entry": bool(entry),
            "entry": serialize_entry(entry) if entry else None,
        }
    )


@app.route("/add_entry", methods=["POST"])
@login_required
def add_entry():
    payload = {
        "work_date": request.form.get("work_date"),
        "check_in": request.form.get("check_in"),
        "meal_start": request.form.get("meal_start"),
        "meal_end": request.form.get("meal_end"),
        "check_out": request.form.get("check_out"),
        "comments": request.form.get("comments"),
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
        check_out=normalized["check_out"],
        comments=normalized["comments"],
    )

    projected = weekly_hours_for_user(target_user_id, normalized["work_date"]) + worked_hours(candidate)
    if projected > MAX_WEEKLY_HOURS:
        flash("No puedes superar 40 horas semanales")
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
        "check_out": request.form.get("check_out"),
        "comments": request.form.get("comments"),
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
        check_out=normalized["check_out"],
        comments=normalized["comments"],
    )
    projected = original_week_hours + worked_hours(updated_candidate)
    if projected > MAX_WEEKLY_HOURS:
        flash("La modificación supera 40 horas semanales")
        return redirect(url_for("calendar", user_id=entry.user_id, day=entry.work_date.isoformat()))

    previous = serialize_entry(entry)
    entry.check_in = normalized["check_in"]
    entry.meal_start = normalized["meal_start"]
    entry.meal_end = normalized["meal_end"]
    entry.check_out = normalized["check_out"]
    entry.comments = normalized["comments"]
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
    flash("Registro actualizado con traza de auditoría")
    return redirect(url_for("calendar", user_id=entry.user_id, day=entry.work_date.isoformat()))


@app.route("/account/password", methods=["POST"])
@login_required
def change_password():
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")
    reason = request.form.get("change_reason", "Actualización de contraseña")

    if not check_password_hash(current_user.password_hash, current_password):
        flash("La contraseña actual no es correcta")
        return redirect(url_for("calendar"))

    if new_password != confirm_password:
        flash("La nueva contraseña y su confirmación no coinciden")
        return redirect(url_for("calendar"))

    password_error = validate_password_strength(new_password)
    if password_error:
        flash(password_error)
        return redirect(url_for("calendar"))

    reason_error = change_reason_required(reason)
    if reason_error:
        flash(reason_error)
        return redirect(url_for("calendar"))

    current_user.password_hash = generate_password_hash(new_password)
    create_audit_log(
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        entity_type="user",
        entity_id=current_user.id,
        action="password_change",
        reason=reason,
        details="Contraseña actualizada por el propio usuario",
    )
    db.session.commit()
    flash("Contraseña actualizada")
    return redirect(url_for("calendar"))


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


@app.route("/admin/users", methods=["GET", "POST"])
@login_required
def admin_users():
    if not current_user.is_admin:
        flash("Acceso denegado")
        return redirect(url_for("calendar"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "employee")

        if not username or not password:
            flash("Usuario y password son obligatorios")
            return redirect(url_for("admin_users"))

        if role not in {"employee", "admin"}:
            flash("Rol invalido")
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
            role=role,
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
            details=f"Usuario {username} con rol {role}",
        )
        db.session.commit()
        flash("Usuario creado")
        return redirect(url_for("admin_users"))

    users = User.query.order_by(User.username.asc()).all()
    weekly_totals = {user.id: weekly_hours_for_user(user.id, date.today()) for user in users}
    return render_template("admin_users.html", users=users, audit_logs=latest_audit_logs(), weekly_totals=weekly_totals)


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


@app.route("/admin/validate/<int:entry_id>", methods=["POST"])
@login_required
def validate_overtime(entry_id):
    if not current_user.is_admin:
        flash("Acceso denegado")
        return redirect(url_for("calendar"))

    entry = db.session.get(TimeEntry, entry_id)
    if not entry:
        flash("Registro no encontrado")
        return redirect(url_for("calendar"))

    entry.overtime_validated = True
    create_audit_log(
        actor_user_id=current_user.id,
        target_user_id=entry.user_id,
        time_entry_id=entry.id,
        entity_type="time_entry",
        entity_id=entry.id,
        action="validate_overtime",
        reason="Validación administrativa de horas extra",
        details=f"Horas extra validadas: {overtime_hours(entry):.2f}",
    )
    db.session.commit()
    flash("Horas validadas")

    return redirect(url_for("calendar", user_id=entry.user_id, day=entry.work_date.isoformat()))


@app.route("/report")
@login_required
def report():
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    active_user = request_user()
    selected_user_id = active_user.id

    if active_user.is_admin and request.args.get("user_id"):
        selected_user_id = int(request.args["user_id"])

    _, _, entries = monthly_entries(month, selected_user_id)

    users = User.query.order_by(User.username.asc()).all() if active_user.is_admin else []
    selected_user = db.session.get(User, selected_user_id)

    total = round(sum(worked_hours(item) for item in entries), 2)

    return render_template(
        "report.html",
        month=month,
        users=users,
        selected_user=selected_user,
        entries=entries,
        total=total,
        worked_hours=worked_hours,
        overtime_hours=overtime_hours,
        meal_hours=meal_hours,
    )


@app.route("/report/excel")
@login_required
def report_excel():
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    active_user = request_user()
    selected_user_id = active_user.id

    if active_user.is_admin and request.args.get("user_id"):
        selected_user_id = int(request.args["user_id"])

    _, _, entries = monthly_entries(month, selected_user_id)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Control horario"
    headers = [
        "Fecha",
        "Entrada",
        "Inicio comida",
        "Fin comida",
        "Salida",
        "Horas comida",
        "Horas netas",
        "Horas extra",
        "Validadas",
        "Comentarios",
    ]
    sheet.append(headers)

    for item in entries:
        sheet.append(
            [
                item.work_date.isoformat(),
                item.check_in.strftime("%H:%M"),
                item.meal_start.strftime("%H:%M") if item.meal_start else "",
                item.meal_end.strftime("%H:%M") if item.meal_end else "",
                item.check_out.strftime("%H:%M"),
                meal_hours(item),
                worked_hours(item),
                overtime_hours(item),
                "SI" if item.overtime_validated else "NO",
                item.comments or "",
            ]
        )

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)

    filename = f"reporte_{selected_user_id}_{month}.xlsx"
    return send_file(output, as_attachment=True, download_name=filename, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/report/pdf")
@login_required
def report_pdf():
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    active_user = request_user()
    selected_user_id = active_user.id

    if active_user.is_admin and request.args.get("user_id"):
        selected_user_id = int(request.args["user_id"])

    _, _, entries = monthly_entries(month, selected_user_id)

    selected_user = db.session.get(User, selected_user_id)

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 50
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, "Informe oficial de control horario")
    y -= 20

    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, y, f"Empleado: {selected_user.username if selected_user else 'N/D'}")
    y -= 15
    pdf.drawString(40, y, f"Mes: {month}")
    y -= 25

    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(40, y, "Fecha")
    pdf.drawString(105, y, "Entrada")
    pdf.drawString(160, y, "Comida")
    pdf.drawString(250, y, "Salida")
    pdf.drawString(305, y, "Neto")
    pdf.drawString(350, y, "Extra")
    pdf.drawString(395, y, "Validada")
    y -= 14

    pdf.setFont("Helvetica", 9)
    for item in entries:
        if y < 60:
            pdf.showPage()
            y = height - 50
            pdf.setFont("Helvetica", 9)

        meal_text = "-"
        if item.meal_start and item.meal_end:
            meal_text = f"{item.meal_start.strftime('%H:%M')}-{item.meal_end.strftime('%H:%M')}"

        pdf.drawString(40, y, item.work_date.isoformat())
        pdf.drawString(105, y, item.check_in.strftime("%H:%M"))
        pdf.drawString(160, y, meal_text)
        pdf.drawString(250, y, item.check_out.strftime("%H:%M"))
        pdf.drawString(305, y, f"{worked_hours(item):.2f}")
        pdf.drawString(350, y, f"{overtime_hours(item):.2f}")
        pdf.drawString(395, y, "SI" if item.overtime_validated else "NO")
        y -= 13

    pdf.save()
    buffer.seek(0)
    filename = f"reporte_{selected_user_id}_{month}.pdf"
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
                "role": user.role,
            },
        }
    )


@app.get("/api/me")
@api_auth_required()
def api_me():
    user = request.api_user
    return jsonify({"id": user.id, "username": user.username, "role": user.role, "active": user.active})


@app.get("/api/users")
@api_auth_required(admin_only=True)
def api_users_list():
    users = User.query.order_by(User.username.asc()).all()
    return jsonify(
        [
            {
                "id": u.id,
                "username": u.username,
                "role": u.role,
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
    role = (data.get("role") or "employee").strip()

    if not username or not password:
        return jsonify({"error": "username y password son obligatorios"}), 400
    if role not in {"employee", "admin"}:
        return jsonify({"error": "role debe ser employee o admin"}), 400
    password_error = validate_password_strength(password)
    if password_error:
        return jsonify({"error": password_error}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "El usuario ya existe"}), 409

    user = User(username=username, password_hash=generate_password_hash(password), role=role, active=True)
    db.session.add(user)
    db.session.flush()
    create_audit_log(
        actor_user_id=request.api_user.id,
        target_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        action="create",
        reason="Alta de usuario desde API",
        details=f"Usuario {username} con rol {role}",
    )
    db.session.commit()

    return jsonify({"id": user.id, "username": user.username, "role": user.role, "active": user.active}), 201


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
    )

    projected = weekly_hours_for_user(target_user_id, normalized["work_date"]) + worked_hours(candidate)
    if projected > MAX_WEEKLY_HOURS:
        return jsonify({"error": "No se puede superar 40 horas semanales"}), 422

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
    )
    projected = original_week_hours + worked_hours(updated_candidate)
    if projected > MAX_WEEKLY_HOURS:
        return jsonify({"error": "La modificación supera 40 horas semanales"}), 422

    previous = serialize_entry(entry)
    entry.check_in = normalized["check_in"]
    entry.meal_start = normalized["meal_start"]
    entry.meal_end = normalized["meal_end"]
    entry.check_out = normalized["check_out"]
    entry.comments = normalized["comments"]
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
    return jsonify(serialize_entry(entry))


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
        reason="Validación administrativa desde API",
        details=f"Horas extra validadas: {overtime_hours(entry):.2f}",
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
    ensure_default_admin()


if __name__ == "__main__":
    app.run(debug=False)
