from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, make_response
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import hashlib
from config import Config
import os
import json
import datetime

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'docx', 'txt', 'xlsx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

app = Flask(__name__)
app.config.from_object(Config)
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

DB_FILE = 'blockchain_identity.db'

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# ── Database Init ──────────────────────────────────────────────────────────────

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name   TEXT NOT NULL,
        email       TEXT UNIQUE NOT NULL,
        employee_id TEXT UNIQUE NOT NULL,
        department  TEXT,
        role        TEXT DEFAULT 'Employee',
        password_hash TEXT NOT NULL,
        account_status TEXT DEFAULT 'Active',
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS identities (
        identity_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER,
        blockchain_hash TEXT UNIQUE NOT NULL,
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )''')
    # Multi-step approval: Pending_Manager → Pending_Admin → Approved / Rejected
    c.execute('''CREATE TABLE IF NOT EXISTS access_requests (
        request_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER,
        resource_name TEXT NOT NULL,
        reason        TEXT,
        status        TEXT DEFAULT 'Pending_Manager',
        manager_note  TEXT,
        admin_note    TEXT,
        blockchain_tx TEXT,
        request_date  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at    TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS audit_logs (
        log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER,
        action      TEXT NOT NULL,
        details     TEXT,
        blockchain_transaction_hash TEXT,
        timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS documents (
        doc_id      INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER,
        doc_name    TEXT NOT NULL,
        ipfs_hash   TEXT NOT NULL,
        doc_type    TEXT,
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
        task_id       INTEGER PRIMARY KEY AUTOINCREMENT,
        assigned_by   INTEGER,
        assigned_to   INTEGER,
        task_title    TEXT NOT NULL,
        task_desc     TEXT,
        status        TEXT DEFAULT 'Pending',
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at  TIMESTAMP,
        FOREIGN KEY (assigned_by) REFERENCES users(user_id),
        FOREIGN KEY (assigned_to) REFERENCES users(user_id)
    )''')
    conn.commit()
    conn.close()

# ── Seed Sample Data ───────────────────────────────────────────────────────────

def seed_data():
    conn = get_db_connection()
    existing = conn.execute('SELECT COUNT(*) as c FROM users').fetchone()['c']
    if existing > 0:
        conn.close()
        return
    sample_users = [
        ('Alice Johnson', 'alice@accessledger.io', 'EMP001', 'Engineering', 'Admin',    'Admin@123'),
        ('Bob Smith',     'bob@accessledger.io',   'EMP002', 'HR',          'Manager',  'Bob@1234'),
        ('Carol White',   'carol@accessledger.io', 'EMP003', 'Finance',     'Manager',  'Carol123'),
        ('David Lee',     'david@accessledger.io', 'EMP004', 'HR',          'Employee', 'David123'),
        ('Eva Martinez',  'eva@accessledger.io',   'EMP005', 'Finance',     'Employee', 'Eva@1234'),
        ('Frank Nguyen',  'frank@accessledger.io', 'EMP006', 'Engineering', 'Employee', 'Frank123'),
    ]
    c = conn.cursor()
    for name, email, emp_id, dept, role, pwd in sample_users:
        ph = generate_password_hash(pwd)
        c.execute('INSERT INTO users (full_name,email,employee_id,department,role,password_hash,account_status) VALUES (?,?,?,?,?,?,?)',
                  (name, email, emp_id, dept, role, ph, 'Active'))
        uid = c.lastrowid
        h = 'Qm' + hashlib.sha256(f"{email}{emp_id}{role}".encode()).hexdigest()[:44]
        c.execute('INSERT INTO identities (user_id,blockchain_hash) VALUES (?,?)', (uid, h))
    conn.commit()

    sample_requests = [
        (4, 'HR Portal',         'Need access for employee onboarding',  'Approved',       'Looks good','Verified',  '0x' + 'a'*40),
        (5, 'Finance Dashboard', 'Monthly report generation',            'Pending_Admin',  'Approved by manager', '', None),
        (6, 'Dev Repo',          'Need source code access for project',  'Pending_Manager','', '', None),
        (4, 'Payroll System',    'Process salary adjustments',           'Rejected',       'Not justified','',None),
        (5, 'Analytics Tool',    'Data visualization for Q4 review',     'Pending_Manager','', '', None),
    ]
    for uid, res, reason, status, mnote, anote, tx in sample_requests:
        c.execute('INSERT INTO access_requests (user_id,resource_name,reason,status,manager_note,admin_note,blockchain_tx) VALUES (?,?,?,?,?,?,?)',
                  (uid, res, reason, status, mnote, anote, tx))
    conn.commit()

    sample_actions = [
        (1,'USER_REGISTERED','Alice Johnson registered as Admin'),
        (2,'USER_REGISTERED','Bob Smith registered as Manager'),
        (3,'USER_REGISTERED','Carol White registered as Manager'),
        (4,'USER_REGISTERED','David Lee registered as Employee'),
        (1,'USER_LOGIN','Admin login'),
        (2,'ACCESS_APPROVED','Manager approved HR Portal for David Lee'),
        (1,'ACCESS_APPROVED','Admin verified HR Portal — TX stored on blockchain'),
        (4,'DOCUMENT_UPLOADED','Security Policy v2.pdf uploaded → IPFS'),
        (5,'ACCESS_REQUESTED','Eva Martinez requested Finance Dashboard'),
        (6,'ACCESS_REQUESTED','Frank Nguyen requested Dev Repo access'),
    ]
    for uid, action, details in sample_actions:
        tx = '0x' + hashlib.sha256(f"{uid}{action}{details}".encode()).hexdigest()[:40]
        c.execute('INSERT INTO audit_logs (user_id,action,details,blockchain_transaction_hash) VALUES (?,?,?,?)',
                  (uid, action, details, tx))
    conn.commit()
    conn.close()

# ── Helpers ────────────────────────────────────────────────────────────────────

def log_action(user_id, action, details=""):
    tx = "0x" + hashlib.sha256(f"{user_id}{action}{datetime.datetime.now()}".encode()).hexdigest()[:40]
    conn = get_db_connection()
    conn.execute('INSERT INTO audit_logs (user_id,action,details,blockchain_transaction_hash) VALUES (?,?,?,?)',
                 (user_id, action, details, tx))
    conn.commit()
    conn.close()
    return tx

from functools import wraps

def login_required(f):
    @wraps(f)
    def decorated(*a, **kw):
        if 'user_id' not in session:
            flash('Please log in first.', 'warning')
            return redirect(url_for('login'))
        return f(*a, **kw)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*a, **kw):
        if session.get('role') != 'Admin':
            flash('Admin access required.', 'danger')
            return redirect(url_for('login'))
        return f(*a, **kw)
    return decorated

def manager_required(f):
    @wraps(f)
    def decorated(*a, **kw):
        if session.get('role') not in ('Admin', 'Manager'):
            flash('Manager access required.', 'danger')
            return redirect(url_for('login'))
        return f(*a, **kw)
    return decorated

init_db()
seed_data()

# ── Public Routes ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

# ── Register ───────────────────────────────────────────────────────────────────

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        full_name    = request.form['full_name']
        email        = request.form['email']
        employee_id  = request.form['employee_id']
        department   = request.form['department']
        role         = request.form['role']
        password     = request.form['password']
        confirm_pass = request.form.get('confirm_password', '')
        if password != confirm_pass:
            flash('Passwords do not match!', 'danger')
            return redirect(url_for('register'))
        hashed = generate_password_hash(password)
        h = 'Qm' + hashlib.sha256(f"{email}{employee_id}{role}".encode()).hexdigest()[:44]
        conn = get_db_connection()
        try:
            conn.execute(
                'INSERT INTO users (full_name,email,employee_id,department,role,password_hash,account_status) VALUES (?,?,?,?,?,?,?)',
                (full_name, email, employee_id, department, role, hashed, 'Pending'))
            uid = conn.execute('SELECT last_insert_rowid() as id').fetchone()['id']
            conn.execute('INSERT INTO identities (user_id,blockchain_hash) VALUES (?,?)', (uid, h))
            conn.commit()
            log_action(uid, "USER_REGISTERED", f"{full_name} registered — Pending admin approval")
            flash('Registration submitted! Awaiting Admin approval.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Email or Employee ID already exists.', 'danger')
        finally:
            conn.close()
    return render_template('register.html')

# ── Login ──────────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form['email']
        password = request.form['password']
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password_hash'], password):
            if user['account_status'] == 'Pending':
                flash('Your account is pending Admin approval.', 'warning')
                return redirect(url_for('login'))
            if user['account_status'] == 'Suspended':
                flash('Your account has been suspended. Contact Admin.', 'danger')
                return redirect(url_for('login'))
            session['user_id']   = user['user_id']
            session['role']      = user['role']
            session['full_name'] = user['full_name']
            session['email']     = user['email']
            session['dept']      = user['department']
            log_action(user['user_id'], "USER_LOGIN", f"{user['full_name']} logged in")
            if user['role'] == 'Admin':
                return redirect(url_for('admin_dashboard'))
            if user['role'] == 'Manager':
                return redirect(url_for('manager_dashboard'))
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html')

# ── Employee Dashboard ─────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()
    user        = conn.execute('SELECT * FROM users WHERE user_id=?', (session['user_id'],)).fetchone()
    identity    = conn.execute('SELECT * FROM identities WHERE user_id=?', (session['user_id'],)).fetchone()
    my_requests = conn.execute(
        'SELECT * FROM access_requests WHERE user_id=? ORDER BY request_date DESC LIMIT 10',
        (session['user_id'],)).fetchall()
    recent_logs = conn.execute(
        'SELECT * FROM audit_logs WHERE user_id=? ORDER BY timestamp DESC LIMIT 6',
        (session['user_id'],)).fetchall()
    documents   = conn.execute(
        'SELECT * FROM documents WHERE user_id=? ORDER BY uploaded_at DESC',
        (session['user_id'],)).fetchall()
    my_tasks    = conn.execute(
        'SELECT * FROM tasks WHERE assigned_to=? ORDER BY created_at DESC',
        (session['user_id'],)).fetchall()
    conn.close()
    return render_template('dashboard.html', user=user, identity=identity,
                           my_requests=my_requests, recent_logs=recent_logs, documents=documents, my_tasks=my_tasks)

# ── Employee: Request Access ───────────────────────────────────────────────────

@app.route('/access_request', methods=['GET', 'POST'])
@login_required
def access_request():
    if request.method == 'POST':
        resource_name = request.form['resource_name']
        reason        = request.form.get('reason', '')
        conn = get_db_connection()
        conn.execute(
            'INSERT INTO access_requests (user_id,resource_name,reason,status) VALUES (?,?,?,?)',
            (session['user_id'], resource_name, reason, 'Pending_Manager'))
        conn.commit()
        conn.close()
        log_action(session['user_id'], "ACCESS_REQUESTED", f"Requested: {resource_name} — awaiting Manager")
        flash(f'Request for "{resource_name}" submitted. Awaiting Manager approval.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('access_request.html')

# ── Document Upload ────────────────────────────────────────────────────────────

@app.route('/upload_document', methods=['POST'])
@login_required
def upload_document():
    doc_type = request.form.get('doc_type', 'General')
    file     = request.files.get('document')
    if not file or file.filename == '':
        flash('Please select a file.', 'warning')
        return redirect(url_for('dashboard'))
    if not allowed_file(file.filename):
        flash('File type not allowed. Use: PDF, PNG, JPG, DOCX, TXT, XLSX.', 'danger')
        return redirect(url_for('dashboard'))
    file_bytes   = file.read()
    content_hash = hashlib.sha256(file_bytes).hexdigest()
    ipfs_hash    = "Qm" + content_hash[:44]
    safe_name    = secure_filename(file.filename)
    ts           = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    saved_name   = f"{session['user_id']}_{ts}_{safe_name}"
    with open(os.path.join(app.config['UPLOAD_FOLDER'], saved_name), 'wb') as fh:
        fh.write(file_bytes)
    conn = get_db_connection()
    conn.execute('INSERT INTO documents (user_id,doc_name,ipfs_hash,doc_type) VALUES (?,?,?,?)',
                 (session['user_id'], safe_name, ipfs_hash, doc_type))
    conn.commit()
    conn.close()
    log_action(session['user_id'], "DOCUMENT_UPLOADED", f"'{safe_name}' → IPFS: {ipfs_hash[:28]}...")
    flash(f'✅ "{safe_name}" uploaded! Hash: {ipfs_hash[:24]}...', 'success')
    return redirect(url_for('dashboard'))

# ── Manager Dashboard ──────────────────────────────────────────────────────────

@app.route('/manager_dashboard')
@manager_required
def manager_dashboard():
    conn = get_db_connection()
    dept = session.get('dept', '')
    # Team members in same department (manager sees their dept; Admin sees all)
    if session.get('role') == 'Admin':
        team = conn.execute('SELECT * FROM users ORDER BY department').fetchall()
    else:
        team = conn.execute('SELECT * FROM users WHERE department=?', (dept,)).fetchall()
    # Requests waiting for manager action
    pending_mgr = conn.execute(
        "SELECT ar.*, u.full_name, u.department, u.role FROM access_requests ar "
        "JOIN users u ON ar.user_id=u.user_id "
        "WHERE ar.status='Pending_Manager' ORDER BY ar.request_date DESC"
    ).fetchall()
    # All requests for monitoring
    all_reqs = conn.execute(
        "SELECT ar.*, u.full_name, u.department FROM access_requests ar "
        "JOIN users u ON ar.user_id=u.user_id ORDER BY ar.request_date DESC"
    ).fetchall()
    # Recent team activity
    if session.get('role') == 'Admin':
        team_logs = conn.execute(
            "SELECT al.*, u.full_name FROM audit_logs al JOIN users u ON al.user_id=u.user_id "
            "ORDER BY al.timestamp DESC LIMIT 15"
        ).fetchall()
    else:
        team_logs = conn.execute(
            "SELECT al.*, u.full_name FROM audit_logs al JOIN users u ON al.user_id=u.user_id "
            "WHERE u.department=? ORDER BY al.timestamp DESC LIMIT 15", (dept,)
        ).fetchall()
    stats = {
        'team_size': len(team),
        'pending':   len(pending_mgr),
        'approved':  conn.execute("SELECT COUNT(*) as c FROM access_requests WHERE status='Approved'").fetchone()['c'],
        'rejected':  conn.execute("SELECT COUNT(*) as c FROM access_requests WHERE status='Rejected'").fetchone()['c'],
    }
    my_tasks = conn.execute(
        'SELECT * FROM tasks WHERE assigned_to=? ORDER BY created_at DESC',
        (session['user_id'],)).fetchall()
    conn.close()
    return render_template('manager_dashboard.html', team=team, pending_mgr=pending_mgr,
                           all_reqs=all_reqs, team_logs=team_logs, stats=stats, dept=dept, my_tasks=my_tasks)

# ── Manager: Approve / Reject → moves to Pending_Admin ────────────────────────

@app.route('/manager_action/<int:req_id>/<action>', methods=['POST'])
@manager_required
def manager_action(req_id, action):
    note = request.form.get('note', '')
    conn = get_db_connection()
    req  = conn.execute('SELECT * FROM access_requests WHERE request_id=?', (req_id,)).fetchone()
    if req and req['status'] == 'Pending_Manager':
        if action == 'approve':
            conn.execute(
                "UPDATE access_requests SET status='Pending_Admin', manager_note=?, updated_at=? WHERE request_id=?",
                (note or 'Approved by Manager', datetime.datetime.now(), req_id))
            conn.commit()
            log_action(session['user_id'], "MGR_APPROVED",
                       f"Manager approved req #{req_id} for '{req['resource_name']}' → Pending Admin")
            flash(f'Request #{req_id} approved — forwarded to Admin for final verification.', 'success')
        else:
            conn.execute(
                "UPDATE access_requests SET status='Rejected', manager_note=?, updated_at=? WHERE request_id=?",
                (note or 'Rejected by Manager', datetime.datetime.now(), req_id))
            conn.commit()
            log_action(session['user_id'], "MGR_REJECTED",
                       f"Manager rejected req #{req_id} for '{req['resource_name']}'")
            flash(f'Request #{req_id} rejected.', 'warning')
    conn.close()
    return redirect(url_for('manager_dashboard'))

# ── Admin Dashboard ────────────────────────────────────────────────────────────

@app.route('/admin_dashboard')
@admin_required
def admin_dashboard():
    conn = get_db_connection()
    total_users   = conn.execute('SELECT COUNT(*) as c FROM users').fetchone()['c']
    pending_users = conn.execute("SELECT COUNT(*) as c FROM users WHERE account_status='Pending'").fetchone()['c']
    pending_req   = conn.execute("SELECT COUNT(*) as c FROM access_requests WHERE status='Pending_Admin'").fetchone()['c']
    approved_req  = conn.execute("SELECT COUNT(*) as c FROM access_requests WHERE status='Approved'").fetchone()['c']
    rejected_req  = conn.execute("SELECT COUNT(*) as c FROM access_requests WHERE status='Rejected'").fetchone()['c']
    total_tx      = conn.execute('SELECT COUNT(*) as c FROM audit_logs').fetchone()['c']
    # Requests at Pending_Admin stage only (admin's queue)
    admin_queue   = conn.execute(
        "SELECT ar.*, u.full_name, u.role, u.department FROM access_requests ar "
        "JOIN users u ON ar.user_id=u.user_id WHERE ar.status='Pending_Admin' ORDER BY ar.request_date DESC"
    ).fetchall()
    all_requests  = conn.execute(
        "SELECT ar.*, u.full_name, u.role FROM access_requests ar "
        "JOIN users u ON ar.user_id=u.user_id ORDER BY ar.request_date DESC"
    ).fetchall()
    all_users     = conn.execute('SELECT * FROM users ORDER BY created_at DESC').fetchall()
    pending_users_list = conn.execute(
        "SELECT * FROM users WHERE account_status='Pending' ORDER BY created_at DESC"
    ).fetchall()
    recent_logs   = conn.execute(
        "SELECT al.*, u.full_name FROM audit_logs al JOIN users u ON al.user_id=u.user_id "
        "ORDER BY al.timestamp DESC LIMIT 15"
    ).fetchall()
    role_counts   = conn.execute("SELECT role, COUNT(*) as cnt FROM users GROUP BY role").fetchall()
    daily_reqs    = conn.execute(
        "SELECT DATE(request_date) as day, COUNT(*) as cnt FROM access_requests "
        "WHERE request_date >= DATE('now','-7 days') GROUP BY day ORDER BY day"
    ).fetchall()
    conn.close()
    return render_template('admin_dashboard.html',
        total_users=total_users, pending_users=pending_users,
        pending_req=pending_req, approved_req=approved_req,
        rejected_req=rejected_req, total_tx=total_tx,
        admin_queue=admin_queue, all_requests=all_requests,
        all_users=all_users, pending_users_list=pending_users_list,
        recent_logs=recent_logs,
        role_labels=json.dumps([r['role'] for r in role_counts]),
        role_data=json.dumps([r['cnt']  for r in role_counts]),
        req_labels=json.dumps([r['day'] for r in daily_reqs]),
        req_data=json.dumps([r['cnt']  for r in daily_reqs])
    )

# ── Admin: Approve/Reject access request (final step) ─────────────────────────

@app.route('/admin_action/<int:req_id>/<action>', methods=['POST'])
@admin_required
def admin_action(req_id, action):
    note = request.form.get('note', '')
    conn = get_db_connection()
    req  = conn.execute('SELECT * FROM access_requests WHERE request_id=?', (req_id,)).fetchone()
    if req and req['status'] == 'Pending_Admin':
        if action == 'approve':
            tx = '0x' + hashlib.sha256(
                f"GRANT:{req_id}:{req['resource_name']}:{datetime.datetime.now()}".encode()
            ).hexdigest()[:40]
            conn.execute(
                "UPDATE access_requests SET status='Approved', admin_note=?, blockchain_tx=?, updated_at=? WHERE request_id=?",
                (note or 'Approved by Admin', tx, datetime.datetime.now(), req_id))
            conn.commit()
            log_action(session['user_id'], "ADMIN_APPROVED",
                       f"Admin granted req #{req_id} '{req['resource_name']}' → TX: {tx[:20]}")
            flash(f'✅ Request #{req_id} APPROVED. Blockchain TX recorded.', 'success')
        else:
            conn.execute(
                "UPDATE access_requests SET status='Rejected', admin_note=?, updated_at=? WHERE request_id=?",
                (note or 'Rejected by Admin', datetime.datetime.now(), req_id))
            conn.commit()
            log_action(session['user_id'], "ADMIN_REJECTED",
                       f"Admin rejected req #{req_id} '{req['resource_name']}'")
            flash(f'❌ Request #{req_id} rejected.', 'warning')
    conn.close()
    return redirect(url_for('admin_dashboard'))

# ── Admin: Approve/Suspend/Activate user accounts ─────────────────────────────

@app.route('/admin_user_action/<int:uid>/<action>')
@admin_required
def admin_user_action(uid, action):
    status_map = {'approve': 'Active', 'suspend': 'Suspended', 'activate': 'Active'}
    new_status = status_map.get(action)
    if not new_status:
        flash('Invalid action.', 'danger')
        return redirect(url_for('admin_dashboard'))
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE user_id=?', (uid,)).fetchone()
    if user and uid != session['user_id']:
        conn.execute('UPDATE users SET account_status=? WHERE user_id=?', (new_status, uid))
        conn.commit()
        log_action(session['user_id'], f"USER_{new_status.upper()}",
                   f"Admin set {user['full_name']} → {new_status}")
        flash(f"{user['full_name']} account set to {new_status}.", 'success')
    conn.close()
    return redirect(url_for('admin_dashboard'))

# ── Admin: Change Role (RBAC) ──────────────────────────────────────────────────

@app.route('/admin_change_role/<int:uid>', methods=['POST'])
@admin_required
def admin_change_role(uid):
    new_role = request.form.get('role')
    if new_role not in ('Admin', 'Manager', 'Employee'):
        flash('Invalid role.', 'danger')
        return redirect(url_for('admin_dashboard'))
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE user_id=?', (uid,)).fetchone()
    if user and uid != session['user_id']:
        conn.execute('UPDATE users SET role=? WHERE user_id=?', (new_role, uid))
        conn.commit()
        log_action(session['user_id'], "ROLE_CHANGED",
                   f"Admin changed {user['full_name']} role → {new_role}")
        flash(f"{user['full_name']}'s role changed to {new_role}.", 'success')
    conn.close()
    return redirect(url_for('admin_dashboard'))

# ── Blockchain Audit Logs ──────────────────────────────────────────────────────

@app.route('/blockchain_logs')
@login_required
def blockchain_logs():
    conn = get_db_connection()
    if session.get('role') == 'Admin':
        logs = conn.execute(
            "SELECT al.*, u.full_name FROM audit_logs al "
            "JOIN users u ON al.user_id=u.user_id ORDER BY al.timestamp DESC"
        ).fetchall()
    else:
        logs = conn.execute(
            'SELECT * FROM audit_logs WHERE user_id=? ORDER BY timestamp DESC',
            (session['user_id'],)).fetchall()
    conn.close()
    return render_template('blockchain_logs.html', logs=logs)

# ── Download Audit Report ──────────────────────────────────────────────────────

@app.route('/download_report')
@admin_required
def download_report():
    conn = get_db_connection()
    logs = conn.execute(
        "SELECT al.*, u.full_name FROM audit_logs al "
        "JOIN users u ON al.user_id=u.user_id ORDER BY al.timestamp DESC"
    ).fetchall()
    conn.close()
    lines = ["=" * 75,
             "         ACCESSLEDGER — BLOCKCHAIN AUDIT REPORT",
             f"         Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
             "=" * 75,
             f"{'#':<5} {'User':<22} {'Action':<28} {'TX Hash':<22} {'Time'}",
             "-" * 100]
    for i, log in enumerate(logs, 1):
        name   = (log['full_name'] if 'full_name' in log.keys() else 'System')[:20]
        tx     = (log['blockchain_transaction_hash'] or '')[:20]
        lines.append(f"{i:<5} {name:<22} {log['action']:<28} {tx:<22} {log['timestamp']}")
    lines += ["=" * 75, f"Total Records: {len(logs)}"]
    response = make_response("\n".join(lines))
    response.headers['Content-Type'] = 'text/plain'
    response.headers['Content-Disposition'] = 'attachment; filename=AccessLedger_Audit_Report.txt'
    return response

# ── Task Assignment (Admin) ────────────────────────────────────────────────────

@app.route('/assign_task', methods=['POST'])
@manager_required
def assign_task():
    assigned_to = request.form.get('assigned_to')
    task_title  = request.form.get('task_title')
    task_desc   = request.form.get('task_desc', '')
    if not assigned_to or not task_title:
        flash('User and Task Title are required.', 'danger')
        return redirect(request.referrer or url_for('dashboard'))
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO tasks (assigned_by, assigned_to, task_title, task_desc) VALUES (?,?,?,?)',
        (session['user_id'], assigned_to, task_title, task_desc)
    )
    conn.commit()
    conn.close()
    log_action(session['user_id'], "TASK_ASSIGNED", f"Assigned task '{task_title}' to user #{assigned_to}")
    flash(f"Task '{task_title}' assigned successfully.", 'success')
    if session.get('role') == 'Admin':
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('manager_dashboard'))

# ── Complete Task (Employee/Manager) ──────────────────────────────────────────

@app.route('/complete_task/<int:task_id>', methods=['POST'])
@login_required
def complete_task(task_id):
    conn = get_db_connection()
    task = conn.execute('SELECT * FROM tasks WHERE task_id=? AND assigned_to=?', (task_id, session['user_id'])).fetchone()
    if task and task['status'] == 'Pending':
        conn.execute("UPDATE tasks SET status='Completed', completed_at=? WHERE task_id=?", (datetime.datetime.now(), task_id))
        conn.commit()
        log_action(session['user_id'], "TASK_COMPLETED", f"Completed task '{task['task_title']}'")
        flash(f"Task '{task['task_title']}' marked as completed!", 'success')
    conn.close()
    # Redirect back to the correct dashboard based on role
    if session.get('role') == 'Manager':
        return redirect(url_for('manager_dashboard'))
    return redirect(url_for('dashboard'))

# ── Analytics API ──────────────────────────────────────────────────────────────

@app.route('/api/analytics')
@admin_required
def api_analytics():
    conn = get_db_connection()
    role_counts = conn.execute("SELECT role, COUNT(*) as cnt FROM users GROUP BY role").fetchall()
    daily_reqs  = conn.execute(
        "SELECT DATE(request_date) as day, COUNT(*) as cnt FROM access_requests "
        "WHERE request_date >= DATE('now','-7 days') GROUP BY day ORDER BY day"
    ).fetchall()
    conn.close()
    return jsonify({
        'roles':         {'labels': [r['role'] for r in role_counts], 'data': [r['cnt'] for r in role_counts]},
        'daily_requests':{'labels': [r['day']  for r in daily_reqs],  'data': [r['cnt'] for r in daily_reqs]}
    })

# ── Logout ─────────────────────────────────────────────────────────────────────

@app.route('/logout')
def logout():
    if 'user_id' in session:
        log_action(session['user_id'], "USER_LOGOUT", f"{session.get('full_name')} logged out")
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
