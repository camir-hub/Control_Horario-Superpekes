from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from models.models import User
from werkzeug.security import check_password_hash

bp_auth = Blueprint('auth', __name__)

@bp_auth.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET' and current_user.is_authenticated:
        logout_user()
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.active and check_password_hash(user.password_hash, password):
            if user.is_admin:
                flash('Este inicio de sesión es solo para empleados', 'login')
                return render_template('login.html', mode='login')
            login_user(user)
            return redirect(url_for('calendar'))
        flash('Credenciales inválidas o usuario inactivo', 'login')
    return render_template('login.html', mode='login')

@bp_auth.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'GET' and current_user.is_authenticated:
        logout_user()
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.active and not user.is_admin and check_password_hash(user.password_hash, password):
            flash('Acceso Denegado', 'login')
            return redirect(url_for('auth.login'))
        if user and user.active and user.is_admin and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('admin_dashboard'))
        flash('Credenciales de administrador inválidas', 'admin_login')
        return render_template('admin_login.html', mode='login')
    return render_template('admin_login.html', mode='login')

@bp_auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))
