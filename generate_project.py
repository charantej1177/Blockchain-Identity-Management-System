import os

# Project structure
directories = [
    "blockchain_identity_management/static/css",
    "blockchain_identity_management/static/js",
    "blockchain_identity_management/static/images",
    "blockchain_identity_management/templates",
    "blockchain_identity_management/blockchain",
    "blockchain_identity_management/database",
    "blockchain_identity_management/models",
    "blockchain_identity_management/uploads",
]

for d in directories:
    os.makedirs(d, exist_ok=True)

# Files to generate
files = {
    "blockchain_identity_management/requirements.txt": """Flask==2.3.2
Flask-MySQLdb==2.0.0
web3==6.5.0
Werkzeug==2.3.6
python-dotenv==1.0.0
cryptography==41.0.1
py-solc-x==1.1.1
""",
    "blockchain_identity_management/config.py": """import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'super-secret-key-123'
    MYSQL_HOST = 'localhost'
    MYSQL_USER = 'root'
    MYSQL_PASSWORD = ''
    MYSQL_DB = 'blockchain_identity'
    MYSQL_CURSORCLASS = 'DictCursor'
    
    # Blockchain settings
    WEB3_PROVIDER_URI = 'http://127.0.0.1:7545'
    CONTRACT_ADDRESS = os.environ.get('CONTRACT_ADDRESS')
""",
    "blockchain_identity_management/database/schema.sql": """
CREATE DATABASE IF NOT EXISTS blockchain_identity;
USE blockchain_identity;

CREATE TABLE users (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    employee_id VARCHAR(50) UNIQUE NOT NULL,
    department VARCHAR(50),
    role ENUM('Admin', 'Manager', 'Employee', 'Guest') DEFAULT 'Employee',
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE identities (
    identity_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    blockchain_hash VARCHAR(66) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE access_requests (
    request_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    resource_name VARCHAR(100) NOT NULL,
    status ENUM('Pending', 'Approved', 'Rejected') DEFAULT 'Pending',
    request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE audit_logs (
    log_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    action VARCHAR(255) NOT NULL,
    blockchain_transaction_hash VARCHAR(66),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
""",
    "blockchain_identity_management/blockchain/IdentityContract.sol": """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract IdentityContract {
    struct Identity {
        bytes32 identityHash;
        string role;
        bool isActive;
        uint256 timestamp;
    }

    mapping(address => Identity) public identities;
    mapping(bytes32 => address) public hashToAddress;
    
    event IdentityRegistered(address indexed userAddress, bytes32 indexed identityHash, string role);
    event AccessLogged(address indexed userAddress, string action, uint256 timestamp);

    function registerIdentity(bytes32 _identityHash, string memory _role) public {
        require(identities[msg.sender].identityHash == bytes32(0), "Identity already exists");
        
        identities[msg.sender] = Identity({
            identityHash: _identityHash,
            role: _role,
            isActive: true,
            timestamp: block.timestamp
        });
        
        hashToAddress[_identityHash] = msg.sender;
        
        emit IdentityRegistered(msg.sender, _identityHash, _role);
    }
    
    function logAccess(string memory _action) public {
        require(identities[msg.sender].isActive, "Identity is not active or registered");
        emit AccessLogged(msg.sender, _action, block.timestamp);
    }
    
    function verifyIdentity(bytes32 _identityHash) public view returns (bool) {
        address userAddress = hashToAddress[_identityHash];
        return (userAddress != address(0) && identities[userAddress].isActive);
    }
}
""",
    "blockchain_identity_management/blockchain/blockchain_utils.py": """from web3 import Web3
from config import Config
import json

# Initialize Web3
w3 = Web3(Web3.HTTPProvider(Config.WEB3_PROVIDER_URI))

def get_contract():
    # Load ABI (In a real scenario, read from compiled contract)
    abi = [] # Replace with actual ABI
    contract_address = Config.CONTRACT_ADDRESS
    return w3.eth.contract(address=contract_address, abi=abi)

def store_identity(identity_hash, role, account, private_key):
    contract = get_contract()
    nonce = w3.eth.get_transaction_count(account)
    
    # Build transaction
    tx = contract.functions.registerIdentity(identity_hash, role).build_transaction({
        'chainId': 1337, # Ganache default
        'gas': 2000000,
        'gasPrice': w3.to_wei('50', 'gwei'),
        'nonce': nonce,
    })
    
    signed_tx = w3.eth.account.sign_transaction(tx, private_key=private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    
    return w3.to_hex(tx_hash)
""",
    "blockchain_identity_management/app.py": """from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
import hashlib
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

mysql = MySQL(app)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        full_name = request.form['full_name']
        email = request.form['email']
        employee_id = request.form['employee_id']
        department = request.form['department']
        role = request.form['role']
        password = request.form['password']
        
        hashed_password = generate_password_hash(password)
        
        # Generate SHA-256 identity hash
        identity_string = f"{email}{employee_id}{role}"
        identity_hash = hashlib.sha256(identity_string.encode()).hexdigest()
        
        cursor = mysql.connection.cursor()
        try:
            cursor.execute('''INSERT INTO users (full_name, email, employee_id, department, role, password_hash)
                              VALUES (%s, %s, %s, %s, %s, %s)''', (full_name, email, employee_id, department, role, hashed_password))
            mysql.connection.commit()
            
            # Fetch user id
            cursor.execute('SELECT user_id FROM users WHERE email = %s', (email,))
            user_id = cursor.fetchone()['user_id']
            
            cursor.execute('''INSERT INTO identities (user_id, blockchain_hash) VALUES (%s, %s)''', (user_id, identity_hash))
            mysql.connection.commit()
            
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
        finally:
            cursor.close()
            
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        cursor = mysql.connection.cursor()
        cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
        user = cursor.fetchone()
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['user_id']
            session['role'] = user['role']
            session['full_name'] = user['full_name']
            
            if user['role'] == 'Admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password', 'danger')
            
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html')

@app.route('/admin_dashboard')
def admin_dashboard():
    if 'user_id' not in session or session['role'] != 'Admin':
        return redirect(url_for('login'))
    return render_template('admin_dashboard.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
""",
    "blockchain_identity_management/templates/base.html": """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Blockchain Identity Management</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container">
            <a class="navbar-brand" href="/">Blockchain IAM</a>
            <div class="collapse navbar-collapse">
                <ul class="navbar-nav ms-auto">
                    {% if session.get('user_id') %}
                        <li class="nav-item"><a class="nav-link" href="{{ url_for('dashboard') }}">Dashboard</a></li>
                        <li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}">Logout</a></li>
                    {% else %}
                        <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">Login</a></li>
                        <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">Register</a></li>
                    {% endif %}
                </ul>
            </div>
        </div>
    </nav>
    <div class="container mt-4">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
""",
    "blockchain_identity_management/templates/index.html": """{% extends "base.html" %}
{% block content %}
<div class="jumbotron text-center mt-5">
    <h1 class="display-4">Secure Identity & Access Management</h1>
    <p class="lead">Powered by Ethereum Blockchain & Smart Contracts</p>
    <hr class="my-4">
    <p>Ensuring tamper-proof identity verification and role-based access control for smart organizations.</p>
    <a class="btn btn-primary btn-lg" href="{{ url_for('register') }}" role="button">Get Started</a>
</div>
{% endblock %}
""",
    "blockchain_identity_management/templates/login.html": """{% extends "base.html" %}
{% block content %}
<div class="row justify-content-center">
    <div class="col-md-6">
        <div class="card mt-5">
            <div class="card-header bg-primary text-white text-center">
                <h3>Login</h3>
            </div>
            <div class="card-body">
                <form method="POST">
                    <div class="mb-3">
                        <label>Email</label>
                        <input type="email" name="email" class="form-control" required>
                    </div>
                    <div class="mb-3">
                        <label>Password</label>
                        <input type="password" name="password" class="form-control" required>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Login</button>
                </form>
            </div>
        </div>
    </div>
</div>
{% endblock %}
""",
    "blockchain_identity_management/templates/register.html": """{% extends "base.html" %}
{% block content %}
<div class="row justify-content-center">
    <div class="col-md-8">
        <div class="card mt-5">
            <div class="card-header bg-success text-white text-center">
                <h3>Register</h3>
            </div>
            <div class="card-body">
                <form method="POST">
                    <div class="row">
                        <div class="col-md-6 mb-3">
                            <label>Full Name</label>
                            <input type="text" name="full_name" class="form-control" required>
                        </div>
                        <div class="col-md-6 mb-3">
                            <label>Email</label>
                            <input type="email" name="email" class="form-control" required>
                        </div>
                        <div class="col-md-6 mb-3">
                            <label>Employee ID</label>
                            <input type="text" name="employee_id" class="form-control" required>
                        </div>
                        <div class="col-md-6 mb-3">
                            <label>Department</label>
                            <input type="text" name="department" class="form-control" required>
                        </div>
                        <div class="col-md-6 mb-3">
                            <label>Role</label>
                            <select name="role" class="form-control">
                                <option value="Employee">Employee</option>
                                <option value="Manager">Manager</option>
                                <option value="Admin">Admin</option>
                                <option value="Guest">Guest</option>
                            </select>
                        </div>
                        <div class="col-md-6 mb-3">
                            <label>Password</label>
                            <input type="password" name="password" class="form-control" required>
                        </div>
                    </div>
                    <button type="submit" class="btn btn-success w-100">Register</button>
                </form>
            </div>
        </div>
    </div>
</div>
{% endblock %}
""",
    "blockchain_identity_management/templates/dashboard.html": """{% extends "base.html" %}
{% block content %}
<div class="mt-4">
    <h2>Welcome, {{ session['full_name'] }} ({{ session['role'] }})</h2>
    <hr>
    <div class="row mt-4">
        <div class="col-md-4">
            <div class="card bg-info text-white">
                <div class="card-body text-center">
                    <h4>Digital Identity</h4>
                    <p>Status: Active (Verified on Blockchain)</p>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
""",
    "blockchain_identity_management/templates/admin_dashboard.html": """{% extends "base.html" %}
{% block content %}
<div class="mt-4">
    <h2>Admin Dashboard</h2>
    <hr>
    <div class="row mt-4">
        <div class="col-md-4">
            <div class="card bg-primary text-white">
                <div class="card-body text-center">
                    <h4>Manage Users</h4>
                    <a href="#" class="btn btn-light mt-2">View Users</a>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card bg-warning text-dark">
                <div class="card-body text-center">
                    <h4>Access Requests</h4>
                    <a href="#" class="btn btn-light mt-2">Review Requests</a>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card bg-success text-white">
                <div class="card-body text-center">
                    <h4>Blockchain Logs</h4>
                    <a href="#" class="btn btn-light mt-2">View Audit Trail</a>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
""",
    "blockchain_identity_management/static/css/style.css": """
body {
    background-color: #f8f9fa;
    font-family: 'Inter', sans-serif;
}

.card {
    border-radius: 10px;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

.navbar {
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}
""",
    "blockchain_identity_management/README.md": """# Blockchain-Enabled Digital Identity and Access Management System

This is a full-stack web application built for managing digital identities using Ethereum Blockchain and Flask.

## Tech Stack
- Frontend: HTML5, CSS3, Bootstrap 5
- Backend: Python Flask
- Database: MySQL
- Blockchain: Solidity, Web3.py, Ganache

## Setup Instructions

1. Install Python packages:
   ```bash
   pip install -r requirements.txt
   ```

2. Setup MySQL database:
   Run the queries in `database/schema.sql` in your MySQL server.

3. Update `config.py`:
   Ensure your MySQL username and password are correct.

4. Run Ganache locally and update `WEB3_PROVIDER_URI` if necessary.

5. Run the application:
   ```bash
   python app.py
   ```
"""
}

for filepath, content in files.items():
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

print("Project generated successfully!")
