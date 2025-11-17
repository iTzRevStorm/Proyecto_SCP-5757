import sqlite3
import os
import datetime
import base64
from datetime import timedelta
from flask import Flask, request, redirect, url_for, render_template_string, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
# ¡NUEVO! Importamos la librería de PostgreSQL
import psycopg2
import psycopg2.extras

# --- Configuración de la Aplicación Flask ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'SCP-Foundation-Secure-Key-918273'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
# ¡NUEVO! Leemos la URL de la base de datos desde las variables de entorno de Render
DATABASE_URL = os.environ.get('DATABASE_URL')

# --- LISTA DE ROLES ---
ROLES = ['admin', 'Supervisor', 'Bodeguero central', 'Bodeguero', 'Obrero', 'user']

# --- CONFIGURACIÓN DE ENCRIPTACIÓN SIMÉTRICA (Fernet) ---
MASTER_KEY = b'pC02-FCS3IeA3m2j-psH_oVSnB6z5gV8zX2b-vV-pII='
f = Fernet(MASTER_KEY)

def encrypt_data(data):
    if data is None: return None
    if isinstance(data, str): data = data.encode('utf-8')
    return f.encrypt(data).decode('utf-8')

def decrypt_data(encrypted_data):
    if encrypted_data is None: return None
    try:
        decrypted_bytes = f.decrypt(encrypted_data.encode('utf-8'))
        return decrypted_bytes.decode('utf-8')
    except Exception as e:
        print(f"Error al desencriptar: {e}")
        return "[DATOS CORRUPTOS]"

# --- SVG DEL LOGO SCP ---
SCP_LOGO_SVG = """
<svg viewBox="0 0 100 100" fill="#FFFFFF" class="scp-logo">
    <title>SCP Foundation Logo</title>
    <path d="M50 0 C22.38 0 0 22.38 0 50 C0 77.62 22.38 100 50 100 C77.62 100 100 77.62 100 50 C100 22.38 77.62 0 50 0 M50 3 C76.01 3 97 23.99 97 50 C97 76.01 76.01 97 50 97 C23.99 97 3 76.01 3 50 C3 23.99 23.99 3 50 3"/>
    <path d="M50 15 C30.65 15 15 30.65 15 50 C15 69.35 30.65 85 50 85 C69.35 85 85 69.35 85 50 C85 30.65 69.35 15 50 15 M50 18 C67.67 18 82 32.33 82 50 C82 67.67 67.67 82 50 82 C32.33 82 18 67.67 18 50 C18 32.33 32.33 18 50 18"/>
    <path d="M44 35 L44 50 L35 50 L50 65 L65 50 L56 50 L56 35 L44 35"/>
    <path d="M44 35 L44 50 L35 50 L50 65 L65 50 L56 50 L56 35 L44 35" transform="rotate(120 50 50)"/>
    <path d="M44 35 L44 50 L35 50 L50 65 L65 50 L56 50 L56 35 L44 35" transform="rotate(240 50 50)"/>
</svg>
"""

# --- Funciones de la Base de Datos (¡TRADUCIDAS A POSTGRESQL!) ---

def get_db_connection():
    # Conecta a la base de datos de Render usando la URL
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def init_db():
    conn = get_db_connection()
    # Usamos un cursor para ejecutar comandos
    cursor = conn.cursor()
    
    # 1. Tabla de Usuarios (Sintaxis de PostgreSQL)
    # Comprueba si la tabla existe
    cursor.execute("SELECT to_regclass('public.users')")
    if cursor.fetchone()[0] is None:
        print("Creando la tabla 'users'...")
        cursor.execute('''
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            status TEXT NOT NULL DEFAULT 'active'
        )
        ''')
        print("Usuario 'admin' por defecto creado (pass: 'admin')")
        admin_pass_hash = generate_password_hash('admin')
        cursor.execute("INSERT INTO users (username, password_hash, role, status) VALUES (%s, %s, %s, %s)",
                       ('admin', admin_pass_hash, 'admin', 'active'))
    
    # 2. Tabla de Herramientas
    cursor.execute("SELECT to_regclass('public.tools')")
    if cursor.fetchone()[0] is None:
        print("Creando la tabla 'tools' (inventario)...")
        cursor.execute('''
        CREATE TABLE tools (
            id SERIAL PRIMARY KEY,
            nombre TEXT NOT NULL UNIQUE,
            descripcion TEXT,
            stock INTEGER NOT NULL
        )
        ''')
        tools_data = [
            ('Esmeril Angular', 'Item-001: Riesgo Keter', 10),
            ('Taladro Percutor', 'Item-002: Riesgo Euclid', 15),
            ('Set de Llaves', 'Item-003: Seguro', 20),
            ('Martillo', 'Item-004: Seguro', 30)
        ]
        cursor.executemany('INSERT INTO tools (nombre, descripcion, stock) VALUES (%s, %s, %s)', tools_data)

    # 3. Tabla de Reportes
    cursor.execute("SELECT to_regclass('public.reportes')")
    if cursor.fetchone()[0] is None:
        print("Creando la tabla 'reportes'...")
        cursor.execute('''
        CREATE TABLE reportes (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            titulo TEXT NOT NULL,
            contenido TEXT NOT NULL,
            fecha_creacion TEXT NOT NULL,
            imagen_base64 TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        ''')
    else:
        # Asegurarnos que la columna de imagen exista (manejo de errores simple)
        try:
            cursor.execute('ALTER TABLE reportes ADD COLUMN imagen_base64 TEXT')
        except psycopg2.Error:
            pass # La columna ya existe, no hacemos nada

    conn.commit() # Guardamos los cambios
    cursor.close()
    conn.close()
    print("Base de datos inicializada y asegurada.")

