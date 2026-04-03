import os
import sqlite3
import pandas as pd
import numpy as np
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'high_level_sales_analyzer_secret_key'

# --- DATABASE CONFIGURATION ---
DATABASE = 'database.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes schema and auto-patches missing columns (Self-Healing)."""
    with get_db_connection() as conn:
        # 1. Create Users Table
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'user'
        )''')
        
        # 2. Create Sales Table
        conn.execute('''CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product TEXT NOT NULL,
            category TEXT NOT NULL,
            date TEXT NOT NULL,
            rate REAL NOT NULL,
            quantity INTEGER NOT NULL,
            total REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )''')

        # 3. SELF-HEALING: Check if 'total' column exists (fixes your specific error)
        cursor = conn.execute("PRAGMA table_info(sales)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'total' not in columns:
            conn.execute('ALTER TABLE sales ADD COLUMN total REAL DEFAULT 0.0')
        
        # 4. Create Default Admin if not exists
        admin_exists = conn.execute('SELECT * FROM users WHERE role = "admin"').fetchone()
        if not admin_exists:
            admin_pwd = generate_password_hash('admin123')
            conn.execute('INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)',
                         ('System Admin', 'admin@sales.com', admin_pwd, 'admin'))
        conn.commit()

# Run DB initialization every time the app starts to ensure schema is correct
init_db()

# --- AUTHENTICATION ROUTES ---

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        hashed_pw = generate_password_hash(password)

        try:
            with get_db_connection() as conn:
                conn.execute('INSERT INTO users (name, email, password) VALUES (?, ?, ?)', 
                             (name, email, hashed_pw))
                conn.commit()
            flash('Account created! Please login.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Email already registered.', 'danger')
            
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['name'] = user['name']
            session['role'] = user['role']
            
            if user['role'] == 'admin':
                return redirect(url_for('admin'))
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password.', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# --- USER MODULE ---

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()

    if request.method == 'POST':
        try:
            product = request.form['product']
            category = request.form['category']
            date = request.form['date']
            rate = float(request.form['rate'])
            qty = int(request.form['qty'])
            total = round(rate * qty, 2)

            conn.execute('''INSERT INTO sales (user_id, product, category, date, rate, quantity, total) 
                            VALUES (?, ?, ?, ?, ?, ?, ?)''', 
                         (user_id, product, category, date, rate, qty, total))
            conn.commit()
        except Exception as e:
            flash(f"Error saving data: {str(e)}", "danger")

    sales_data = conn.execute('SELECT * FROM sales WHERE user_id = ? ORDER BY date DESC', (user_id,)).fetchall()
    df = pd.DataFrame([dict(row) for row in sales_data])
    conn.close()

    stats = {'total_revenue': 0, 'top_product': 'N/A', 'count': 0}
    
    if not df.empty:
        stats['total_revenue'] = np.round(df['total'].sum(), 2)
        stats['top_product'] = df.groupby('product')['total'].sum().idxmax()
        stats['count'] = len(df)

    # Note: We send 'sales' to the template to match the JavaScript logic provided earlier
    return render_template('dashboard.html', stats=stats, sales=df.to_dict('records'))

@app.route('/delete_sale/<int:id>')
def delete_sale(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    with get_db_connection() as conn:
        conn.execute('DELETE FROM sales WHERE id = ? AND user_id = ?', (id, session['user_id']))
        conn.commit()
    return redirect(url_for('dashboard'))

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    user = conn.execute('SELECT email FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()
    
    return render_template('profile.html', user_email=user['email'])
   

# --- ADMIN MODULE ---

@app.route('/admin')
def admin():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Access Denied: Admins Only', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    users = conn.execute('SELECT id, name, email, role FROM users WHERE role != "admin"').fetchall()
    all_sales = conn.execute('''SELECT sales.*, users.name as user_name 
                                FROM sales JOIN users ON sales.user_id = users.id 
                                ORDER BY sales.id DESC LIMIT 50''').fetchall()
    conn.close()
    
    return render_template('admin.html', users=users, all_sales=all_sales)

@app.route('/admin/delete_user/<int:id>')
def delete_user(id):
    if session.get('role') == 'admin':
        with get_db_connection() as conn:
            conn.execute('DELETE FROM users WHERE id = ?', (id,))
            conn.execute('DELETE FROM sales WHERE user_id = ?', (id,)) 
            conn.commit()
    return redirect(url_for('admin'))

# --- ERROR HANDLING ---

@app.errorhandler(404)
def page_not_found(e):
    return render_template('home.html'), 404 # Redirect to home on 404
@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    new_name = request.form.get('name')
    new_email = request.form.get('email')
    user_id = session['user_id']

    try:
        conn = get_db_connection()
        conn.execute('UPDATE users SET name = ?, email = ? WHERE id = ?', 
                     (new_name, new_email, user_id))
        conn.commit()
        conn.close()
        
        # Update the session name so the sidebar/navbar updates immediately
        session['name'] = new_name
        flash('Profile updated successfully!', 'success')
    except Exception as e:
        flash(f'Error updating profile: {e}', 'danger')
        
    return redirect(url_for('profile'))

# --- Change Password ---
@app.route('/change_password', methods=['POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    new_pass = request.form.get('new_password')
    confirm_pass = request.form.get('confirm_password')
    user_id = session['user_id']
    
    if not new_pass or len(new_pass) < 8:
        flash('Password must be at least 8 characters long.', 'danger')
        return redirect(url_for('profile'))

    if new_pass == confirm_pass:
        # Securely hash the password before saving
        hashed_pw = generate_password_hash(new_pass)
        
        conn = get_db_connection()
        conn.execute('UPDATE users SET password = ? WHERE id = ?', 
                     (hashed_pw, user_id))
        conn.commit()
        conn.close()
        
        flash('Password changed successfully!', 'success')
    else:
        flash('Passwords do not match!', 'danger')
        
    return redirect(url_for('profile'))
if __name__ == '__main__':
    app.run(debug=True)