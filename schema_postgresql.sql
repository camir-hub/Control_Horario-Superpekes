
-- Control Horario - Esquema PostgreSQL actualizado (solo para uso externo, sin SQLite)
BEGIN;

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(80) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    rol VARCHAR(20) NOT NULL DEFAULT 'employee',
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

CREATE TABLE company_profile (
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

CREATE TABLE time_entries (
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
    CONSTRAINT uq_time_entries_user_day UNIQUE (user_id, work_date)
);

CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    actor_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    target_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    time_entry_id INTEGER REFERENCES time_entries(id) ON DELETE SET NULL,
    entity_type VARCHAR(30) NOT NULL,
    entity_id INTEGER,
    action VARCHAR(30) NOT NULL,
    reason TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE password_reset_codes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code VARCHAR(12) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    used BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_rol_active ON users(rol, active);
CREATE INDEX idx_time_entries_user_date ON time_entries(user_id, work_date);
CREATE INDEX idx_time_entries_work_date ON time_entries(work_date);
CREATE INDEX idx_audit_logs_time_entry ON audit_logs(time_entry_id);
CREATE INDEX idx_audit_logs_created_at ON audit_logs(created_at);
CREATE INDEX idx_password_reset_codes_user_id ON password_reset_codes(user_id);
CREATE INDEX idx_password_reset_codes_code ON password_reset_codes(code);

-- Insertar perfil de empresa y usuario admin si no existen
INSERT INTO company_profile (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
INSERT INTO users (username, password_hash, rol, active)
VALUES ('admin', 'scrypt:32768:8:1$FqL4HwsFJF5vbFRh$f802202ba1917d6b01e32dfca9caf4d420f0b5beb8d1a739703a418da0ea75ac3e6453917cbd82a74b2feb28b7d1f3a524738450dc27456535061f8efd1fdd82', 'admin', TRUE)
ON CONFLICT (username) DO NOTHING;

COMMIT;
