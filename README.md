# Control Horario Profesional (Flask + PostgreSQL)

Aplicacion de control de presencia laboral con arquitectura web + API REST.

## Caracteristicas

- Backend Flask en entorno virtual (venv).
- Base de datos PostgreSQL (compatible con pgAdmin 4).
- Roles:
	- Empleado: crea su jornada del dia actual y consulta historial mensual.
	- Administrador: alta/baja de usuarios, consulta global y validacion de registros con horas extra.
- Registro por tramos: entrada/salida, comida, pausa y horas extra.
- Regla legal: maximo 40 horas semanales por empleado.
- Vista calendario semanal interactiva por dia.
- Geolocalizacion opcional al crear o modificar el fichaje desde navegador compatible.
- Exportacion para inspeccion:
	- Vista de impresion oficial.
	- Descarga PDF.
	- Descarga Excel (.xlsx).
- Informes con estado del registro (Pendiente/Validado) y motivo de cambios con hora.
- Trazabilidad de cambios en tabla de auditoria (audit_logs).
- API REST para reutilizar la misma logica desde Web o App movil.

## Estructura principal

- `app.py`: backend web + API REST.
- `schema_postgresql.sql`: esquema SQL para crear tablas en PostgreSQL.
- `templates/`: vistas HTML5.

## Requisitos

- Python 3.11+ (o superior compatible).
- PostgreSQL 14+.
- pgAdmin 4 (opcional, para administracion visual).

## Instalacion en entorno virtual (Windows PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate
pip install -r requirements.txt
```

## Configuracion PostgreSQL

1. Crea base de datos en PostgreSQL, por ejemplo: `control_horario`.
2. Abre pgAdmin 4 y ejecuta el script [schema_postgresql.sql](schema_postgresql.sql).
3. Configura variables de entorno:

```powershell
$env:DATABASE_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/control_horario"
$env:SECRET_KEY = "cambia_esta_clave_por_otra_segura"
```

## Ejecucion

```powershell
flask --app app run
```

Credenciales iniciales por defecto:

- Usuario: `admin`
- Password: `Admin123!`

Recomendado: cambiarla inmediatamente despues del primer acceso.

## API REST (resumen)

Autenticacion API:

- `POST /api/auth/login`
	- body JSON: `{ "username": "admin", "password": "admin123" }`
	- respuesta: token Bearer.

Cabecera para endpoints protegidos:

- `Authorization: Bearer <token>`

Endpoints principales:

- `GET /api/me`
- `GET /api/entries?day=YYYY-MM-DD&user_id=<id>`
- `POST /api/entries`
	- admite opcionalmente `location_latitude` y `location_longitude`
- `PATCH /api/entries/<id>`
	- requiere `change_reason` y permite actualizar tramos (comida/pausa/extra)
- `GET /api/reports/monthly?month=YYYY-MM&user_id=<id>`
- `GET /api/reports/monthly/pdf?month=YYYY-MM&user_id=<id>`
- `GET /api/reports/monthly/excel?month=YYYY-MM&user_id=<id>`
- `GET /api/audit-logs` (solo admin)

Solo administrador:

- `GET /api/users`
- `POST /api/users`
- `PATCH /api/users/<id>/status`
- `POST /api/entries/<id>/validate`

## Restricciones de negocio implementadas

- No hay endpoint de borrado de registros historicos.
- Modificar registros requiere motivo del cambio y queda auditado.
- Empleado solo crea su jornada del dia actual.
- Un solo registro por empleado y dia.
- Si la suma semanal supera 40h, se bloquea el alta.
- Tramos de comida/pausa/extra deben quedar dentro de la jornada y sin solaparse.
- Horas extra diarias (sobre 8h) quedan marcadas para validacion administrativa.
