-- Control Horario - PostgreSQL (pgAdmin4)
-- Script unico de esquema/actualizacion.
-- Ejecutar conectado a la base de datos: control_horario.

BEGIN;

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(80) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    rol VARCHAR(20) NOT NULL CHECK (rol IN ('admin', 'employee')),
    first_name VARCHAR(120) NOT NULL DEFAULT '',
    last_name VARCHAR(120) NOT NULL DEFAULT '',
    tax_id VARCHAR(40) NOT NULL DEFAULT '',
    affiliation_number VARCHAR(32) NOT NULL DEFAULT '',
    email VARCHAR(150) NOT NULL DEFAULT '',
    phone VARCHAR(20) NOT NULL DEFAULT '',
    employment_type VARCHAR(30) NOT NULL DEFAULT 'Interno',
    address VARCHAR(200) NOT NULL DEFAULT '',
    postal_code VARCHAR(10) NOT NULL DEFAULT '',
    city VARCHAR(100) NOT NULL DEFAULT '',
    province VARCHAR(100) NOT NULL DEFAULT '',
    country VARCHAR(100) NOT NULL DEFAULT 'Espana',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name VARCHAR(120) NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name VARCHAR(120) NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS tax_id VARCHAR(40) NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS affiliation_number VARCHAR(32) NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(150) NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(20) NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS employment_type VARCHAR(30) NOT NULL DEFAULT 'Interno';
ALTER TABLE users ADD COLUMN IF NOT EXISTS address VARCHAR(200) NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS postal_code VARCHAR(10) NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS city VARCHAR(100) NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS province VARCHAR(100) NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS country VARCHAR(100) NOT NULL DEFAULT 'Espana';
ALTER TABLE users ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW();

CREATE TABLE IF NOT EXISTS company_profile (
    id SERIAL PRIMARY KEY,
    company_name VARCHAR(150) NOT NULL DEFAULT '',
    tax_id VARCHAR(40) NOT NULL DEFAULT '',
    fiscal_address VARCHAR(255) NOT NULL DEFAULT '',
    postal_code VARCHAR(20) NOT NULL DEFAULT '',
    city VARCHAR(120) NOT NULL DEFAULT '',
    province VARCHAR(120) NOT NULL DEFAULT '',
    country VARCHAR(120) NOT NULL DEFAULT 'Espana',
    phone VARCHAR(40) NOT NULL DEFAULT '',
    referral_source VARCHAR(120) NOT NULL DEFAULT '',
    data_policy_accepted BOOLEAN NOT NULL DEFAULT FALSE,
    processing_manager_accepted BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

ALTER TABLE company_profile ADD COLUMN IF NOT EXISTS company_name VARCHAR(150) NOT NULL DEFAULT '';
ALTER TABLE company_profile ADD COLUMN IF NOT EXISTS tax_id VARCHAR(40) NOT NULL DEFAULT '';
ALTER TABLE company_profile ADD COLUMN IF NOT EXISTS fiscal_address VARCHAR(255) NOT NULL DEFAULT '';
ALTER TABLE company_profile ADD COLUMN IF NOT EXISTS postal_code VARCHAR(20) NOT NULL DEFAULT '';
ALTER TABLE company_profile ADD COLUMN IF NOT EXISTS city VARCHAR(120) NOT NULL DEFAULT '';
ALTER TABLE company_profile ADD COLUMN IF NOT EXISTS province VARCHAR(120) NOT NULL DEFAULT '';
ALTER TABLE company_profile ADD COLUMN IF NOT EXISTS country VARCHAR(120) NOT NULL DEFAULT 'Espana';
ALTER TABLE company_profile ADD COLUMN IF NOT EXISTS phone VARCHAR(40) NOT NULL DEFAULT '';
ALTER TABLE company_profile ADD COLUMN IF NOT EXISTS referral_source VARCHAR(120) NOT NULL DEFAULT '';
ALTER TABLE company_profile ADD COLUMN IF NOT EXISTS data_policy_accepted BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE company_profile ADD COLUMN IF NOT EXISTS processing_manager_accepted BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE company_profile ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW();

CREATE TABLE IF NOT EXISTS time_entries (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    work_date DATE NOT NULL,
    check_in TIME NOT NULL,
    meal_start TIME NULL,
    meal_end TIME NULL,
    pause_start TIME NULL,
    pause_end TIME NULL,
    overtime_start TIME NULL,
    overtime_end TIME NULL,
    check_out TIME NOT NULL,
    comments TEXT NULL,
    location_latitude DOUBLE PRECISION NULL,
    location_longitude DOUBLE PRECISION NULL,
    overtime_validated BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_time_entries_user_day UNIQUE (user_id, work_date),
    CONSTRAINT ck_ordered_times CHECK (check_out > check_in),
    CONSTRAINT ck_meal_pair CHECK (
        (meal_start IS NULL AND meal_end IS NULL)
        OR (meal_start IS NOT NULL AND meal_end IS NOT NULL AND meal_end > meal_start)
    )
);

ALTER TABLE time_entries ADD COLUMN IF NOT EXISTS comments TEXT NULL;
ALTER TABLE time_entries ADD COLUMN IF NOT EXISTS location_latitude DOUBLE PRECISION NULL;
ALTER TABLE time_entries ADD COLUMN IF NOT EXISTS location_longitude DOUBLE PRECISION NULL;
ALTER TABLE time_entries ADD COLUMN IF NOT EXISTS pause_start TIME NULL;
ALTER TABLE time_entries ADD COLUMN IF NOT EXISTS pause_end TIME NULL;
ALTER TABLE time_entries ADD COLUMN IF NOT EXISTS overtime_start TIME NULL;
ALTER TABLE time_entries ADD COLUMN IF NOT EXISTS overtime_end TIME NULL;
ALTER TABLE time_entries ADD COLUMN IF NOT EXISTS overtime_validated BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE time_entries ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW();

CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    actor_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    target_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    time_entry_id INTEGER NULL REFERENCES time_entries(id) ON DELETE SET NULL,
    entity_type VARCHAR(30) NOT NULL,
    entity_id INTEGER NULL,
    action VARCHAR(30) NOT NULL,
    reason TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS actor_user_id INTEGER;
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS target_user_id INTEGER;
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS time_entry_id INTEGER;
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS entity_type VARCHAR(30);
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS entity_id INTEGER;
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS action VARCHAR(30);
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS reason TEXT;
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS details TEXT NOT NULL DEFAULT '';
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_rol_active ON users(rol, active);
CREATE INDEX IF NOT EXISTS idx_time_entries_user_date ON time_entries(user_id, work_date);
CREATE INDEX IF NOT EXISTS idx_time_entries_work_date ON time_entries(work_date);
CREATE INDEX IF NOT EXISTS idx_audit_logs_time_entry ON audit_logs(time_entry_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);

INSERT INTO company_profile (id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;

INSERT INTO users (username, password_hash, rol, active)
VALUES (
    'admin',
    'scrypt:32768:8:1$FqL4HwsFJF5vbFRh$f802202ba1917d6b01e32dfca9caf4d420f0b5beb8d1a739703a418da0ea75ac3e6453917cbd82a74b2feb28b7d1f3a524738450dc27456535061f8efd1fdd82',
    'admin',
    TRUE
)
ON CONFLICT (username) DO NOTHING;

COMMIT;
