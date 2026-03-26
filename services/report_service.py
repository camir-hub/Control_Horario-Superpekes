# Funciones de lógica de negocio para reportes

def get_monthly_report(user_id, month, db, TimeEntry):
    # Ejemplo: lógica para obtener un reporte mensual
    return db.session.query(TimeEntry).filter(
        TimeEntry.user_id == user_id,
        TimeEntry.work_date.like(f"{month}-%")
    ).all()
