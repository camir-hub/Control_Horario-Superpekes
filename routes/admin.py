from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, make_response, send_file, current_app as app
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from datetime import date, datetime, timedelta
import io, os
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, GradientFill, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.drawing.image import Image as XlImage
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from models.models import User, TimeEntry, CompanyProfile
from utils.logic import (
	validate_password_strength, change_reason_required, create_audit_log, worked_hours, meal_hours, pause_hours, overtime_hours, latest_change_reasons_for_entries, report_context, report_employee_users
)

bp_admin = Blueprint('admin', __name__)

@bp_admin.route("/admin/users/<int:user_id>/reset-password", methods=["POST"])
@login_required
def reset_user_password(user_id):
	if not current_user.is_admin:
		flash("Acceso denegado")
		return redirect(url_for("calendar"))
	user = User.query.get(user_id)
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
	from app import db
	db.session.commit()
	flash("Contraseña reiniciada correctamente")
	return redirect(url_for("admin_users"))

@bp_admin.route("/admin", methods=["GET"])
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

@bp_admin.route("/admin/company", methods=["GET", "POST"])
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
		from app import db
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

@bp_admin.route("/admin/users", methods=["GET", "POST"])
@login_required
def admin_users():
	if not current_user.is_admin:
		flash("Acceso denegado")
		return redirect(url_for("calendar"))
	from app import db
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

@bp_admin.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@login_required
def toggle_user(user_id):
	if not current_user.is_admin:
		flash("Acceso denegado")
		return redirect(url_for("calendar"))
	from app import db
	user = User.query.get(user_id)
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

@bp_admin.route("/admin/validate-hours", methods=["GET"])
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

@bp_admin.route("/admin/toggle-validation/<int:entry_id>", methods=["POST"])
@login_required
def toggle_validation(entry_id):
	if not current_user.is_admin:
		return jsonify({"error": "Acceso denegado"}), 403
	from app import db
	entry = TimeEntry.query.get(entry_id)
	if not entry:
		return jsonify({"error": "Registro no encontrado"}), 404
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

@bp_admin.route("/report")
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

@bp_admin.route("/report/excel")
@login_required
def report_excel():
	# ...código migrado igual que en app.py...
	pass  # Implementar igual que en app.py

@bp_admin.route("/report/pdf")
@login_required
def report_pdf():
	# ...código migrado igual que en app.py...
	pass  # Implementar igual que en app.py
