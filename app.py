
from flask import Flask
from flask import Blueprint
from flask_login import login_required
from functools import wraps
import os
import re
import io
import random
import string
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.drawing.image import Image as XlImage
from openpyxl.styles import GradientFill
from reportlab.lib.pagesizes import A4
from routes.admin import bp_admin
from models.models import db, User, TimeEntry, CompanyProfile
from sqlalchemy import inspect, text
from werkzeug.security import generate_password_hash

# Instancia de la app Flask
app = Flask(__name__)

# Configuración básica
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///control_horario.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'super-secret-key')

# Inicializar SQLAlchemy con la app
db.init_app(app)

# Registrar blueprint admin
app.register_blueprint(bp_admin)

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
        pass

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
        actor_user_id=current_user.id,
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
        yearly_overtime=weekly_stats.get("yearly_overtime", 0),
        yearly_overtime_limit=weekly_stats.get("yearly_overtime_limit", 80),
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

    # Bloqueo de horas extra anuales
    year = normalized["work_date"].year
    yearly_overtime = get_yearly_overtime(target_user_id, year)
    overtime_start = normalized["overtime_start"]
    overtime_end = normalized["overtime_end"]
    if overtime_start and overtime_end and yearly_overtime >= 80:
        flash("No puedes registrar más de 80 horas extra en el año.", "error")
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
