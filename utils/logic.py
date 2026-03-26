from flask_login import current_user

def request_user():
    from flask import request
    if hasattr(request, "api_user"):
        return request.api_user
    return current_user
def latest_audit_logs(limit=30):
    from models.models import AuditLog
    return AuditLog.query.order_by(AuditLog.created_at.desc()).limit(limit).all()
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
from flask import request
from models.models import User, TimeEntry

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

    if hasattr(active_user, 'is_admin') and active_user.is_admin:
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
    selected_user = None if include_all else User.query.get(selected_user_id)

    return active_user, selected_user_id, selected_user, entries, change_reasons, include_all
def latest_change_reasons_for_entries(entries):
    entry_ids = [item.id for item in entries]
    if not entry_ids:
        return {}

    from models.models import AuditLog
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
def change_reason_required(reason):
    reason = (reason or "").strip()
    if not reason:
        return "Debes indicar el motivo del cambio"
    return None
from datetime import date

def can_edit_entry(user, entry):
    if hasattr(user, 'is_admin') and user.is_admin:
        return True
    if hasattr(entry, 'overtime_validated') and entry.overtime_validated:
        return False
    return hasattr(entry, 'user_id') and hasattr(user, 'id') and entry.user_id == user.id and hasattr(entry, 'work_date') and entry.work_date == date.today()
from models.models import AuditLog, db

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
def parse_coordinate(value):
    if value in (None, ""):
        return None
    return round(float(value), 7)
def parse_iso_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()

def parse_hhmm(value):
    return datetime.strptime(value, "%H:%M").time()
from models.models import TimeEntry

def get_yearly_overtime(user_id, year):
    from datetime import date
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    entries = TimeEntry.query.filter(
        TimeEntry.user_id == user_id,
        TimeEntry.work_date >= year_start,
        TimeEntry.work_date <= year_end,
    ).all()
    return round(sum(overtime_hours(item) for item in entries), 2)
from datetime import datetime, timedelta
import re

def combine_dt(day_value, time_value):
    return datetime.combine(day_value, time_value)

def interval_hours(entry, start_attr, end_attr, round_result=True):
    start = getattr(entry, start_attr, None)
    end = getattr(entry, end_attr, None)
    if start and end:
        delta = combine_dt(entry.work_date, end) - combine_dt(entry.work_date, start)
        hours = delta.total_seconds() / 3600
        if round_result:
            return max(0.0, round(hours, 2))
        return max(0.0, hours)
    return 0.0

def meal_hours(entry):
    return interval_hours(entry, 'meal_start', 'meal_end', round_result=False)

def pause_hours(entry):
    return interval_hours(entry, 'pause_start', 'pause_end')

def worked_hours(entry):
    total = combine_dt(entry.work_date, entry.check_out) - combine_dt(entry.work_date, entry.check_in)
    worked = total.total_seconds() / 3600 - meal_hours(entry) - pause_hours(entry)
    return max(0.0, round(worked, 2))

def overtime_hours(entry):
    return interval_hours(entry, 'overtime_start', 'overtime_end')

def week_bounds(day_value):
    week_start = day_value - timedelta(days=day_value.weekday())
    return week_start, week_start + timedelta(days=6)

def weekly_hours_for_user(TimeEntry, user_id, day_value):
    start, end = week_bounds(day_value)
    entries = TimeEntry.query.filter(
        TimeEntry.user_id == user_id,
        TimeEntry.work_date >= start,
        TimeEntry.work_date <= end,
    ).all()
    return round(sum(worked_hours(item) for item in entries), 2)

def weekly_breakdown_for_user(TimeEntry, user_id, day_value, MAX_WEEKLY_HOURS):
    start, end = week_bounds(day_value)
    entries = TimeEntry.query.filter(
        TimeEntry.user_id == user_id,
        TimeEntry.work_date >= start,
        TimeEntry.work_date <= end,
    ).all()
    def sum_hours(func):
        return round(sum(func(item) for item in entries), 2)
    effective_hours = sum_hours(worked_hours)
    meal_total = sum_hours(meal_hours)
    pause_total = sum_hours(pause_hours)
    overtime_total = sum_hours(overtime_hours)
    over_limit_hours = round(max(0.0, effective_hours - MAX_WEEKLY_HOURS), 2)
    year = start.year
    return {
        'effective_hours': effective_hours,
        'meal_total': meal_total,
        'pause_total': pause_total,
        'overtime_total': overtime_total,
        'over_limit_hours': over_limit_hours,
        'year': year
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
