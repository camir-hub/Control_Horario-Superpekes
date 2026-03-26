# Funciones de lógica de negocio relacionadas con usuarios

def get_user_by_username(username, db, User):
    return db.session.query(User).filter_by(username=username).first()
