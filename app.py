import random
import os
import numpy as np
import tensorflow as tf

# Fix random seeds
os.environ['TF_DETERMINISTIC_OPS'] = '1'
random.seed(42)
np.random.seed(42)
tf.random.set_seed(42)

from flask import Flask, request, jsonify, send_from_directory
import cv2
from tensorflow.keras.models import load_model
from datetime import datetime
import sqlite3

app = Flask(__name__, static_folder='static')

# Load CNN model
model = load_model('models/model.h5')

CLASS_NAMES = [
    'Actinic Keratoses',
    'Basal Cell Carcinoma',
    'Benign Keratosis',
    'Dermatofibroma',
    'Melanoma',
    'Melanocytic Nevus',
    'Vascular Lesion'
]

RISK = {
    'Melanoma':             'High',
    'Basal Cell Carcinoma': 'Medium',
    'Actinic Keratoses':    'Medium',
    'Benign Keratosis':     'Low',
    'Melanocytic Nevus':    'Low',
    'Dermatofibroma':       'Low',
    'Vascular Lesion':      'Low'
}

DESC = {
    'Melanoma':             'Serious skin cancer. Immediate dermatologist consultation recommended.',
    'Basal Cell Carcinoma': 'Most common skin cancer. Rarely spreads but needs prompt treatment.',
    'Actinic Keratoses':    'Rough, scaly patch caused by sun damage. Can develop into cancer.',
    'Benign Keratosis':     'Non-cancerous skin growth. Generally harmless, monitor for changes.',
    'Melanocytic Nevus':    'Common mole. Usually harmless but monitor for changes.',
    'Dermatofibroma':       'Benign skin growth. Usually harmless, no treatment needed.',
    'Vascular Lesion':      'Abnormal blood vessel growth. Usually benign.'
}

# ── Database Setup ─────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect('database.db')
    c    = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name     TEXT NOT NULL,
            email    TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created  TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS predictions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            email       TEXT,
            diagnosis   TEXT,
            confidence  TEXT,
            risk        TEXT,
            description TEXT,
            date        TEXT,
            time        TEXT
        )
    ''')
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

# Initialize database on startup
init_db()

# ── Pages ────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('static', 'skin_disease_login_signup_v3.html')

@app.route('/dashboard')
def dashboard():
    return send_from_directory('static', 'skin_disease_full_app.html')

@app.route('/admin')
def admin():
    return send_from_directory('static', 'admin.html')

# ── Auth ─────────────────────────────────────────────────────
@app.route('/register', methods=['POST'])
def register():
    data     = request.json
    name     = data.get('name')
    email    = data.get('email')
    password = data.get('password')
    created  = datetime.now().strftime('%d %b %Y')

    conn = get_db()
    c    = conn.cursor()
    try:
        c.execute(
            'INSERT INTO users (name, email, password, created) VALUES (?, ?, ?, ?)',
            (name, email, password, created)
        )
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'success': False, 'message': 'Email already registered.'})

@app.route('/login', methods=['POST'])
def login():
    data     = request.json
    email    = data.get('email')
    password = data.get('password')

    conn = get_db()
    c    = conn.cursor()
    user = c.execute(
        'SELECT * FROM users WHERE email = ? AND password = ?',
        (email, password)
    ).fetchone()
    conn.close()

    if user:
        return jsonify({'success': True, 'name': user['name'], 'email': email})
    return jsonify({'success': False, 'message': 'Invalid email or password.'})

# ── Predict ───────────────────────────────────────────────────
@app.route('/predict', methods=['POST'])
def predict():
    if 'image' not in request.files:
        return jsonify({'error': 'No image uploaded'}), 400

    file      = request.files['image']
    email     = request.form.get('email', '')
    img_bytes = np.frombuffer(file.read(), np.uint8)
    img       = cv2.imdecode(img_bytes, cv2.IMREAD_COLOR)
    img       = cv2.resize(img, (224, 224))
    img       = img / 255.0
    img       = np.expand_dims(img, axis=0)

    predictions = model.predict(img)

    # Fix Melanoma bias
    predictions[0][4] *= 0.7

    class_index = int(np.argmax(predictions[0]))
    confidence  = round(float(np.max(predictions[0])) * 100, 2)
    diagnosis   = CLASS_NAMES[class_index]
    risk        = RISK.get(diagnosis, 'Low')
    desc        = DESC.get(diagnosis, '')

    now  = datetime.now()
    date = now.strftime('%d %b %Y')
    time = now.strftime('%I:%M %p')

    # Save to database
    conn = get_db()
    c    = conn.cursor()
    c.execute(
        'INSERT INTO predictions (email, diagnosis, confidence, risk, description, date, time) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (email, diagnosis, f'{confidence}%', risk, desc, date, time)
    )
    conn.commit()
    conn.close()

    return jsonify({
        'diagnosis':   diagnosis,
        'confidence':  f'{confidence}%',
        'risk':        risk,
        'description': desc,
        'date':        date,
        'time':        time
    })

# ── History ───────────────────────────────────────────────────
@app.route('/history', methods=['GET'])
def get_history():
    email = request.args.get('email', '')
    conn  = get_db()
    c     = conn.cursor()
    rows  = c.execute(
        'SELECT * FROM predictions WHERE email = ? ORDER BY id DESC',
        (email,)
    ).fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])

# ── Admin Data ────────────────────────────────────────────────
@app.route('/admin/data', methods=['GET'])
def admin_data():
    conn  = get_db()
    c     = conn.cursor()
    users = c.execute('SELECT name, email, created FROM users').fetchall()
    preds = c.execute('SELECT * FROM predictions ORDER BY id DESC').fetchall()
    conn.close()
    return jsonify({
        'total_users':       len(users),
        'total_predictions': len(preds),
        'users':             [dict(u) for u in users],
        'predictions':       [dict(p) for p in preds]
    })

if __name__ == '__main__':
    app.run(debug=True)