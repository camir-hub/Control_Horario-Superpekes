
BEGIN;

-- Control Horario - PostgreSQL (pgAdmin4)
-- Esquema actualizado a 27/03/2026 según modelos activos en app.py
-- Ejecutar conectado a la base de datos: control_horario

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(80) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    rol VARCHAR(20) NOT NULL DEFAULT '',
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
    country VARCHAR(100) NOT NULL DEFAULT '',
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
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    actor_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    target_user_id INTEGER REFERENCES users(id) ON DELETE RESTRICT,
    time_entry_id INTEGER REFERENCES time_entries(id) ON DELETE RESTRICT,
    entity_type VARCHAR(30) NOT NULL,
    entity_id INTEGER,
    action VARCHAR(30) NOT NULL,
    reason TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

COMMIT;
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

-- Rellenar created_at en registros antiguos de time_entries si está vacío
UPDATE time_entries
SET created_at = COALESCE(created_at, work_date::timestamp + check_in, NOW())
WHERE created_at IS NULL;

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

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_rol_active ON users(rol, active);
CREATE INDEX IF NOT EXISTS idx_time_entries_user_date ON time_entries(user_id, work_date);
CREATE INDEX IF NOT EXISTS idx_time_entries_work_date ON time_entries(work_date);
CREATE INDEX IF NOT EXISTS idx_audit_logs_time_entry ON audit_logs(time_entry_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);

INSERT INTO company_profile (id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;

INSERT INTO users (username, password_hash, first_name, last_name, tax_id, affiliation_number,email, phone, address, postal_code, city, province, country, rol, active)
VALUES (
    'Administrador',
    'scrypt:32768:8:1$pmiB2BJlbleLOFKy$41e1499a07564146168bd0d45e9617a9de89491814ebf54824cbd9a88eb0dbc020095c8b8734a7a8e196d5064c1f08dca320cd774b75258f67534dd7d5506b1d',
    'Diana',
    '-----',
    'N/A',
    'N/A',
    'camir.bureau@gmail.com',
    '679911494',
    'Santa Cruz de Bezana',
    '39100',
    'Santander',
    'Cantabria',
    'España',
    'admin',
    TRUE
)
ON CONFLICT (username) DO NOTHING;

-- Tabla para recuperación de contraseña
CREATE TABLE IF NOT EXISTS password_reset_codes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code VARCHAR(12) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    used BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_password_reset_codes_user_id ON password_reset_codes(user_id);
CREATE INDEX IF NOT EXISTS idx_password_reset_codes_code ON password_reset_codes(code);

-- Firma mensual del empleado para cierre legal del parte horario.
CREATE TABLE IF NOT EXISTS monthly_signatures (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    month_key VARCHAR(7) NOT NULL,
    signed_name VARCHAR(180) NOT NULL DEFAULT '',
    signature_data_url TEXT NULL,
    signature_ip VARCHAR(64) NULL,
    signature_user_agent VARCHAR(255) NULL,
    signed_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_monthly_signatures_user_month UNIQUE (user_id, month_key)
);

CREATE INDEX IF NOT EXISTS idx_monthly_signatures_user_month ON monthly_signatures(user_id, month_key);

COMMIT;
