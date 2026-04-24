import os
import sqlite3
import pandas as pd
import numpy as np
from datetime import timedelta
from io import StringIO

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, make_response,jsonify
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

# ─── MATPLOTLIB FIX ───────────────────────────────────────────────────────────

import matplotlib
matplotlib.use('Agg')  # Prevent GUI warning

import matplotlib.pyplot as plt

# ─── APP CONFIG ───────────────────────────────────────────────────────────────

app = Flask(__name__)

app.secret_key = os.environ.get(
    'SECRET_KEY',
    'sa_super_secret_key_change_in_prod_2025!'
)

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

DATABASE = 'database.db'


# ─── DATABASE HELPERS ─────────────────────────────────────────────────────────

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Creates tables and seeds default admin on first run."""
    with get_db_connection() as conn:

        # USERS TABLE
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'user'
            )
        ''')

        # SALES TABLE
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                product TEXT NOT NULL,
                category TEXT NOT NULL,
                date TEXT NOT NULL,
                rate REAL NOT NULL,
                quantity INTEGER NOT NULL,
                total REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')

        # SELF-HEALING FOR OLD DATABASES
        cols = [
            r[1]
            for r in conn.execute(
                "PRAGMA table_info(sales)"
            ).fetchall()
        ]

        if 'total' not in cols:
            conn.execute(
                'ALTER TABLE sales ADD COLUMN total REAL DEFAULT 0.0'
            )
        if 'cost_price' not in cols:
             conn.execute(
                   'ALTER TABLE sales ADD COLUMN cost_price REAL DEFAULT 0.0'
    )
        # DEFAULT ADMIN
        admin = conn.execute('SELECT * FROM users WHERE role="admin"').fetchone()
        if not admin:
            conn.execute(
                'INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)',
                ('System Admin', 'admin@sales.com',
                 generate_password_hash('admin123'), 'admin')
            )

        conn.commit()


init_db()
# ─── MATPLOTLIB CHARTS ─
def generate_charts(sales):
    chart_folder = os.path.join("static", "charts")
    os.makedirs(chart_folder, exist_ok=True)

    if not sales:
        return

    product_totals = {}
    category_totals = {}
    dates = []
    revenues = []
    profits = []

    for row in sales:
        # Safe access for sqlite rows + dict rows
        product = row["product"]
        category = row["category"]
        total = float(row["total"]) if row["total"] else 0

        # Profit calculation
        cost_price = float(row["cost_price"]) if "cost_price" in row and row["cost_price"] else 0
        quantity = int(row["quantity"]) if row["quantity"] else 0
        rate = float(row["rate"]) if row["rate"] else 0

        profit = (rate - cost_price) * quantity

        product_totals[product] = product_totals.get(product, 0) + total
        category_totals[category] = category_totals.get(category, 0) + 1

        dates.append(row["date"])
        revenues.append(total)
        profits.append(profit)

    # BAR CHART
    plt.figure(figsize=(10, 5))
    plt.bar(product_totals.keys(), product_totals.values())
    plt.title("Sales Chart (Product Performance)")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig("static/charts/product_chart.png")
    plt.close()

    # LINE CHART
    plt.figure(figsize=(10, 5))
    plt.plot(dates, revenues, label="Revenue")
    plt.plot(dates, profits, label="Profit")
    plt.title("Monthly Sales Growth")
    plt.legend()
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig("static/charts/line_chart.png")
    plt.close()

    # PIE CHART
    plt.figure(figsize=(7, 7))
    plt.pie(
        category_totals.values(),
        labels=category_totals.keys(),
        autopct="%1.1f%%"
    )
    plt.title("Category Split")
    plt.tight_layout()
    plt.savefig("static/charts/category_chart.png")
    plt.close()
# ─── SESSION START ──────────────
def _start_session(user):
    session.permanent = True
    session['user_id'] = user['id']
    session['name'] = user['name']
    session['role'] = user['role']


# ─── HOME
@app.route('/')
def home():
    return render_template('home.html')
# ─── REGISTER ──────────
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']

        if len(password) < 6:
            flash(
                'Password must be at least 6 characters.',
                'danger'
            )
            return render_template('register.html')

        try:
            with get_db_connection() as conn:
                conn.execute(
                    '''
                    INSERT INTO users
                    (name, email, password)
                    VALUES (?, ?, ?)
                    ''',
                    (
                        name,
                        email,
                        generate_password_hash(password)
                    )
                )
                conn.commit()

            flash(
                'Account created! Please log in.',
                'success'
            )
            return redirect(url_for('login'))

        except sqlite3.IntegrityError:
            flash(
                'That email is already registered.',
                'danger'
            )

    return render_template('register.html')


# ─── LOGIN ────────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']

        conn = get_db_connection()

        user = conn.execute(
            'SELECT * FROM users WHERE email = ?',
            (email,)
        ).fetchone()

        conn.close()

        if user and check_password_hash(
            user['password'],
            password
        ):
            _start_session(user)

            flash(
                f'Welcome back, {user["name"]}! 👋',
                'success'
            )

            if user['role'] == 'admin':
                return redirect(url_for('admin_panel'))

            return redirect(url_for('dashboard'))

        flash(
            'Incorrect email or password.',
            'danger'
        )

    return render_template('login.html')


# ─── LOGOUT ───────────────────────────────────────────────────────────────────

@app.route('/logout')
def logout():
    session.clear()
    flash(
        'You have been logged out.',
        'success'
    )
    return redirect(url_for('home'))


# ─── ADMIN PANEL ──────────────────────────────────────────────────────────────

@app.route('/admin')
def admin_panel():
    if (
        'user_id' not in session or
        session.get('role') != 'admin'
    ):
        flash('Admin access only.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()

    users = conn.execute(
        '''
        SELECT id, name, email, role
        FROM users
        '''
    ).fetchall()

    total_sales = conn.execute(
        'SELECT COUNT(*) FROM sales'
    ).fetchone()[0]

    conn.close()

    return render_template(
        'admin.html',
        users=users,
        total_sales=total_sales
    )


# ─── DASHBOARD ────────────────────────────────────────────────────────────────

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()

    # ADD SALE
    if request.method == 'POST':
        try:
            product = request.form['product'].strip()
            category = request.form['category']
            date = request.form['date']
            cost_price = float(request.form['cost_price'])
            rate = float(request.form['rate'])
            qty = int(request.form['qty'])

            if rate <= 0 or qty <= 0:
                flash(
                    'Rate and quantity must be greater than zero.',
                    'danger'
                )
            else:
                total = round(rate * qty, 2)

                conn.execute(
                    '''
                    INSERT INTO sales
                    (
                        user_id,
                        product,
                        category,
                        date,
                        rate,
                        cost_price,
                        quantity,
                        total
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?,?)
                    ''',
                    (
                        user_id,
                        product,
                        category,
                        date,
                        rate,
                        cost_price,
                        qty,
                        total
                    )
                )

                conn.commit()

                flash(
                    'Sale added successfully!',
                    'success'
                )

        except Exception as e:
            flash(
                f'Error saving data: {str(e)}',
                'danger'
            )

        conn.close()
        return redirect(url_for('dashboard'))

    # FETCH SALES
    rows = conn.execute(
        '''
        SELECT *
        FROM sales
        WHERE user_id = ?
        ORDER BY date DESC
        ''',
        (user_id,)
    ).fetchall()

    conn.close()

    sales_data = [dict(r) for r in rows]

    # GENERATE MATPLOTLIB CHARTS
    generate_charts(sales_data)

    df = pd.DataFrame(sales_data)

    stats = {
            'total_revenue': 0,
             'top_product': 'N/A',
             'count': 0,
            'profit': 0
        }

    monthly_profit_data = []



    if not df.empty:
        df['total'] = pd.to_numeric(
            df['total'],
            errors='coerce'
        ).fillna(0)

        revenue = round(
            float(df['total'].sum()),
            2
        )

        stats = {
        'total_revenue': 0,
        'top_product': 'N/A',
        'count': 0,
        'profit': 0
        }

        monthly_profit_data = []

        if not df.empty:
    # Safe numeric conversion
             df['total'] = pd.to_numeric(df['total'], errors='coerce').fillna(0)
             df['rate'] = pd.to_numeric(df['rate'], errors='coerce').fillna(0)
             df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)

             if 'cost_price' not in df.columns:
                 df['cost_price'] = 0

                 df['cost_price'] = pd.to_numeric(
                 df['cost_price'],
                 errors='coerce'
                 ).fillna(0)

    # Real Profit Formula
             df['profit'] = (
                 (df['rate'] - df['cost_price']) * df['quantity']
            )

             revenue = round(float(df['total'].sum()), 2)
             total_profit = round(float(df['profit'].sum()), 2)

             stats = {
                 'total_revenue': revenue,
                 'top_product': df.groupby('product')['total'].sum().idxmax(),
                'count': len(df),
                 'profit': total_profit
            }

    # Monthly Profit Data
             df['month'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m')

             monthly_profit_data = (
    df.groupby('month')
    .agg({
        'total': 'sum',
        'profit': 'sum'
    })
    .reset_index()
    .rename(columns={
        'total': 'revenue',
        'profit': 'profit'
    })
    .sort_values('month', ascending=False)
    .to_dict('records')
)
    return render_template(
    'dashboard.html',
    stats=stats,
    sales=df.to_dict('records') if not df.empty else [],
    monthly_profit_data=monthly_profit_data
)

# ─── EXPORT CSV ───────────────────────────────────────────────────────────────

@app.route('/export_csv')
def export_csv():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()

    df = pd.read_sql_query(
        '''
        SELECT
            date,
            product,
            category,
            rate,
            cost_price,
            quantity,
            profit,
            total
        FROM sales
        WHERE user_id = ?
        ''',
        conn,
        params=(session['user_id'],)
    )

    conn.close()

    df.rename(
        columns={
            'date': 'Date',
            'product': 'Product',
            'category': 'Category',
            'rate': 'Rate ($)',
            'cost_price':'Costprice',
            'quantity': 'Quantity',
            'profit':'Profit',
            'total': 'Total ($)'
        },
        inplace=True
    )

    output = StringIO()
    df.to_csv(output, index=False)

    response = make_response(output.getvalue())
    response.headers[
        'Content-Disposition'
    ] = 'attachment; filename=sales_report.csv'

    response.headers[
        'Content-Type'
    ] = 'text/csv'

    return response


# ─── DELETE SALE ──────────────────────────────────────────────────────────────

@app.route('/delete_sale/<int:id>', methods=['POST'])
def delete_sale(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()

    conn.execute(
        '''
        DELETE FROM sales
        WHERE id = ? AND user_id = ?
        ''',
        (
            id,
            session['user_id']
        )
    )

    conn.commit()
    conn.close()

    flash(
        'Record deleted.',
        'success'
    )

    return redirect(url_for('dashboard'))

# ─── EDIT SALE ──────────────────────────────────────────────────────────────

@app.route('/edit/<int:id>', methods=['POST'])
def edit_sale(id):
    if 'user_id' not in session:
        return {"success": False, "error": "Unauthorized"}

    try:
        product = request.form['product'].strip()
        category = request.form['category']
        date = request.form['date']
        cost_price = float(request.form['cost_price'])
        rate = float(request.form['rate'])
        qty = int(request.form['qty'])

        if rate <= 0 or qty <= 0 or cost_price < 0:
            return {
                "success": False,
                "error": "Invalid values"
            }

        total = round(rate * qty, 2)

        conn = get_db_connection()

        conn.execute(
            '''
            UPDATE sales
            SET
                product = ?,
                category = ?,
                date = ?,
                cost_price = ?,
                rate = ?,
                quantity = ?,
                total = ?
            WHERE id = ? AND user_id = ?
            ''',
            (
                product,
                category,
                date,
                cost_price,
                rate,
                qty,
                total,
                id,
                session['user_id']
            )
        )

        conn.commit()
        conn.close()

        return {"success": True}

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
# ─── PROFILE ──────────────────────────────────────────────────────────────────

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()

    user = conn.execute(
        '''
        SELECT email
        FROM users
        WHERE id = ?
        ''',
        (session['user_id'],)
    ).fetchone()

    conn.close()

    return render_template(
        'profile.html',
        user_email=user['email']
    )


# ─── UPDATE PROFILE ───────────────────────────────────────────────────────────

@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    user_id = session['user_id']

    try:
        conn = get_db_connection()

        conn.execute(
            '''
            UPDATE users
            SET name = ?, email = ?
            WHERE id = ?
            ''',
            (
                name,
                email,
                user_id
            )
        )

        conn.commit()
        conn.close()

        session['name'] = name

        flash(
            'Profile updated! ✅',
            'success'
        )

    except Exception as e:
        flash(
            f'Error updating profile: {e}',
            'danger'
        )

    return redirect(url_for('profile'))


# ─── CHANGE PASSWORD ──────────────────────────────────────────────────────────

@app.route('/change_password', methods=['POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    new_pass = request.form.get(
        'new_password',
        ''
    )

    confirm_pass = request.form.get(
        'confirm_password',
        ''
    )

    if len(new_pass) < 8:
        flash(
            'Password must be at least 8 characters.',
            'danger'
        )
        return redirect(url_for('profile'))

    if new_pass != confirm_pass:
        flash(
            'Passwords do not match.',
            'danger'
        )
        return redirect(url_for('profile'))

    conn = get_db_connection()

    conn.execute(
        '''
        UPDATE users
        SET password = ?
        WHERE id = ?
        ''',
        (
            generate_password_hash(new_pass),
            session['user_id']
        )
    )

    conn.commit()
    conn.close()

    flash(
        'Password changed successfully! 🔐',
        'success'
    )

    return redirect(url_for('profile'))


# ─── ERROR HANDLER ────────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return render_template('home.html'), 404

# ---------------- ADMIN PANEL ----------------
@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form['username'] == 'admin' and request.form['password'] == '1234567890':
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))
        flash('Access Denied', 'danger')

    return render_template('admin-login.html') # 👈 IMPORTANT

@app.route('/admin-logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('home'))

@app.route('/admin-panel')
def admin_dashboard():
    if not session.get('admin'):
        return redirect(url_for('home'))
    return render_template('admin-panel.html')

@app.route('/admin/users')
def admin_users():
    if not session.get('admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    conn = get_db_connection()
    users = conn.execute('SELECT id, name, email, role FROM users ORDER BY id').fetchall()
    conn.close()
    return jsonify([dict(user) for user in users])

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
def admin_delete_user(user_id):
    if not session.get('admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    conn = get_db_connection()
    # Delete user's sales first
    conn.execute('DELETE FROM sales WHERE user_id = ?', (user_id,))
    # Delete user
    conn.execute('DELETE FROM users WHERE id = ? AND role != "admin"', (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/admin/user/<int:user_id>')
def admin_user_details(user_id):
    if not session.get('admin'):
        return redirect(url_for('home'))

    conn = get_db_connection()

    user = conn.execute(
        'SELECT * FROM users WHERE id = ?',
        (user_id,)
    ).fetchone()

    if not user:
        conn.close()
        flash('User not found', 'danger')
        return redirect(url_for('admin_dashboard'))

    rows = conn.execute(
        '''
        SELECT *
        FROM sales
        WHERE user_id = ?
        ORDER BY date DESC
        ''',
        (user_id,)
    ).fetchall()

    conn.close()

    df = pd.DataFrame([dict(r) for r in rows])

    stats = {
        'total_revenue': 0,
        'profit': 0,
        'count': 0,
        'top_product': 'N/A'
    }

    if not df.empty:
        df['total'] = pd.to_numeric(df['total'], errors='coerce').fillna(0)
        df['rate'] = pd.to_numeric(df['rate'], errors='coerce').fillna(0)
        df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)

        if 'cost_price' not in df.columns:
            df['cost_price'] = 0

        df['cost_price'] = pd.to_numeric(
            df['cost_price'],
            errors='coerce'
        ).fillna(0)

        # REAL PROFIT CALCULATION
        df['profit'] = (
            (df['rate'] - df['cost_price']) * df['quantity']
        )

        stats = {
            'total_revenue': round(float(df['total'].sum()), 2),
            'profit': round(float(df['profit'].sum()), 2),
            'count': len(df),
            'top_product': df.groupby('product')['total'].sum().idxmax()
        }

    return render_template(
        'user-details.html',
        user=dict(user),
        stats=stats,
        full_data=df.to_dict('records')
    )
@app.route('/admin_update_profile', methods=['POST'])
def admin_update_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    name = request.form['name']
    email = request.form['email']

    conn = get_db_connection()

    try:
        conn.execute("""
            UPDATE users
            SET name=?, email=?
            WHERE id=?
        """, (name, email, session['user_id']))

        conn.commit()

        # ✅ Update session values also
        session['name'] = name

        flash("Profile updated successfully!", "success")

    except sqlite3.IntegrityError:
        flash("Email already exists!", "danger")

    finally:
        conn.close()

    return redirect(url_for('profile'))
@app.route('/admin_change_password', methods=['POST'])
def admin_change_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    new_password = request.form['new_password']
    confirm_password = request.form['confirm_password']
    if new_password != confirm_password:
        flash("Passwords do not match!", "danger")
        return redirect(url_for('profile'))
    if len(new_password) < 8:
        flash("Password must be at least 8 characters!", "danger")
        return redirect(url_for('profile'))
    hashed_password = generate_password_hash(new_password)
    conn = get_db_connection()
    conn.execute("""
        UPDATE users SET password=? WHERE id=?
    """, (hashed_password, session['user_id']))
    conn.commit()
    conn.close()
    flash("Password updated successfully!", "success")
    return redirect(url_for('profile'))
# ─── RUN ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(debug=True)
