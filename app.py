import os
import sqlite3
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify,  make_response
from werkzeug.security import generate_password_hash, check_password_hash
from io import StringIO



app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev_key')

DATABASE = 'database.db'


# ---------------- DB ----------------
def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db_connection() as conn:

        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'user'
        )''')

        conn.execute('''CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product TEXT NOT NULL,
            category TEXT NOT NULL,
            date TEXT NOT NULL,
            rate REAL NOT NULL,
            cost_price REAL DEFAULT 0.0,
            quantity INTEGER NOT NULL,
            total REAL NOT NULL,
            profit REAL DEFAULT 0.0,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )''')

        # SELF HEALING
        cursor = conn.execute("PRAGMA table_info(sales)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'cost_price' not in columns:
            conn.execute('ALTER TABLE sales ADD COLUMN cost_price REAL DEFAULT 0.0')

        if 'profit' not in columns:
            conn.execute('ALTER TABLE sales ADD COLUMN profit REAL DEFAULT 0.0')

        if 'total' not in columns:
            conn.execute('ALTER TABLE sales ADD COLUMN total REAL DEFAULT 0.0')

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


# ---------------- CSV ----------------
@app.route('/export_csv')
def export_csv():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()

    df = pd.read_sql_query("""
        SELECT date, product, category, quantity, cost_price, total, profit 
        FROM sales WHERE user_id = ?
    """, conn, params=(session['user_id'],))

    conn.close()

    df['date'] = pd.to_datetime(df['date'], errors='coerce').dt.strftime('%Y-%m-%d')

    df.rename(columns={
        'date': 'Date',
        'product': 'Product',
        'category': 'Category',
        'quantity':'Quantity',
        'cost_price':'Costprice',
        'total': 'Total ($)',
        'profit':'Profit'
    }, inplace=True)

    output = StringIO()
    df.to_csv(output, index=False)

    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=sales_report.csv"
    response.headers["Content-type"] = "text/csv"

    return response


# ---------------- DELETE ----------------

@app.route('/delete_sale/<int:id>', methods=['POST'])
def delete_sale(id):
    conn = get_db_connection()
    conn.execute("DELETE FROM sales WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect('/dashboard')

# ---------------- AUTH ----------------
@app.route('/')
def home():
    return render_template('home.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            conn = get_db_connection()
            conn.execute(
                'INSERT INTO users (name, email, password) VALUES (?, ?, ?)',
                (request.form['name'],
                 request.form['email'],
                 generate_password_hash(request.form['password']))
            )
            conn.commit()
            conn.close()

            flash('Account created!', 'success')
            return redirect(url_for('login'))

        except sqlite3.IntegrityError:
            flash('Email already exists', 'danger')

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':

        conn = get_db_connection()
        user = conn.execute(
            'SELECT * FROM users WHERE email=?',
            (request.form['email'],)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user['password'], request.form['password']):
            session['user_id'] = user['id']
            session['name'] = user['name']
            session['role'] = user['role']
            return redirect(url_for('dashboard'))

        flash('Invalid login', 'danger')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))


# ---------------- DASHBOARD ----------------
@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    session.pop('_flashes', None)
    conn = get_db_connection()

    if request.method == 'POST':
      try:
        rate = float(request.form.get('rate', 0))
        cost_price = float(request.form.get('cost_price', 0))
        qty = int(request.form.get('qty', 0))
      except ValueError:
        flash("Invalid numeric input", "danger")
        return redirect(url_for('dashboard'))

    
      try:
        total = round(rate * qty, 2)
        profit = round((rate - cost_price) * qty, 2)

        conn.execute("""
            INSERT INTO sales
            (user_id, product, category, date, rate, cost_price, quantity, total, profit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session['user_id'],
            request.form['product'],
            request.form['category'],
            request.form['date'],
            rate,
            cost_price,
            qty,
            total,
            profit
        ))

        conn.commit()
        flash('Added successfully!', 'success')
        return redirect(url_for('dashboard'))

      except Exception as e:
        flash(str(e), 'danger')

        

    rows = conn.execute(
        'SELECT * FROM sales WHERE user_id=? ORDER BY date DESC',
        (session['user_id'],)
    ).fetchall()

    conn.close()

    df = pd.DataFrame([dict(r) for r in rows])

    stats = {
        'total_revenue': 0,
        'top_product': 'N/A',
        'count': 0,
        'profit': 0
    }

    if not df.empty:
        df['total'] = pd.to_numeric(df['total'], errors='coerce').fillna(0)
        df['profit'] = pd.to_numeric(df['profit'], errors='coerce').fillna(0)

        top_product = "N/A"
        if len(df) > 0:
            top_product = df.groupby('product')['total'].sum().idxmax()

        stats = {
            'total_revenue': round(df['total'].sum(), 2),
            'profit': round(df['profit'].sum(), 2),
            'count': len(df),
            'top_product': top_product
        }

    return render_template(
        'dashboard.html',
        stats=stats,
        sales=df.to_dict(orient='records')
    )
@app.route('/edit/<int:id>', methods=['POST'])
def edit_sale(id):

    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Unauthorized"})

    conn = get_db_connection()

    try:
        product = request.form['product']
        category = request.form['category']
        date = request.form['date']
        cost_price = float(request.form['cost_price'])
        rate = float(request.form['rate'])
        qty = int(request.form['qty'])

        total = round(rate * qty, 2)
        profit = round((rate - cost_price) * qty, 2)

        conn.execute("""
            UPDATE sales
            SET product=?, category=?, date=?, cost_price=?, rate=?, quantity=?, total=?, profit=?
            WHERE id=? AND user_id=?
        """, (
            product, category, date,
            cost_price, rate, qty,
            total, profit,
            id, session['user_id']
        ))

        conn.commit()

        # 🔥 FETCH UPDATED DATA (FOR CHARTS)
        rows = conn.execute(
            "SELECT * FROM sales WHERE user_id=? ORDER BY date DESC",
            (session['user_id'],)
        ).fetchall()

        df = pd.DataFrame([dict(r) for r in rows])

        if df.empty:
            return jsonify({
                "success": True,
                "updated_sale": {
                    "id": id,
                    "product": product,
                    "category": category,
                    "date": date,
                    "total": total,
                    "profit": profit
                },
                "stats": {
                    "total_revenue": 0,
                    "profit": 0,
                    "count": 0,
                    "top_product": "N/A"
                },
                "full_data": []
            })

        df['total'] = pd.to_numeric(df['total'], errors='coerce').fillna(0)
        df['profit'] = pd.to_numeric(df['profit'], errors='coerce').fillna(0)

        stats = {
            "total_revenue": round(df['total'].sum(), 2),
            "profit": round(df['profit'].sum(), 2),
            "count": len(df),
            "top_product": df.groupby('product')['total'].sum().idxmax()
        }

        return jsonify({
            "success": True,
            "updated_sale": {
                "id": id,
                "product": product,
                "category": category,
                "date": date,
                "total": total,
                "profit": profit
            },
            "stats": stats,
             
            "full_data": df.to_dict(orient="records") # 🔥 REQUIRED FOR LIVE CHARTS
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

    finally:
        conn.close()
@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    user = conn.execute('SELECT email FROM users WHERE id=?',
                        (session['user_id'],)).fetchone()
    conn.close()

    return render_template('profile.html', user_email=user['email'])

@app.route('/update_profile', methods=['POST'])
def update_profile():
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
@app.route('/change_password', methods=['POST'])
def change_password():
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
# ---------------- RUN ----------------
if __name__ == '__main__':
    app.run(debug=True)