# --- Funciones de Ayuda de Autenticación (Decoradores) ---

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def check_password_reset(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' in session and session.get('status') == 'must_reset':
            if request.endpoint not in ['force_reset', 'logout']:
                flash('DEBE CAMBIAR SU CONTRASEÑA ANTES DE CONTINUAR.', 'error')
                return redirect(url_for('force_reset', username=session['username'])) # Pasamos el username
        return f(*args, **kwargs)
    return decorated_function

def role_required(*roles):
    def wrapper(f):
        from functools import wraps
        @wraps(f)
        @login_required 
        @check_password_reset 
        def decorated_function(*args, **kwargs):
            if session.get('role') not in roles:
                flash(f'ACCESO DENEGADO. Se requiere Nivel de Autorización: {" o ".join(roles)}', 'error')
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function
    return wrapper

@app.before_request
def make_session_permanent():
    session.permanent = True

# --- Rutas de la Aplicación (Traducidas a PostgreSQL) ---

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        # Usamos un cursor que devuelve diccionarios
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        # Usamos %s como placeholder
        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user and check_password_hash(user['password_hash'], password):
            if user['status'] == 'must_reset':
                flash('AUTORIZACIÓN DE RESETEO RECIBIDA. Debe crear una nueva clave.', 'success')
                return redirect(url_for('force_reset', username=user['username']))
            
            if user['status'] == 'pending_reset':
                flash('Solicitud de reseteo enviada. Esperando autorización de un Admin.', 'error')
                return redirect(url_for('login'))

            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['status'] = user['status']
            session.permanent = True

            if user['role'] == 'admin':
                return redirect(url_for('dashboard_admin'))
            elif user['role'] == 'Supervisor':
                return redirect(url_for('dashboard_supervisor'))
            elif user['role'] in ['Bodeguero', 'Bodeguero central']:
                return redirect(url_for('dashboard_bodeguero'))
            elif user['role'] == 'Obrero':
                return redirect(url_for('dashboard_obrero'))
            else:
                return redirect(url_for('user_no_access_page'))
        else:
            flash('USUARIO O CLAVE INCORRECTOS. INTENTO REGISTRADO.', 'error')
            
    return render_template_string(LOGIN_TEMPLATE, SVG_LOGO=SCP_LOGO_SVG)

@app.route('/logout')
def logout():
    session.clear()
    flash('Desconexión segura del terminal.', 'success')
    return redirect(url_for('login'))

@app.route('/no_access')
@login_required
@check_password_reset
def user_no_access_page():
    if session['role'] != 'user':
        return redirect(url_for('login'))
    return render_template_string(
        USER_NO_ACCESS_TEMPLATE, 
        username=session['username'],
        role=session['role'],
        DASHBOARD_BASE_STYLE=DASHBOARD_BASE_STYLE
    )

# --- Rutas de Reseteo de Contraseña ---

@app.route('/reset_request', methods=['GET', 'POST'])
def reset_request():
    if request.method == 'POST':
        username = request.form['username']
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        user = cursor.fetchone()
        
        if user:
            cursor.execute("UPDATE users SET status = 'pending_reset' WHERE id = %s", (user['id'],))
            conn.commit()
            cursor.close()
            conn.close()
            return redirect(url_for('wait_for_approval', username=username))
        else:
            flash('Usuario no encontrado.', 'error')
            cursor.close()
            conn.close()
            return redirect(url_for('reset_request'))
        
    return render_template_string(RESET_REQUEST_TEMPLATE)

@app.route('/wait_for_approval')
def wait_for_approval():
    username = request.args.get('username')
    if not username:
        return redirect(url_for('login'))
    return render_template_string(WAITING_TEMPLATE, username=username)

@app.route('/check_approval_status')
def check_approval_status():
    username = request.args.get('username')
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cursor.execute('SELECT status FROM users WHERE username = %s', (username,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if user:
        if user['status'] == 'must_reset':
            return jsonify({'status': 'approved', 'redirect_url': url_for('force_reset', username=username)})
        else:
            return jsonify({'status': 'pending'})
    else:
        return jsonify({'status': 'not_found'}), 404

@app.route('/force_reset', methods=['GET', 'POST'])
def force_reset():
    if request.method == 'POST':
        username = request.form['username']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        if new_password != confirm_password:
            flash('Las contraseñas no coinciden. Intente de nuevo.', 'error')
            return redirect(url_for('force_reset', username=username))
        
        new_password_hash = generate_password_hash(new_password)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password_hash = %s, status = 'active' WHERE username = %s", (new_password_hash, username))
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Contraseña actualizada exitosamente. Por favor, inicie sesión.', 'success')
        return redirect(url_for('login'))

    username = request.args.get('username')
    if not username:
        flash('Solicitud inválida. Falta usuario.', 'error')
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cursor.execute('SELECT status FROM users WHERE username = %s', (username,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not user or user['status'] != 'must_reset':
        flash('Este usuario no tiene un reseteo de contraseña autorizado.', 'error')
        return redirect(url_for('login'))

    return render_template_string(FORCE_RESET_TEMPLATE, username=username)
    
@app.route('/approve_reset', methods=['POST'])
@role_required('admin')
def approve_reset():
    user_id = request.form['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET status = 'must_reset' WHERE id = %s", (user_id,))
    conn.commit()
    cursor.close()
    conn.close()
    flash('Reseteo autorizado. El usuario será redirigido para crear una nueva clave.', 'success')
    return redirect(url_for('dashboard_admin', vista='solicitudes'))
    
# --- 1. DASHBOARD ADMIN ---
@app.route('/dashboard')
@role_required('admin')
def dashboard_admin():
    vista_activa = request.args.get('vista', 'crear')
    users = []
    reportes = []
    inventario = []
    solicitudes = []
    buscar_query = request.args.get('buscar_query', '')
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    if vista_activa == 'lista':
        cursor.execute("SELECT * FROM users WHERE status != 'pending_reset'")
        users = cursor.fetchall()
    
    elif vista_activa == 'buscar':
        if buscar_query:
            query = f"%{buscar_query}%"
            cursor.execute("SELECT * FROM users WHERE username LIKE %s AND status != 'pending_reset'", (query,))
            users = cursor.fetchall()
    
    elif vista_activa == 'reportes':
        cursor.execute("SELECT r.*, u.username FROM reportes r JOIN users u ON r.user_id = u.id ORDER BY r.id DESC")
        reportes_enc = cursor.fetchall()
        for r in reportes_enc:
            reportes.append({
                'id': r['id'], 'username': r['username'],
                'titulo': decrypt_data(r['titulo']),
                'contenido': decrypt_data(r['contenido']),
                'fecha_creacion': r['fecha_creacion'],
                'imagen_base64': decrypt_data(r['imagen_base64'])
            })
        
    elif vista_activa == 'inventario':
        cursor.execute("SELECT * FROM tools ORDER BY nombre")
        inventario = cursor.fetchall()

    elif vista_activa == 'solicitudes':
        cursor.execute("SELECT id, username FROM users WHERE status = 'pending_reset'")
        solicitudes = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template_string(
        DASHBOARD_ADMIN_TEMPLATE, 
        users=users,
        reportes=reportes,
        inventario=inventario,
        solicitudes=solicitudes,
        username=session['username'], 
        role=session['role'], 
        buscar_query=buscar_query,
        vista_activa=vista_activa,
        ROLES_LISTA=ROLES,
        DASHBOARD_BASE_STYLE=DASHBOARD_BASE_STYLE
    )

# --- 2. DASHBOARD SUPERVISOR ---
@app.route('/supervisor')
@role_required('Supervisor')
def dashboard_supervisor():
    vista_activa = request.args.get('vista', 'crear_reporte')
    reportes = []
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    cursor.execute("SELECT id, username FROM users WHERE role = 'Obrero'")
    obreros = cursor.fetchall()
    
    cursor.execute("SELECT * FROM tools ORDER BY nombre")
    stock_bodega = cursor.fetchall()
    
    cursor.execute("SELECT r.*, u.username FROM reportes r JOIN users u ON r.user_id = u.id ORDER BY r.id DESC")
    reportes_enc = cursor.fetchall()
    for r in reportes_enc:
        reportes.append({
            'id': r['id'], 'username': r['username'],
            'titulo': decrypt_data(r['titulo']),
            'contenido': decrypt_data(r['contenido']),
            'fecha_creacion': r['fecha_creacion'],
            'imagen_base64': decrypt_data(r['imagen_base64'])
        })
    cursor.close()
    conn.close()
    
    return render_template_string(
        DASHBOARD_SUPERVISOR_TEMPLATE,
        username=session['username'],
        role=session['role'],
        obreros=obreros,
        reportes=reportes,
        stock_bodega=stock_bodega,
        vista_activa=vista_activa,
        DASHBOARD_BASE_STYLE=DASHBOARD_BASE_STYLE
    )

# --- 3. DASHBOARD BODEGUERO ---
@app.route('/bodeguero')
@role_required('Bodeguero', 'Bodeguero central')
def dashboard_bodeguero():
    vista_activa = request.args.get('vista', 'inventario')
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cursor.execute("SELECT * FROM tools ORDER BY nombre")
    inventario = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template_string(
        DASHBOARD_BODEGUERO_TEMPLATE,
        username=session['username'],
        role=session['role'],
        inventario=inventario,
        vista_activa=vista_activa,
        DASHBOARD_BASE_STYLE=DASHBOARD_BASE_STYLE
    )

# --- 4. DASHBOARD OBRERO ---
@app.route('/obrero')
@role_required('Obrero')
def dashboard_obrero():
    vista_activa = request.args.get('vista', 'pedir')
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cursor.execute("SELECT * FROM tools WHERE stock > 0 ORDER BY nombre")
    herramientas_disponibles = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template_string(
        DASHBOARD_OBRERO_TEMPLATE,
        username=session['username'],
        role=session['role'],
        herramientas=herramientas_disponibles,
        vista_activa=vista_activa,
        DASHBOARD_BASE_STYLE=DASHBOARD_BASE_STYLE
    )

# --- RUTAS DE ACCIONES (Formularios) ---

@app.route('/crear_reporte', methods=['POST'])
@role_required('Supervisor', 'Obrero')
def crear_reporte():
    titulo = request.form['titulo']
    contenido = request.form['contenido']
    user_id = session['user_id']
    fecha = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    
    imagen_base64 = None
    if 'imagen' in request.files:
        file = request.files['imagen']
        if file.filename != '':
            try:
                img_bytes = file.read()
                imagen_base64 = base64.b64encode(img_bytes).decode('utf-8')
                flash('Imagen adjuntada exitosamente.', 'success')
            except Exception as e:
                flash(f'Error al procesar imagen: {e}', 'error')
                if session['role'] == 'Supervisor':
                    return redirect(url_for('dashboard_supervisor'))
                else:
                    return redirect(url_for('dashboard_obrero'))

    titulo_enc = encrypt_data(titulo)
    contenido_enc = encrypt_data(contenido)
    imagen_base64_enc = encrypt_data(imagen_base64) 

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO reportes (user_id, titulo, contenido, fecha_creacion, imagen_base64) VALUES (%s, %s, %s, %s, %s)',
        (user_id, titulo_enc, contenido_enc, fecha, imagen_base64_enc)
    )
    conn.commit()
    cursor.close()
    conn.close()
    
    flash('Reporte archivado y encriptado.', 'success')
    
    if session['role'] == 'Supervisor':
        return redirect(url_for('dashboard_supervisor'))
    else:
        return redirect(url_for('dashboard_obrero'))

@app.route('/crear', methods=['POST'])
@role_required('admin')
def crear_usuario():
    username = request.form['username']
    password = request.form['password']
    role = request.form['role']
    password_hash = generate_password_hash(password)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)', (username, password_hash, role))
        conn.commit()
        flash(f'Sujeto "{username}" registrado exitosamente.', 'success')
    except (psycopg2.Error, psycopg2.IntegrityError):
        conn.rollback() # Deshacemos la transacción en caso de error
        flash(f'Error: Designación de sujeto "{username}" ya existe.', 'error')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('dashboard_admin'))

@app.route('/eliminar', methods=['POST'])
@role_required('admin')
def eliminar_usuario():
    user_id = request.form['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM users WHERE id = %s AND username != %s', (user_id, 'admin'))
    conn.commit()
    cursor.close()
    conn.close()
    flash('Sujeto eliminado.', 'success')
    return redirect(url_for('dashboard_admin', vista='lista'))

@app.route('/cambiar_rol', methods=['POST'])
@role_required('admin')
def cambiar_rol():
    user_id = request.form['user_id']
    new_role = request.form['new_role']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET role = %s WHERE id = %s AND username != %s', (new_role, user_id, 'admin'))
    conn.commit()
    cursor.close()
    conn.close()
    flash('Nivel de autorización actualizado.', 'success')
    return redirect(url_for('dashboard_admin', vista='lista'))

@app.route('/editar_nombre', methods=['POST'])
@role_required('admin')
def editar_nombre():
    user_id = request.form['user_id']
    new_username = request.form['new_username']
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('UPDATE users SET username = %s WHERE id = %s AND username != %s', (new_username, user_id, 'admin'))
        conn.commit()
        flash('Designación de sujeto actualizada.', 'success')
    except (psycopg2.Error, psycopg2.IntegrityError):
        conn.rollback()
        flash(f'Error: Designación "{new_username}" ya existe.', 'error')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('dashboard_admin', vista='lista'))

@app.route('/pedir_herramienta', methods=['POST'])
@role_required('Obrero')
def pedir_herramienta():
    tool_id = request.form['tool_id']
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cursor.execute('SELECT stock, nombre FROM tools WHERE id = %s', (tool_id,))
    tool = cursor.fetchone()
    if tool and tool['stock'] > 0:
        cursor.execute('UPDATE tools SET stock = stock - 1 WHERE id = %s', (tool_id,))
        conn.commit()
        flash(f'Item "{tool["nombre"]}" retirado de contención.', 'success')
    else:
        flash(f'Error: Item "{tool["nombre"]}" sin stock.', 'error')
    cursor.close()
    conn.close()
    return redirect(url_for('dashboard_obrero'))

@app.route('/agregar_stock', methods=['POST'])
@role_required('Bodeguero', 'Bodeguero central', 'admin')
def agregar_stock():
    tool_id = request.form['tool_id']
    cantidad = int(request.form['cantidad'])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    if cantidad > 0:
        cursor.execute('UPDATE tools SET stock = stock + %s WHERE id = %s', (cantidad, tool_id))
        conn.commit()
        flash(f'{cantidad} unidades añadidas a contención.', 'success')
    else:
        flash('Cantidad debe ser positiva.', 'error')
    
    cursor.close()
    conn.close()
    
    if session['role'] == 'admin':
        return redirect(url_for('dashboard_admin', vista='inventario'))
    else:
        return redirect(url_for('dashboard_bodeguero'))

# --- [¡REDISEÑO COMPLETO!] Plantillas HTML ---

# --- Plantilla de Login (COMPLETA) ---
LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="es" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SCP Foundation - Secure Login</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Roboto+Mono:wght@400;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color-dark: #000;
            --bg-card-dark: rgba(0, 0, 0, 0.85);
            --text-color-dark: #eeeeee;
            --text-muted-dark: #aaa;
            --border-color-dark: #333;
            --border-accent-dark: #c0392b;
            --primary-dark: #c0392b;
            --primary-hover-dark: transparent;
            --primary-hover-text-dark: #c0392b;
            --input-bg-dark: #1a1a1a;
            --success-bg-dark: #003d0a;
            --success-border-dark: #27ae60;
            --error-bg-dark: #4d0000;
            --error-border-dark: #c0392b;

            --bg-color-light: #f0f2f5;
            --bg-card-light: #ffffff;
            --text-color-light: #222222;
            --text-muted-light: #555;
            --border-color-light: #dddddd;
            --border-accent-light: #007bff;
            --primary-light: #007bff;
            --primary-hover-light: #0056b3;
            --primary-hover-text-light: #ffffff;
            --input-bg-light: #ffffff;
            --success-bg-light: #d4edda;
            --success-border-light: #c3e6cb;
            --error-bg-light: #f8d7da;
            --error-border-light: #f5c6cb;
            
            --bg-color: var(--bg-color-dark);
            --bg-card: var(--bg-card-dark);
            --text-color: var(--text-color-dark);
            --text-muted: var(--text-muted-dark);
            --border-color: var(--border-color-dark);
            --border-accent: var(--border-accent-dark);
            --primary: var(--primary-dark);
            --primary-hover: var(--primary-hover-dark);
            --primary-hover-text: var(--primary-hover-text-dark);
            --input-bg: var(--input-bg-dark);
            --success-bg: var(--success-bg-dark);
            --success-border: var(--success-border-dark);
            --error-bg: var(--error-bg-dark);
            --error-border: var(--error-border-dark);
        }
        
        [data-theme="light"] {
            --bg-color: var(--bg-color-light);
            --bg-card: var(--bg-card-light);
            --text-color: var(--text-color-light);
            --text-muted: var(--text-muted-light);
            --border-color: var(--border-color-light);
            --border-accent: var(--border-accent-light);
            --primary: var(--primary-light);
            --primary-hover: var(--primary-hover-light);
            --primary-hover-text: var(--primary-hover-text-light);
            --input-bg: var(--input-bg-light);
            --success-bg: var(--success-bg-light);
            --success-border: var(--success-border-light);
            --error-bg: var(--error-bg-light);
            --error-border: var(--error-border-light);
        }
        
        body {
            font-family: 'Roboto Mono', 'Consolas', monospace;
            background-color: var(--bg-color);
            color: var(--text-color);
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            transition: background-color 0.3s;
            overflow: hidden;
        }
        .login-card {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            padding: 2.5rem;
            border-radius: 4px;
            box-shadow: 0 0 20px rgba(0, 0, 0, 0.1);
            width: 100%;
            max-width: 400px;
            box-sizing: border-box;
            text-align: center;
            transition: background-color 0.3s, border-color 0.3s;
            z-index: 10;
        }
        .scp-logo {
            width: 120px;
            height: 120px;
            margin-bottom: 1.5rem;
            fill: var(--text-color);
        }
        [data-theme="light"] .scp-logo { fill: #333; }
        
        .login-card h1 {
            color: var(--text-color);
            margin-top: 0;
            margin-bottom: 1.5rem;
            font-size: 1.5rem;
            font-weight: 700;
            letter-spacing: 2px;
            text-transform: uppercase;
        }
        .form-group {
            margin-bottom: 1.25rem;
            text-align: left;
            position: relative;
        }
        .form-group label {
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 400;
            color: var(--text-muted);
            text-transform: uppercase;
            font-size: 0.8rem;
        }
        .form-group input {
            width: 100%;
            padding: 0.75rem;
            border: 1px solid var(--border-color);
            background-color: var(--input-bg);
            border-radius: 2px;
            box-sizing: border-box;
            font-size: 1rem;
            color: var(--text-color);
            font-family: 'Roboto Mono', 'Consolas', monospace;
            padding-right: 40px; 
        }
        .password-toggle {
            position: absolute;
            right: 10px;
            top: 35px;
            cursor: pointer;
            color: var(--text-muted);
            user-select: none;
            font-size: 1.2rem;
        }
        .btn {
            width: 100%;
            padding: 0.85rem;
            border: 1px solid var(--primary);
            border-radius: 2px;
            background-color: var(--primary);
            color: white !important; 
            font-size: 1rem;
            font-weight: 700;
            cursor: pointer;
            transition: background-color 0.2s, color 0.2s;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .btn:hover {
            background-color: var(--primary-hover);
            color: var(--primary-hover-text) !important;
        }
        .flash {
            padding: 0.8rem; margin-bottom: 1rem; border-radius: 2px;
            font-weight: 700; text-align: center; font-size: 0.9rem;
            border: 1px solid;
        }
        .flash.error {
            background-color: var(--error-bg);
            border-color: var(--error-border);
            color: var(--primary);
        }
        [data-theme="light"] .flash.error { color: #721c24; }
        .flash.success {
            background-color: var(--success-bg);
            border-color: var(--success-border);
            color: #27ae60;
        }
        [data-theme="light"] .flash.success { color: #155724; }
        
        .theme-toggle {
            position: absolute;
            top: 20px;
            right: 20px;
            cursor: pointer;
            font-size: 1.5rem;
            color: var(--text-muted);
            z-index: 11;
        }
        
        .forgot-password {
            display: block;
            text-align: right;
            font-size: 0.8rem;
            color: var(--text-muted);
            text-decoration: none;
            margin-top: -10px;
            margin-bottom: 15px;
        }
        .forgot-password:hover {
            color: var(--text-color);
            text-decoration: underline;
        }
        
        .easter-egg {
            display: none;
            position: fixed;
            z-index: 9999;
            right: 20px;
            top: 50%;
            transform: translateY(-50%);
            padding: 10px;
            background-color: var(--bg-card);
            border: 2px solid var(--border-accent);
            border-radius: 4px;
            opacity: 0;
            transition: opacity 0.5s ease-in-out;
            text-align: center;
        }
        .easter-egg img {
            max-width: 250px;
            height: auto;
        }
        .easter-egg p {
            color: var(--primary);
            font-weight: 700;
            margin-top: 10px;
        }
    </style>
</head>
<body>
    <div class="theme-toggle" id="theme-toggle">☀️</div>
    
    <div id="easter-egg" class="easter-egg">
        <img src="data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAYEBAUEBAYFBQUGBgYHCQ4JCQgICRINDQoOFBAPDQ4NDgwTERQUFhITFhcWGRkSExAbHRsYHRYYGRziISLfIjed/2wBDAQYHBwYIChgQChAPHRQfHR8fHR8fHR8fHR8fHR8fHR8fHR8fHR8fHR8fHR8fHR8fHR8fHR8fHR8fHR8fHR8fHR//wAARCADvAU4DASIAAhEBAxEB/8QAGwABAQADAQEBAAAAAAAAAAAAAAMCBAUGAQf/xAAzEAEAAgECBgICAQMDBQEAAAAAAQIDBBEFEiETMVGBUWEiMkFxgZEFNEKhscHwIzOi4f/EABgBAQEBAQEAAAAAAAAAAAAAAAABAgME/8QAGhEBAQEBAQEBAAAAAAAAAAAAAAERIQISUf/aAAwDAQACEQMRAD8A/SAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAfm94rFExaZnwiIiZmZc8XJkyd+zxVj/vO/1GzS26SazrzT/AIxG/wDlnJyZctzPFMR/tGv7tE1F61JFKV6xWsaREQN9cTT0m8z5REzLIsHNPGsVmZtWZ4ZmZ3JAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD4tataxWtasUiNaREbA5ScmTJvEzFY/2xv+7qDRi0VrFaxWKxGkREbEQAAAAAAAAAAAAAAAABz5sFclYmJmLRGkbR4S6Akz4MmPvzxT/ALxv+GqLWtpHFKzWeIiYl0xMTEraJiY8JidphrTqAAAAAAAAAAAAAAAACfN0/vXis/6RO36y1Zsd8dum9J1idYnwiYkQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABkw5Jxb1tOkxtMeMQ2AcuLPS9YrERWsxEzG+8+TqAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//Z" alt="Waton Linux Easter Egg">
        <p>Waton Linux</p>
    </div>

    <div class="login-card">
        {{ SVG_LOGO|safe }}
        
        <h1>SISTEMA DE INGRESO</h1>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="flash {{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        <form action="/" method="POST">
            <div class="form-group">
                <label for="username">Designación de Usuario</label>
                <input type="text" id="username" name="username" required>
            </div>
            <div class="form-group">
                <label for="password">Clave de Acceso</label>
                <input type="password" id="password" name="password" required>
                <span class="password-toggle" onclick="togglePassword(this, 'password')">👁️</span>
            </div>
            <a href="{{ url_for('reset_request') }}" class="forgot-password">¿Olvidaste tu contraseña?</a>
            
            <button type="submit" class="btn">Autenticar</button>
        </form>
    </div>
    
    <script>
        function togglePassword(eye, inputId) {
            const input = document.getElementById(inputId);
            if (input.type === 'password') {
                input.type = 'text';
                eye.textContent = '🙈';
            } else {
                input.type = 'password';
                eye.textContent = '👁️';
            }
        }
        
        const themeToggle = document.getElementById('theme-toggle');
        const body = document.documentElement;
        const currentTheme = localStorage.getItem('theme') || 'dark';
        body.setAttribute('data-theme', currentTheme);
        themeToggle.textContent = currentTheme === 'light' ? '🌙' : '☀️';
        themeToggle.addEventListener('click', () => {
            const newTheme = body.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            body.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            themeToggle.textContent = newTheme === 'light' ? '🌙' : '☀️';
        });
        
        const easterEggTrigger = 'hesoyam';
        const usernameInput = document.getElementById('username');
        const passwordInput = document.getElementById('password');
        const easterEggDiv = document.getElementById('easter-egg');
        let easterEggActive = false;
        function checkEasterEgg(event) {
            if (easterEggActive) return;
            if (event.target.value.toLowerCase() === easterEggTrigger) {
                easterEggActive = true;
                easterEggDiv.style.display = 'block';
                setTimeout(() => { easterEggDiv.style.opacity = '1'; }, 10);
                event.target.value = '';
                setTimeout(() => {
                    easterEggDiv.style.opacity = '0';
                    setTimeout(() => {
                        easterEggDiv.style.display = 'none';
                        easterEggActive = false;
                    }, 500);
                }, 3000);
            }
        }
        usernameInput.addEventListener('input', checkEasterEgg);
        passwordInput.addEventListener('input', checkEasterEgg);
    </script>
</body>
</html>
"""

# --- Plantilla de Estilos Base para Dashboards (COMPLETA) ---
DASHBOARD_BASE_STYLE = """
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Roboto+Mono:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-dark: #0a0a0a;
            --bg-card-dark: #1a1a1a;
            --text-dark: #eeeeee;
            --text-muted-dark: #aaa;
            --border-dark: #333;
            --border-accent-dark: #c0392b;
            --red-dark: #c0392b;
            --green-dark: #27ae60;
            --blue-dark: #2980b9;
            --hover-dark: #333;
            --success-bg-dark: #003d0a;
            --success-border-dark: #27ae60;
            --error-bg-dark: #4d0000;
            --error-border-dark: #c0392b;
            --input-bg-dark: #0a0a0a;

            --bg-light: #f0f2f5;
            --bg-card-light: #ffffff;
            --text-light: #222222;
            --text-muted-light: #555;
            --border-light: #dddddd;
            --border-accent-light: #007bff;
            --red-light: #dc3545;
            --green-light: #28a745;
            --blue-light: #007bff;
            --hover-light: #e9ecef;
            --success-bg-light: #d4edda;
            --success-border-light: #c3e6cb;
            --error-bg-light: #f8d7da;
            --error-border-light: #f5c6cb;
            --input-bg-light: #ffffff;
            
            --bg: var(--bg-dark);
            --bg-card: var(--bg-card-dark);
            --text-color: var(--text-dark);
            --text-muted: var(--text-muted-dark);
            --border: var(--border-dark);
            --border-accent: var(--border-accent-dark);
            --red: var(--red-dark);
            --green: var(--green-dark);
            --blue: var(--blue-dark);
            --hover: var(--hover-dark);
            --success-bg: var(--success-bg-dark);
            --success-border: var(--success-border-dark);
            --error-bg: var(--error-bg-dark);
            --error-border: var(--error-border-dark);
            --input-bg: var(--input-bg-dark);
        }
        
        html[data-theme="light"] {
            --bg: var(--bg-light);
            --bg-card: var(--bg-card-light);
            --text-color: var(--text-light);
            --text-muted: var(--text-muted-light);
            --border: var(--border-light);
            --border-accent: var(--border-accent-light);
            --red: var(--red-light);
            --green: var(--green-light);
            --blue: var(--blue-light);
            --hover: var(--hover-light);
            --success-bg: var(--success-bg-light);
            --success-border: var(--success-border-light);
            --error-bg: var(--error-bg-light);
            --error-border: var(--error-border-light);
            --input-bg: var(--input-bg-light);
        }
        
        body {
            font-family: 'Roboto Mono', 'Consolas', monospace;
            margin: 0; background-color: var(--bg);
            color: var(--text-color); display: flex;
            height: 100vh; overflow: hidden;
            transition: background-color 0.3s, color 0.3s;
        }
        /* --- Barra Lateral --- */
        .sidebar {
            width: 240px;
            background-color: var(--bg-card);
            border-right: 1px solid var(--border);
            padding: 20px;
            height: 100vh;
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
            flex-shrink: 0;
            transition: background-color 0.3s, border-color 0.3s;
            overflow-y: auto;
        }
        .sidebar h1 {
            font-size: 1.3rem;
            margin: 0 0 30px 0;
            text-align: center;
            color: var(--text-color);
            text-transform: uppercase;
            border-bottom: 1px solid var(--red);
            padding-bottom: 15px;
            letter-spacing: 1px;
        }
        .sidebar-link {
            color: var(--text-muted);
            text-decoration: none;
            padding: 12px 15px;
            border-radius: 2px;
            margin-bottom: 8px;
            font-weight: 500;
            transition: all 0.2s;
            border: 1px solid transparent;
            font-size: 0.9rem;
        }
        .sidebar-link:hover {
            background-color: var(--hover);
            color: var(--text-color);
        }
        .sidebar-link.active {
            background-color: var(--bg);
            color: var(--text-color);
            border: 1px solid var(--red);
        }
        .sidebar-link.logout {
            margin-top: auto;
            background-color: var(--red);
            color: white;
            text-align: center;
        }
        .sidebar-link.logout:hover {
            opacity: 0.8;
        }

        /* --- Contenido Principal --- */
        .main-content {
            flex-grow: 1;
            padding: 25px;
            overflow-y: auto;
            height: 100vh;
            box-sizing: border-box;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 15px;
        }
        .header h2 { margin: 0; color: var(--text-color); font-size: 1.5rem; }
        .user-info { font-size: 0.9rem; color: var(--text-muted); }
        .user-info span { font-weight: bold; color: var(--red); }
        
        .theme-toggle {
            cursor: pointer;
            font-size: 1.5rem;
            color: var(--text-muted);
            margin-left: 20px;
            user-select: none;
        }

        /* --- Tarjetas de Contenido --- */
        .card {
            background-color: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 2px;
            padding: 25px;
            margin-bottom: 20px;
            transition: background-color 0.3s, border-color 0.3s;
        }
        .card h2 {
            margin-top: 0;
            font-size: 1.2rem;
            color: var(--text-color);
            border-bottom: 1px solid var(--border);
            padding-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        /* --- Formularios --- */
        .form-layout {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            align-items: flex-end;
        }
        .form-group {
            display: flex;
            flex-direction: column;
            position: relative;
        }
        .form-group label {
            font-weight: 500;
            margin-bottom: 8px;
            font-size: 0.8rem;
            color: var(--text-muted);
            text-transform: uppercase;
        }
        input[type="text"], input[type="password"], input[type="number"], input[type="file"], select, textarea {
            padding: 10px;
            border: 1px solid var(--border);
            background-color: var(--input-bg);
            border-radius: 2px;
            font-size: 1rem;
            box-sizing: border-box;
            width: 100%;
            font-family: var(--font-mono);
            color: var(--text-color);
            transition: background-color 0.3s, border-color 0.3s, color 0.3s;
        }
        input[type="file"] { background-color: var(--bg-card); padding: 8px; }
        input[type="file"]::file-selector-button {
            background-color: var(--text-muted);
            color: var(--bg-card);
            border: none;
            padding: 5px 10px;
            border-radius: 2px;
            font-family: var(--font-mono);
            font-weight: 700;
            cursor: pointer;
        }
        .password-toggle {
            position: absolute;
            right: 10px;
            bottom: 8px; 
            cursor: pointer;
            color: var(--text-muted);
            user-select: none;
            font-size: 1.2rem;
        }
        textarea { min-height: 80px; }
        select { appearance: none; background-image: url('data:image/svg+xml;charset=US-ASCII,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22292.4%22%20height%3D%22292.4%22%3E%3Cpath%20fill%3D%22%23AAA%22%20d%3D%22M287%2069.4a17.6%2017.6%200%200%200-13-5.4H18.4c-5%200-9.3%201.8-13%205.4A17.6%2017.6%200%200%200%200%2082.2c0%205%201.8%209.3%205.4%2013l128%20128c3.6%203.6%207.8%205.4%2013%205.4s9.4-1.8%2013-5.4l128-128c3.6-3.6%205.4-7.8%205.4-13%200-4.8-1.8-9.2-5.4-12.8z%22%2F%3E%3C%2Fsvg%3E'); background-repeat: no-repeat; background-position: right 10px center; background-size: 10px; }
        
        /* --- Botones --- */
        .btn {
            background-color: var(--text-muted);
            color: var(--bg-card);
            padding: 10px 20px;
            border: 1px solid var(--text-muted);
            border-radius: 2px;
            cursor: pointer;
            font-size: 0.9rem;
            font-weight: 700;
            transition: all 0.2s;
            text-transform: uppercase;
            font-family: var(--font-mono);
            height: 40px;
        }
        .btn:hover { background-color: var(--text-color); border-color: var(--text-color); }
        .btn-green { background-color: var(--green); border-color: var(--green); color: white; }
        .btn-green:hover { opacity: 0.8; }
        .btn-red { background-color: var(--red); border-color: var(--red); color: white; }
        .btn-red:hover { opacity: 0.8; }

        /* --- Tabla --- */
        .user-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }
        .user-table th, .user-table td {
            padding: 12px;
            border-bottom: 1px solid var(--border);
            text-align: left;
            vertical-align: middle;
        }
        .user-table th {
            background-color: var(--bg);
            font-weight: 700;
            color: var(--text-muted);
            text-transform: uppercase;
            font-size: 0.8rem;
        }
        .user-table td .form-layout { grid-template-columns: 1fr auto; gap: 5px; }
        .user-table td .btn { height: 34px; padding: 5px 10px; }
        .user-table td select { height: 34px; padding: 5px; }
        
        .action-btn {
            background: none; border: none; padding: 0;
            font-family: inherit; font-size: 0.9rem; cursor: pointer;
            color: var(--red); text-decoration: none; font-weight: 600;
        }
        .action-btn:hover { text-decoration: underline; }
        .action-btn.disabled {
            color: var(--text-muted);
            pointer-events: none;
            cursor: default;
            text-decoration: none;
        }
        .action-btn.edit { color: var(--blue); }
        .report-image {
            max-width: 200px;
            height: auto;
            border: 1px solid var(--border);
            border-radius: 2px;
            margin-top: 10px;
        }

        /* --- Modal (Popup) --- */
        .modal {
            display: none; position: fixed; z-index: 1000;
            left: 0; top: 0; width: 100%; height: 100%;
            overflow: auto; background-color: rgba(0,0,0,0.7);
        }
        .modal-content {
            background-color: var(--bg-card);
            margin: 10% auto;
            padding: 25px;
            border: 1px solid var(--red);
            width: 80%;
            max-width: 500px;
            border-radius: 2px;
            position: relative;
        }
        .modal-content h2 { color: var(--text-color); }
        .modal-close {
            color: #aaa; position: absolute; top: 10px; right: 20px;
            font-size: 28px; font-weight: bold;
        }
        .modal-close:hover, .modal-close:focus {
            color: var(--text-color); text-decoration: none; cursor: pointer;
        }

        /* --- Alertas Flash --- */
        .flash {
            padding: 15px; margin-bottom: 15px; border-radius: 2px;
            font-weight: 700; opacity: 0; animation: fadeIn 0.5s forwards;
            font-size: 0.9rem; border: 1px solid;
        }
        .flash.success { 
            background-color: var(--success-bg); 
            border-color: var(--success-border); 
            color: var(--green); 
        }
        html[data-theme="light"] .flash.success { color: #155724; }
        .flash.error { 
            background-color: var(--error-bg); 
            border-color: var(--error-border); 
            color: var(--red); 
        }
        html[data-theme="light"] .flash.error { color: #721c24; }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
    </style>
"""

# --- Plantilla "Sin Acceso" (COMPLETA) ---
USER_NO_ACCESS_TEMPLATE = """
<!DOCTYPE html>
<html lang="es" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ACCESO DENEGADO</title>
    {{ DASHBOARD_BASE_STYLE|safe }}
    <style>
        body {
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .access-denied-card {
            background-color: var(--bg-card);
            border: 1px solid var(--red);
            padding: 3rem;
            border-radius: 2px;
            box-shadow: 0 0 20px rgba(255, 0, 0, 0.2);
            text-align: center;
            max-width: 600px;
            margin: auto;
        }
        .access-denied-card h1 {
            color: var(--red);
            font-size: 2rem;
            text-transform: uppercase;
            letter-spacing: 2px;
            margin-top: 0;
            animation: flicker 1.5s infinite alternate;
        }
        html[data-theme="light"] .access-denied-card h1 { animation: none; }
        @keyframes flicker {
            0%, 18%, 22%, 25%, 53%, 57%, 100% { text-shadow: 0 0 4px #f00, 0 0 11px #f00, 0 0 19px #f00; }
            20%, 24%, 55% { text-shadow: none; }
        }
        .access-denied-card p {
            color: var(--text-color);
            font-size: 1.1rem;
        }
        .access-denied-card span {
            font-weight: bold;
            color: #ffc107; /* Amarillo advertencia */
        }
        .btn-red {
            margin-top: 1.5rem;
            width: auto;
        }
    </style>
</head>
<body>
    <div class="theme-toggle" id="theme-toggle" style="position: absolute; top: 20px; right: 20px;">☀️</div>
    <div class="access-denied-card">
        <h1>[ ACCESO DENEGADO ]</h1>
        <p>El personal con Nivel de Autorización <span>{{ role.capitalize() }}</span> no tiene permiso para acceder a este terminal.</p>
        <p>Sujeto: <span>{{ username }}</span></p>
        <a href="/logout" class="btn btn-red">Cerrar Sesión</a>
    </div>
    <script id="global-theme-script">
        const themeToggle = document.getElementById('theme-toggle');
        const html = document.documentElement;
        const currentTheme = localStorage.getItem('theme') || 'dark';
        html.setAttribute('data-theme', currentTheme);
        themeToggle.textContent = currentTheme === 'light' ? '🌙' : '☀️';
        themeToggle.addEventListener('click', () => {
            const newTheme = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            html.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            themeToggle.textContent = newTheme === 'light' ? '🌙' : '☀️';
        });
    </script>
</body>
</html>
"""

# --- Plantilla Admin (COMPLETA) ---
DASHBOARD_ADMIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="es" data-theme="dark">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin // Nivel 5</title>
    {{ DASHBOARD_BASE_STYLE|safe }}
</head>
<body>
    <nav class="sidebar">
        <h1>ADMIN-SYS // Nv. 5</h1>
        
        <a href="{{ url_for('dashboard_admin') }}?vista=crear" class="sidebar-link {% if vista_activa == 'crear' %}active{% endif %}">
            > Registrar Sujeto
        </a>
        <a href="{{ url_for('dashboard_admin') }}?vista=lista" class="sidebar-link {% if vista_activa == 'lista' %}active{% endif %}">
            > Ver Base de Datos
        </a>
        <a href="{{ url_for('dashboard_admin') }}?vista=buscar" class="sidebar-link {% if vista_activa == 'buscar' %}active{% endif %}">
            > Buscar Sujeto
        </a>
        <a href="{{ url_for('dashboard_admin') }}?vista=reportes" class="sidebar-link {% if vista_activa == 'reportes' %}active{% endif %}">
            > Ver Reportes
        </a>
        <a href="{{ url_for('dashboard_admin') }}?vista=inventario" class="sidebar-link {% if vista_activa == 'inventario' %}active{% endif %}">
            > Ver Inventario
        </a>
        <a href="{{ url_for('dashboard_admin') }}?vista=solicitudes" class="sidebar-link {% if vista_activa == 'solicitudes' %}active{% endif %}">
            > Solicitudes Reseteo
        </a>
        
        <a href="/logout" class="sidebar-link logout">DESCONECTAR</a>
    </nav>

    <main class="main-content">
        <header class="header">
            <h2>TERMINAL DE ADMINISTRACIÓN</h2>
            <div style="display: flex; align-items: center;">
                <div class="user-info">
                    Usuario: <span>{{ username }}</span> // Nivel: <span>{{ role }}</span>
                </div>
                <div class="theme-toggle" id="theme-toggle">☀️</div>
            </div>
        </header>

        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="flash {{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        {% if vista_activa == 'crear' %}
        <div class="card">
            <h2>File: REGISTRO_NUEVO_SUJETO</h2>
            <form action="/crear" method="POST">
                <div class="form-layout">
                    <div class="form-group">
                        <label for="username">Designación</label>
                        <input type="text" id="username" name="username" required>
                    </div>
                    <div class="form-group">
                        <label for="password">Clave Acceso</label>
                        <input type="password" id="password" name="password" required>
                        <span class="password-toggle" onclick="togglePassword(this, 'password')">👁️</span>
                    </div>
                    <div class="form-group">
                        <label for="role">Nivel Autorización</label>
                        <select id="role" name="role">
                            {% for r in ROLES_LISTA %}
                            <option value="{{ r }}">{{ r.capitalize() }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <button type="submit" class="btn btn-green" style="height: 40px; margin-top: 25px;">Registrar</button>
                </div>
            </form>
        </div>
        {% endif %}

        {% if vista_activa == 'buscar' %}
        <div class="card">
            <h2>Query: BUSCAR_SUJETO</h2>
            <form action="{{ url_for('dashboard_admin') }}" method="GET">
                <input type="hidden" name="vista" value="buscar">
                <div class="form-layout" style="grid-template-columns: 3fr 1fr;">
                    <div class="form-group">
                        <label for="buscar_query">Entrar designación...</label>
                        <input type="text" id="buscar_query" name="buscar_query" value="{{ buscar_query }}">
                    </div>
                    <button type="submit" class="btn" style="margin-top: 25px;">Buscar</button>
                </div>
            </form>
        </div>
        {% endif %}

        {% if vista_activa == 'lista' or (vista_activa == 'buscar' and buscar_query) %}
        <div class="card">
            {% if vista_activa == 'lista' %} <h2>Log: BASE_DE_DATOS_SUJETOS</h2> {% else %} <h2>Result: RESULTADOS_BUSQUEDA</h2> {% endif %}
            <table class="user-table">
                <thead>
                    <tr>
                        <th>ID_SUJETO</th>
                        <th>Designación</th>
                        <th>Nivel Autorización</th>
                        <th>Acciones</th>
                    </tr>
                </thead>
                <tbody>
                    {% for user in users %}
                    <tr>
                        <td>{{ "%03d"|format(user.id) }}</td>
                        <td>{{ user.username }}</td>
                        <td>
                            <form action="/cambiar_rol" method="POST" class="form-layout">
                                <input type="hidden" name="user_id" value="{{ user.id }}">
                                <select name="new_role" {% if user.username == 'admin' %}disabled{% endif %}>
                                    {% for r in ROLES_LISTA %}
                                    <option value="{{ r }}" {% if user.role == r %}selected{% endif %}>
                                        {{ r.capitalize() }}
                                    </option>
                                    {% endfor %}
                                </select>
                                <button type="submit" class="btn btn-green" {% if user.username == 'admin' %}disabled{% endif %}>
                                    Actualizar
                                </button>
                            </form>
                        </td>
                        <td>
                            {% if user.username == 'admin' %}
                                <span class="action-btn disabled">(ADMIN_ROOT)</span>
                            {% else %}
                                <form action="/eliminar" method="POST" style="display:inline;">
                                    <input type="hidden" name="user_id" value="{{ user.id }}">
                                    <button type="submit" class="action-btn" onclick="return confirm('ALERTA: ¿Eliminar permanentemente al sujeto {{ user.username }}?');">
                                        Eliminar
                                    </button>
                                </form>
                                |
                                <a href="#" class="action-btn edit" onclick="openEditModal('{{ user.id }}', '{{ user.username }}')">
                                    Editar
                                </a>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}
        
        {% if vista_activa == 'reportes' %}
        <div class="card" id="ver-reportes">
            <h2>Log: REPORTES_ACTIVIDAD_RECIENTE (Acceso Total)</h2>
            <table class="user-table">
                <thead>
                    <tr><th>Autor</th><th>Asunto</th><th>Contenido</th><th>Fecha</th><th>Evidencia</th></tr>
                </thead>
                <tbody>
                    {% for reporte in reportes %}
                    <tr>
                        <td>{{ reporte.username }}</td>
                        <td>{{ reporte.titulo }}</td>
                        <td>{{ reporte.contenido }}</td>
                        <td>{{ reporte.fecha_creacion }}</td>
                        <td>
                            {% if reporte.imagen_base64 %}
                                <img src="data:image/jpeg;base64,{{ reporte.imagen_base64 }}" alt="Evidencia de reporte" class="report-image">
                            {% else %}
                                (Sin adjunto)
                            {% endif %}
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="5" style="text-align:center; color: var(--text-muted);">[ No hay reportes en el archivo ]</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}

        {% if vista_activa == 'inventario' %}
        <div class="card" id="inventario">
            <h2>Log: ITEMS_EN_CONTENCION (Control de Admin)</h2>
            <table class="user-table">
                <thead>
                    <tr>
                        <th>Item (Designación)</th>
                        <th>Descripción (Clase)</th>
                        <th>Stock Actual</th>
                        <th>Actualizar Stock</th>
                    </tr>
                </thead>
                <tbody>
                    {% for tool in inventario %}
                    <tr>
                        <td>{{ tool.nombre }}</td>
                        <td>{{ tool.descripcion }}</td>
                        <td><strong>{{ tool.stock }}</strong></td>
                        <td>
                            <form action="/agregar_stock" method="POST" class="form-layout" style="grid-template-columns: 1fr auto;">
                                <input type="hidden" name="tool_id" value="{{ tool.id }}">
                                <div class="form-group">
                                    <input type="number" name="cantidad" min="1" value="1" style="padding: 5px;">
                                </div>
                                <button type="submit" class="btn btn-green" style="padding: 5px 10px; height: 34px;">Agregar</button>
                            </form>
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="4" style="text-align:center; color: var(--text-muted);">[ Contención vacía ]</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}
        
        {% if vista_activa == 'solicitudes' %}
        <div class="card" id="ver-solicitudes">
            <h2>Query: SOLICITUDES_RESET_PENDIENTES</h2>
            <table class="user-table">
                <thead>
                    <tr>
                        <th>ID_Sujeto</th>
                        <th>Designación</th>
                        <th>Acción</th>
                    </tr>
                </thead>
                <tbody>
                    {% for s in solicitudes %}
                    <tr>
                        <td>{{ "%03d"|format(s.id) }}</td>
                        <td>{{ s.username }}</td>
                        <td>
                            <form action="/approve_reset" method="POST" style="display:inline;">
                                <input type="hidden" name="user_id" value="{{ s.id }}">
                                <button type="submit" class="btn btn-green">Autorizar Reseteo</button>
                            </form>
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="3" style="text-align:center; color: var(--text-muted);">[ No hay solicitudes pendientes ]</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}
        
    </main>

    <div id="editModal" class="modal">
        <div class="modal-content">
            <span class="modal-close" onclick="closeEditModal()">&times;</span>
            <h2>EDITAR DESIGNACIÓN DE SUJETO</h2>
            <form action="/editar_nombre" method="POST">
                <input type="hidden" id="modal_user_id" name="user_id">
                <div class="form-group" style="margin-top: 20px;">
                    <label for="modal_username">Nueva designación:</label>
                    <input type="text" id="modal_username" name="new_username" required>
                </div>
                <button type="submit" class="btn btn-green" style="margin-top: 20px;">Guardar Cambios</button>
            </form>
        </div>
    </div>
    
    <script id="global-scripts">
        var modal = document.getElementById("editModal");
        function openEditModal(id, username) {
            document.getElementById("modal_user_id").value = id;
            document.getElementById("modal_username").value = username;
            modal.style.display = "block";
        }
        function closeEditModal() { modal.style.display = "none"; }
        window.onclick = function(event) { if (event.target == modal) { modal.style.display = "none"; } }

        function togglePassword(eye, inputId) {
            const input = document.getElementById(inputId);
            if (input.type === 'password') {
                input.type = 'text';
                eye.textContent = '🙈';
            } else {
                input.type = 'password';
                eye.textContent = '👁️';
            }
        }
        
        const themeToggle = document.getElementById('theme-toggle');
        const html = document.documentElement;
        const currentTheme = localStorage.getItem('theme') || 'dark';
        html.setAttribute('data-theme', currentTheme);
        themeToggle.textContent = currentTheme === 'light' ? '🌙' : '☀️';
        themeToggle.addEventListener('click', () => {
            const newTheme = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            html.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            themeToggle.textContent = newTheme === 'light' ? '🌙' : '☀️';
        });
    </script>
</body>
</html>
"""

# --- Plantilla Supervisor (COMPLETA) ---
DASHBOARD_SUPERVISOR_TEMPLATE = """
<!DOCTYPE html>
<html lang="es" data-theme="dark">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Supervisor // Nivel 3</title>
    {{ DASHBOARD_BASE_STYLE|safe }}
</head>
<body>
    <nav class="sidebar">
        <h1>SUPERVISOR // Nv. 3</h1>
        <a href="{{ url_for('dashboard_supervisor') }}?vista=crear_reporte" class="sidebar-link {% if vista_activa == 'crear_reporte' %}active{% endif %}">
            > Crear Reporte
        </a>
        <a href="{{ url_for('dashboard_supervisor') }}?vista=ver_reportes" class="sidebar-link {% if vista_activa == 'ver_reportes' %}active{% endif %}">
            > Ver Reportes
        </a>
        <a href="{{ url_for('dashboard_supervisor') }}?vista=ver_obreros" class="sidebar-link {% if vista_activa == 'ver_obreros' %}active{% endif %}">
            > Ver Unidades
        </a>
        <a href="{{ url_for('dashboard_supervisor') }}?vista=ver_bodega" class="sidebar-link {% if vista_activa == 'ver_bodega' %}active{% endif %}">
            > Ver Contención
        </a>
        <a href="/logout" class="sidebar-link logout">DESCONECTAR</a>
    </nav>
    <main class="main-content">
        <header class="header">
            <h2>TERMINAL DE SUPERVISIÓN</h2>
            <div style="display: flex; align-items: center;">
                <div class="user-info">
                    Usuario: <span>{{ username }}</span> // Nivel: <span>{{ role }}</span>
                </div>
                <div class="theme-toggle" id="theme-toggle">☀️</div>
            </div>
        </header>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="flash {{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        {% if vista_activa == 'crear_reporte' %}
        <div class="card" id="crear-reporte">
            <h2>File: NUEVO_REPORTE_ACTIVIDAD</h2>
            <form action="/crear_reporte" method="POST" enctype="multipart/form-data">
                <div class="form-group" style="margin-bottom: 15px;">
                    <label for="titulo">Asunto del Reporte</label>
                    <input type="text" id="titulo" name="titulo" required>
                </div>
                <div class="form-group" style="margin-bottom: 15px;">
                    <label for="contenido">Contenido</label>
                    <textarea id="contenido" name="contenido" required></textarea>
                </div>
                <div class="form-group" style="margin-bottom: 15px;">
                    <label for="imagen">Adjuntar Evidencia (Opcional, max 5MB)</label>
                    <input type="file" id="imagen" name="imagen" accept="image/*">
                </div>
                <button type="submit" class="btn btn-green">Archivar Reporte</button>
            </form>
        </div>
        {% endif %}

        {% if vista_activa == 'ver_reportes' %}
        <div class="card" id="ver-reportes">
            <h2>Log: REPORTES_ACTIVIDAD_RECIENTE</h2>
            <table class="user-table">
                <thead>
                    <tr><th>Autor</th><th>Asunto</th><th>Contenido</th><th>Fecha</th><th>Evidencia</th></tr>
                </thead>
                <tbody>
                    {% for reporte in reportes %}
                    <tr>
                        <td>{{ reporte.username }}</td>
                        <td>{{ reporte.titulo }}</td>
                        <td>{{ reporte.contenido }}</td>
                        <td>{{ reporte.fecha_creacion }}</td>
                        <td>
                            {% if reporte.imagen_base64 %}
                                <img src="data:image/jpeg;base64,{{ reporte.imagen_base64 }}" alt="Evidencia de reporte" class="report-image">
                            {% else %}
                                (Sin adjunto)
                            {% endif %}
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="5" style="text-align:center; color: var(--text-muted);">[ No hay reportes en el archivo ]</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}

        {% if vista_activa == 'ver_obreros' %}
        <div class="card" id="ver-obreros">
            <h2>List: UNIDADES_OBREROS_ASIGNADAS</h2>
            <table class="user-table">
                <thead>
                    <tr><th>ID_Sujeto</th><th>Designación</th></tr>
                </thead>
                <tbody>
                    {% for obrero in obreros %}
                    <tr>
                        <td>{{ "%03d"|format(obrero.id) }}</td>
                        <td>{{ obrero.username }}</td>
                    </tr>
                    {% else %}
                    <tr><td colspan="2" style="text-align:center; color: var(--text-muted);">[ No hay unidades asignadas ]</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}
        
        {% if vista_activa == 'ver_bodega' %}
        <div class="card" id="ver-bodega">
            <h2>Log: ESTADO_CONTENCION (Solo Lectura)</h2>
            <table class="user-table">
                <thead>
                    <tr>
                        <th>Item (Designación)</th>
                        <th>Descripción (Clase)</th>
                        <th>Stock Actual</th>
                    </tr>
                </thead>
                <tbody>
                    {% for tool in stock_bodega %}
                    <tr>
                        <td>{{ tool.nombre }}</td>
                        <td>{{ tool.descripcion }}</td>
                        <td><strong>{{ tool.stock }}</strong></td>
                    </tr>
                    {% else %}
                    <tr><td colspan="3" style="text-align:center; color: var(--text-muted);">[ Contención vacía ]</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}
    </main>
    
    <script id="global-theme-script">
        const themeToggle = document.getElementById('theme-toggle');
        const html = document.documentElement;
        const currentTheme = localStorage.getItem('theme') || 'dark';
        html.setAttribute('data-theme', currentTheme);
        themeToggle.textContent = currentTheme === 'light' ? '🌙' : '☀️';
        themeToggle.addEventListener('click', () => {
            const newTheme = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            html.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            themeToggle.textContent = newTheme === 'light' ? '🌙' : '☀️';
        });
    </script>
</body>
</html>
"""

# --- Plantilla Bodeguero (COMPLETA) ---
DASHBOARD_BODEGUERO_TEMPLATE = """
<!DOCTYPE html>
<html lang="es" data-theme="dark">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bodega // Nivel 2</title>
    {{ DASHBOARD_BASE_STYLE|safe }}
</head>
<body>
    <nav class="sidebar">
        <h1>BODEGA // Nv. 2</h1>
        <a href="{{ url_for('dashboard_bodeguero') }}?vista=inventario" class="sidebar-link {% if vista_activa == 'inventario' %}active{% endif %}">
            > Inventario Contención
        </a>
        <a href="/logout" class="sidebar-link logout">DESCONECTAR</a>
    </nav>
    <main class="main-content">
        <header class="header">
            <h2>TERMINAL DE CONTENCIÓN</h2>
            <div style="display: flex; align-items: center;">
                <div class="user-info">
                    Usuario: <span>{{ username }}</span> // Nivel: <span>{{ role }}</span>
                </div>
                <div class="theme-toggle" id="theme-toggle">☀️</div>
            </div>
        </header>

        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="flash {{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        <div class="card" id="inventario">
            <h2>Log: ITEMS_EN_CONTENCION</h2>
            <table class="user-table">
                <thead>
                    <tr>
                        <th>Item (Designación)</th>
                        <th>Descripción (Clase)</th>
                        <th>Stock Actual</th>
                        <th>Actualizar Stock</th>
                    </tr>
                </thead>
                <tbody>
                    {% for tool in inventario %}
                    <tr>
                        <td>{{ tool.nombre }}</td>
                        <td>{{ tool.descripcion }}</td>
                        <td><strong>{{ tool.stock }}</strong></td>
                        <td>
                            <form action="/agregar_stock" method="POST" class="form-layout" style="grid-template-columns: 1fr auto;">
                                <input type="hidden" name="tool_id" value="{{ tool.id }}">
                                <div class="form-group">
                                    <input type="number" name="cantidad" min="1" value="1" style="padding: 5px;">
                                </div>
                                <button type="submit" class="btn btn-green" style="padding: 5px 10px; height: 34px;">Agregar</button>
                            </form>
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="4" style="text-align:center; color: var(--text-muted);">[ Contención vacía ]</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </main>
    <script id="global-theme-script">
        const themeToggle = document.getElementById('theme-toggle');
        const html = document.documentElement;
        const currentTheme = localStorage.getItem('theme') || 'dark';
        html.setAttribute('data-theme', currentTheme);
        themeToggle.textContent = currentTheme === 'light' ? '🌙' : '☀️';
        themeToggle.addEventListener('click', () => {
            const newTheme = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            html.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            themeToggle.textContent = newTheme === 'light' ? '🌙' : '☀️';
        });
    </script>
</body>
</html>
"""

# --- Plantilla Obrero (COMPLETA) ---
DASHBOARD_OBRERO_TEMPLATE = """
<!DOCTYPE html>
<html lang="es" data-theme="dark">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Obrero // Nivel 1</title>
    {{ DASHBOARD_BASE_STYLE|safe }}
</head>
<body>
    <nav class="sidebar">
        <h1>OBRERO // Nv. 1</h1>
        <a href="{{ url_for('dashboard_obrero') }}?vista=pedir" class="sidebar-link {% if vista_activa == 'pedir' %}active{% endif %}">
            > Solicitar Equipo
        </a>
        <a href="{{ url_for('dashboard_obrero') }}?vista=reporte" class="sidebar-link {% if vista_activa == 'reporte' %}active{% endif %}">
            > Crear Reporte Diario
        </a>
        <a href="/logout" class="sidebar-link logout">DESCONECTAR</a>
    </nav>
    <main class="main-content">
        <header class="header">
            <h2>TERMINAL DE UNIDAD</h2>
            <div style="display: flex; align-items: center;">
                <div class="user-info">
                    Usuario: <span>{{ username }}</span> // Nivel: <span>{{ role }}</span>
                </div>
                <div class="theme-toggle" id="theme-toggle">☀️</div>
            </div>
        </header>

        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="flash {{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        {% if vista_activa == 'pedir' %}
        <div class="card" id="pedir-herramienta">
            <h2>Form: SOLICITUD_EQUIPO</h2>
            <table class="user-table">
                <thead>
                    <tr>
                        <th>Item</th>
                        <th>Stock Disponible</th>
                        <th>Acción</th>
                    </tr>
                </thead>
                <tbody>
                    {% for tool in herramientas %}
                    <tr>
                        <td>{{ tool.nombre }}</td>
                        <td>{{ tool.stock }}</td>
                        <td>
                            <form action="/pedir_herramienta" method="POST">
                                <input type="hidden" name="tool_id" value="{{ tool.id }}">
                                <button type="submit" class="btn" style="height: 34px;">Solicitar</button>
                            </form>
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="3" style="text-align:center; color: var(--text-muted);">[ No hay equipo disponible ]</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}

        {% if vista_activa == 'reporte' %}
        <div class="card" id="crear-reporte">
            <h2>File: REPORTE_DIARIO</h2>
            <form action="/crear_reporte" method="POST" enctype="multipart/form-data">
                <div class="form-group" style="margin-bottom: 15px;">
                    <label for="titulo">Asunto (Ej: Tarea del día)</label>
                    <input type="text" id="titulo" name="titulo" required>
                </div>
                <div class="form-group" style="margin-bottom: 15px;">
                    <label for="contenido">Descripción del trabajo realizado</label>
                    <textarea id="contenido" name="contenido" required></textarea>
                </div>
                <div class="form-group" style="margin-bottom: 15px;">
                    <label for="imagen">Adjuntar Evidencia (Opcional, max 5MB)</label>
                    <input type="file" id="imagen" name="imagen" accept="image/*">
                </div>
                <button type="submit" class="btn btn-green">Archivar Reporte</button>
            </form>
        </div>
        {% endif %}
    </main>
    <script id="global-theme-script">
        const themeToggle = document.getElementById('theme-toggle');
        const html = document.documentElement;
        const currentTheme = localStorage.getItem('theme') || 'dark';
        html.setAttribute('data-theme', currentTheme);
        themeToggle.textContent = currentTheme === 'light' ? '🌙' : '☀️';
        themeToggle.addEventListener('click', () => {
            const newTheme = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            html.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            themeToggle.textContent = newTheme === 'light' ? '🌙' : '☀️';
        });
    </script>
</body>
</html>
"""

# --- [NUEVAS] PLANTILLAS DE RESETEO DE CONTRASEÑA (COMPLETAS) ---

RESET_REQUEST_TEMPLATE = """
<!DOCTYPE html>
<html lang="es" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Solicitar Reseteo</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Roboto+Mono:wght@400;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color-dark: #000;
            --bg-card-dark: rgba(0, 0, 0, 0.85);
            --text-color-dark: #eeeeee;
            --text-muted-dark: #aaa;
            --border-color-dark: #333;
            --border-accent-dark: #c0392b;
            --primary-dark: #c0392b;
            --primary-hover-dark: transparent;
            --primary-hover-text-dark: #c0392b;
            --input-bg-dark: #1a1a1a;
            --bg-color-light: #f0f2f5;
            --bg-card-light: #ffffff;
            --text-color-light: #222222;
            --text-muted-light: #555;
            --border-color-light: #dddddd;
            --border-accent-light: #007bff;
            --primary-light: #007bff;
            --primary-hover-light: #0056b3;
            --primary-hover-text-light: #ffffff;
            --input-bg-light: #ffffff;
            --bg-color: var(--bg-color-dark);
            --bg-card: var(--bg-card-dark);
            --text-color: var(--text-color-dark);
            --text-muted: var(--text-muted-dark);
            --border-color: var(--border-color-dark);
            --primary: var(--primary-dark);
            --primary-hover: var(--primary-hover-dark);
            --primary-hover-text: var(--primary-hover-text-dark);
            --input-bg: var(--input-bg-dark);
        }
        [data-theme="light"] {
            --bg-color: var(--bg-color-light);
            --bg-card: var(--bg-card-light);
            --text-color: var(--text-color-light);
            --text-muted: var(--text-muted-light);
            --border-color: var(--border-color-light);
            --primary: var(--primary-light);
            --primary-hover: var(--primary-hover-light);
            --primary-hover-text: var(--primary-hover-text-light);
            --input-bg: var(--input-bg-light);
        }
        body {
            font-family: 'Roboto Mono', 'Consolas', monospace;
            background-color: var(--bg-color);
            color: var(--text-color);
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            transition: background-color 0.3s;
        }
        .login-card {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            padding: 2.5rem;
            border-radius: 4px;
            width: 100%;
            max-width: 400px;
            box-sizing: border-box;
            text-align: center;
        }
        .login-card h1 {
            color: var(--text-color);
            margin-top: 0;
            margin-bottom: 1.5rem;
            font-size: 1.2rem;
            font-weight: 700;
            text-transform: uppercase;
        }
        .login-card p {
            font-size: 0.9rem;
            color: var(--text-muted);
            margin-bottom: 1.5rem;
        }
        .form-group {
            margin-bottom: 1.25rem;
            text-align: left;
        }
        .form-group label {
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 400;
            color: var(--text-muted);
            text-transform: uppercase;
            font-size: 0.8rem;
        }
        .form-group input {
            width: 100%;
            padding: 0.75rem;
            border: 1px solid var(--border-color);
            background-color: var(--input-bg);
            border-radius: 2px;
            box-sizing: border-box;
            font-size: 1rem;
            color: var(--text-color);
            font-family: 'Roboto Mono', 'Consolas', monospace;
        }
        .btn {
            width: 100%;
            padding: 0.85rem;
            border: 1px solid var(--primary);
            border-radius: 2px;
            background-color: var(--primary);
            color: white !important;
            font-size: 1rem;
            font-weight: 700;
            cursor: pointer;
            transition: background-color 0.2s, color 0.2s;
            text-transform: uppercase;
        }
        .btn:hover {
            background-color: var(--primary-hover);
            color: var(--primary-hover-text) !important;
        }
        .back-link {
            display: block;
            text-align: center;
            font-size: 0.9rem;
            color: var(--text-muted);
            text-decoration: none;
            margin-top: 1.5rem;
        }
        .theme-toggle {
            position: absolute;
            top: 20px;
            right: 20px;
            cursor: pointer;
            font-size: 1.5rem;
            color: var(--text-muted);
        }
    </style>
</head>
<body>
    <div class="theme-toggle" id="theme-toggle">☀️</div>
    <div class="login-card">
        <h1>Solicitar Reseteo de Contraseña</h1>
        <p>Ingrese su nombre de usuario. Si existe, se enviará una solicitud de reseteo a un administrador.</p>
        
        <form action="/reset_request" method="POST">
            <div class="form-group">
                <label for="username">Designación de Usuario</label>
                <input type="text" id="username" name="username" required>
            </div>
            <button type="submit" class="btn">Enviar Solicitud</button>
        </form>
        
        <a href="{{ url_for('login') }}" class="back-link">&lt; Volver al Login</a>
    </div>
    <script>
        const themeToggle = document.getElementById('theme-toggle');
        const html = document.documentElement;
        const currentTheme = localStorage.getItem('theme') || 'dark';
        html.setAttribute('data-theme', currentTheme);
        themeToggle.textContent = currentTheme === 'light' ? '🌙' : '☀️';
        themeToggle.addEventListener('click', () => {
            const newTheme = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            html.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            themeToggle.textContent = newTheme === 'light' ? '🌙' : '☀️';
        });
    </script>
</body>
</html>
"""

# --- ¡NUEVA! Plantilla de Sala de Espera (COMPLETA) ---
WAITING_TEMPLATE = """
<!DOCTYPE html>
<html lang="es" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Esperando Aprobación...</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Roboto+Mono:wght@400;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color-dark: #000;
            --bg-card-dark: rgba(0, 0, 0, 0.85);
            --text-color-dark: #eeeeee;
            --text-muted-dark: #aaa;
            --border-color-dark: #333;
            --primary-dark: #c0392b;
            --bg-color-light: #f0f2f5;
            --bg-card-light: #ffffff;
            --text-color-light: #222222;
            --text-muted-light: #555;
            --border-color-light: #dddddd;
            --primary-light: #007bff;
            --bg-color: var(--bg-color-dark);
            --bg-card: var(--bg-card-dark);
            --text-color: var(--text-color-dark);
            --text-muted: var(--text-muted-dark);
            --border-color: var(--border-color-dark);
            --primary: var(--primary-dark);
        }
        [data-theme="light"] {
            --bg-color: var(--bg-color-light);
            --bg-card: var(--bg-card-light);
            --text-color: var(--text-color-light);
            --text-muted: var(--text-muted-light);
            --border-color: var(--border-color-light);
            --primary: var(--primary-light);
        }
        body {
            font-family: 'Roboto Mono', 'Consolas', monospace;
            background-color: var(--bg-color);
            color: var(--text-color);
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            transition: background-color 0.3s;
        }
        .login-card {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            padding: 2.5rem;
            border-radius: 4px;
            width: 100%;
            max-width: 450px;
            box-sizing: border-box;
            text-align: center;
        }
        .login-card h1 {
            color: var(--text-color);
            margin-top: 0;
            margin-bottom: 1.5rem;
            font-size: 1.2rem;
            font-weight: 700;
            text-transform: uppercase;
        }
        .login-card p {
            font-size: 0.9rem;
            color: var(--text-muted);
            margin-bottom: 1.5rem;
        }
        .login-card span {
            color: var(--primary);
            font-weight: 700;
        }
        .loader {
            font-size: 1.5rem;
            color: var(--text-color);
        }
        .theme-toggle {
            position: absolute;
            top: 20px;
            right: 20px;
            cursor: pointer;
            font-size: 1.5rem;
            color: var(--text-muted);
        }
    </style>
</head>
<body>
    <div class="theme-toggle" id="theme-toggle">☀️</div>
    <div class="login-card">
        <h1>Solicitud Enviada</h1>
        <p>Esperando autorización del administrador para el usuario <span>{{ username }}</span>.</p>
        <p>Por favor, mantenga esta página abierta.</p>
        <div class="loader" id="loader">Contactando servidor...</div>
    </div>
    <script>
        const themeToggle = document.getElementById('theme-toggle');
        const html = document.documentElement;
        const currentTheme = localStorage.getItem('theme') || 'dark';
        html.setAttribute('data-theme', currentTheme);
        themeToggle.textContent = currentTheme === 'light' ? '🌙' : '☀️';
        themeToggle.addEventListener('click', () => {
            const newTheme = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            html.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            themeToggle.textContent = newTheme === 'light' ? '🌙' : '☀️';
        });

        const loader = document.getElementById('loader');
        let dots = 0;

        setInterval(() => {
            dots = (dots + 1) % 4;
            loader.textContent = "Esperando aprobación" + ".".repeat(dots);
        }, 1000);

        const pollInterval = setInterval(async () => {
            try {
                const response = await fetch("{{ url_for('check_approval_status', username=username) }}");
                const data = await response.json();

                if (data.status === 'approved') {
                    clearInterval(pollInterval);
                    loader.textContent = "¡Aprobado! Redirigiendo...";
                    window.location.href = data.redirect_url;
                }
            } catch (error) {
                loader.textContent = "Error de conexión...";
            }
        }, 5000); 
    </script>
</body>
</html>
"""

# --- Plantilla Force Reset (COMPLETA) ---
FORCE_RESET_TEMPLATE = """
<!DOCTYPE html>
<html lang="es" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Establecer Nueva Contraseña</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Roboto+Mono:wght@400;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color-dark: #000;
            --bg-card-dark: rgba(0, 0, 0, 0.85);
            --text-color-dark: #eeeeee;
            --text-muted-dark: #aaa;
            --border-color-dark: #333;
            --border-accent-dark: #c0392b;
            --primary-dark: #c0392b;
            --primary-hover-dark: transparent;
            --primary-hover-text-dark: #c0392b;
            --input-bg-dark: #1a1a1a;
            --error-bg-dark: #4d0000;
            --error-border-dark: #c0392b;
            --bg-color-light: #f0f2f5;
            --bg-card-light: #ffffff;
            --text-color-light: #222222;
            --text-muted-light: #555;
            --border-color-light: #dddddd;
            --border-accent-light: #007bff;
            --primary-light: #007bff;
            --primary-hover-light: #0056b3;
            --primary-hover-text-light: #ffffff;
            --input-bg-light: #ffffff;
            --error-bg-light: #f8d7da;
            --error-border-light: #f5c6cb;
            --bg-color: var(--bg-color-dark);
            --bg-card: var(--bg-card-dark);
            --text-color: var(--text-color-dark);
            --text-muted: var(--text-muted-dark);
            --border-color: var(--border-color-dark);
            --primary: var(--primary-dark);
            --primary-hover: var(--primary-hover-dark);
            --primary-hover-text: var(--primary-hover-text-dark);
            --input-bg: var(--input-bg-dark);
            --error-bg: var(--error-bg-dark);
            --error-border: var(--error-border-dark);
        }
        [data-theme="light"] {
            --bg-color: var(--bg-color-light);
            --bg-card: var(--bg-card-light);
            --text-color: var(--text-color-light);
            --text-muted: var(--text-muted-light);
            --border-color: var(--border-color-light);
            --primary: var(--primary-light);
            --primary-hover: var(--primary-hover-light);
            --primary-hover-text: var(--primary-hover-text-light);
            --input-bg: var(--input-bg-light);
            --error-bg: var(--error-bg-light);
            --error-border: var(--error-border-light);
        }
        body {
            font-family: 'Roboto Mono', 'Consolas', monospace;
            background-color: var(--bg-color);
            color: var(--text-color);
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
        }
        .login-card {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            padding: 2.5rem;
            border-radius: 4px;
            width: 100%;
            max-width: 400px;
            box-sizing: border-box;
            text-align: center;
        }
        .login-card h1 {
            color: var(--text-color);
            margin-top: 0;
            margin-bottom: 1.5rem;
            font-size: 1.2rem;
            font-weight: 700;
            text-transform: uppercase;
        }
        .form-group {
            margin-bottom: 1.25rem;
            text-align: left;
            position: relative;
        }
        .form-group label {
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 400;
            color: var(--text-muted);
            text-transform: uppercase;
            font-size: 0.8rem;
        }
        .form-group input {
            width: 100%;
            padding: 0.75rem 40px 0.75rem 0.75rem;
            border: 1px solid var(--border-color);
            background-color: var(--input-bg);
            border-radius: 2px;
            box-sizing: border-box;
            font-size: 1rem;
            color: var(--text-color);
            font-family: 'Roboto Mono', 'Consolas', monospace;
        }
        .password-toggle {
            position: absolute;
            right: 10px;
            top: 35px;
            cursor: pointer;
            color: var(--text-muted);
            user-select: none;
            font-size: 1.2rem;
        }
        .btn {
            width: 100%;
            padding: 0.85rem;
            border: 1px solid var(--primary);
            border-radius: 2px;
            background-color: var(--primary);
            color: white !important;
            font-size: 1rem;
            font-weight: 700;
            cursor: pointer;
            text-transform: uppercase;
        }
        .flash {
            padding: 0.8rem; margin-bottom: 1rem; border-radius: 2px;
            font-weight: 700; text-align: center; font-size: 0.9rem;
            border: 1px solid;
        }
        .flash.error {
            background-color: var(--error-bg);
            border-color: var(--error-border);
            color: var(--primary);
        }
        [data-theme="light"] .flash.error { color: #721c24; }
        .theme-toggle {
            position: absolute;
            top: 20px;
            right: 20px;
            cursor: pointer;
            font-size: 1.5rem;
            color: var(--text-muted);
        }
    </style>
</head>
<body>
    <div class="theme-toggle" id="theme-toggle">☀️</div>
    <div class="login-card">
        <h1>Establecer Nueva Contraseña</h1>
        <p style="color: var(--text-muted);">Usuario: {{ username }}</p>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="flash {{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <form action="/handle_public_reset" method="POST">
            <input type="hidden" name="username" value="{{ username }}">
            
            <div class="form-group">
                <label for="new_password">Contraseña Nueva</label>
                <input type="password" id="new_password" name="new_password" required>
                <span class="password-toggle" onclick="togglePassword(this, 'new_password')">👁️</span>
            </div>
            <div class="form-group">
                <label for="confirm_password">Volver a colocar la Contraseña Nueva</label>
                <input type="password" id="confirm_password" name="confirm_password" required>
                <span class="password-toggle" onclick="togglePassword(this, 'confirm_password')">👁️</span>
            </div>
            <button type="submit" class="btn">Establecer Nueva Contraseña</button>
        </form>
    </div>
    <script>
        function togglePassword(eye, inputId) {
            const input = document.getElementById(inputId);
            if (input.type === 'password') {
                input.type = 'text';
                eye.textContent = '🙈';
            } else {
                input.type = 'password';
                eye.textContent = '👁️';
            }
        }
        const themeToggle = document.getElementById('theme-toggle');
        const html = document.documentElement;
        const currentTheme = localStorage.getItem('theme') || 'dark';
        html.setAttribute('data-theme', currentTheme);
        themeToggle.textContent = currentTheme === 'light' ? '🌙' : '☀️';
        themeToggle.addEventListener('click', () => {
            const newTheme = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            html.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            themeToggle.textContent = newTheme === 'light' ? '🌙' : '☀️';
        });
    </script>
</body>
</html>
"""


# --- Punto de Entrada Principal ---
if __name__ == '__main__':
    # Esta función SÍ debe llamarse aquí.
    # Gunicorn no la llamará, pero si ejecutas 
    # 'python admin_usuarios_web.py' localmente,
    # SÍ la llamará, creando tu BD local.
    init_db() 
    
    host_ip = '0.0.0.0' 
    print(f"Iniciando servidor web en http://{host_ip}:5000")
    print("SCP Secure Terminal está en línea. Accesible en la red local.")
    print("Presiona CTRL+C para apagar el servidor.")
    
    app.run(debug=True, port=5000, host=host_ip)
