# Instancia global de SQLAlchemy, inicializada en app.py
from flask_sqlalchemy import SQLAlchemy
db = SQLAlchemy()
from flask_login import UserMixin
from datetime import datetime

# La instancia db será importada desde app.py

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

class PasswordResetCode(db.Model):
    __tablename__ = "password_reset_codes"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
