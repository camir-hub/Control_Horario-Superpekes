-- Esquema PostgreSQL para Control Horario
-- Ejecutar en pgAdmin 4 sobre la base de datos control_horario.

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(80) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('admin', 'employee')),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS time_entries (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    work_date DATE NOT NULL,
    check_in TIME NOT NULL,
    meal_start TIME NULL,
    meal_end TIME NULL,
    check_out TIME NOT NULL,
    comments TEXT NULL,
    overtime_validated BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_time_entries_user_day UNIQUE (user_id, work_date),
    CONSTRAINT ck_ordered_times CHECK (check_out > check_in),
    CONSTRAINT ck_meal_pair CHECK (
        (meal_start IS NULL AND meal_end IS NULL)
        OR
        (meal_start IS NOT NULL AND meal_end IS NOT NULL AND meal_end > meal_start)
    )
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    actor_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    target_user_id INTEGER NULL REFERENCES users(id) ON DELETE RESTRICT,
    time_entry_id INTEGER NULL REFERENCES time_entries(id) ON DELETE RESTRICT,
    entity_type VARCHAR(30) NOT NULL,
    entity_id INTEGER NULL,
    action VARCHAR(30) NOT NULL,
    reason TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_time_entries_user_date ON time_entries(user_id, work_date);
CREATE INDEX IF NOT EXISTS idx_time_entries_work_date ON time_entries(work_date);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_actor_user ON audit_logs(actor_user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_time_entry ON audit_logs(time_entry_id);

-- Admin inicial (password recomendado: cambiar inmediatamente)
-- password_hash para Admin123! (werkzeug)
INSERT INTO users (username, password_hash, role, active)
VALUES (
    'admin',
    'scrypt:32768:8:1$FqL4HwsFJF5vbFRh$f802202ba1917d6b01e32dfca9caf4d420f0b5beb8d1a739703a418da0ea75ac3e6453917cbd82a74b2feb28b7d1f3a524738450dc27456535061f8efd1fdd82',
    'admin',
    TRUE
)
ON CONFLICT (username) DO NOTHING;
