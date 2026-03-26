# Funciones de lógica de negocio para registros de jornada

def get_entries_for_user(user_id, db, TimeEntry):
    return db.session.query(TimeEntry).filter_by(user_id=user_id).all()
