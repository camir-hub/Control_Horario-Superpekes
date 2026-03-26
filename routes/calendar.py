# --- Rutas de calendario y jornada ---
from flask import request, redirect, url_for, render_template, flash
from flask_login import login_required, current_user
from datetime import date, timedelta
from models.models import db, User, TimeEntry
from utils.logic import (
	parse_iso_date, meal_hours, pause_hours, worked_hours, overtime_hours,
	can_edit_entry, validate_entry_payload, weekly_breakdown_for_user,
	MAX_WEEKLY_HOURS, get_yearly_overtime, weekly_hours_for_user, create_audit_log,
	change_reason_required, serialize_entry
)
from .calendar import bp_calendar

@bp_calendar.route("/calendar")
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


@bp_calendar.route("/add_entry", methods=["POST"])
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


@bp_calendar.route("/entries/<int:entry_id>/update", methods=["POST"])
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
		details=f"Antes={serialize_entry(entry)}; Despues={serialize_entry(entry)}",
	)
	db.session.commit()
	flash("Registro actualizado. Las horas extra quedan pendientes de nueva validación.")
	return redirect(url_for("calendar", user_id=entry.user_id, day=entry.work_date.isoformat()))
from flask import Blueprint

bp_calendar = Blueprint('calendar', __name__)

# Aquí se migrarán las rutas relacionadas con el calendario y la gestión de entradas de jornada.
