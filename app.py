import os
import sqlite3
import pandas as pd
import numpy as np
import base64
from datetime import timedelta
from io import StringIO, BytesIO

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, make_response, jsonify
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
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



def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Creates tables and seeds default admin on first run."""
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'user'
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                product TEXT NOT NULL,
                category TEXT NOT NULL,
                date TEXT NOT NULL,
                rate REAL NOT NULL,
                cost_price REAL DEFAULT 0.0,
                quantity INTEGER NOT NULL,
                total REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')

        cols = [r[1] for r in conn.execute("PRAGMA table_info(sales)").fetchall()]

        if 'total' not in cols:
            conn.execute('ALTER TABLE sales ADD COLUMN total REAL DEFAULT 0.0')
        if 'cost_price' not in cols:
            conn.execute('ALTER TABLE sales ADD COLUMN cost_price REAL DEFAULT 0.0')
        if 'profit' not in cols:
            conn.execute('ALTER TABLE sales ADD COLUMN profit REAL DEFAULT 0.0')

        admin = conn.execute('SELECT * FROM users WHERE role="admin"').fetchone()
        if not admin:
            conn.execute(
                'INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)',
                ('System Admin', 'admin@sales.com', generate_password_hash('admin123'), 'admin')
            )

        conn.commit()


init_db()


plt.style.use('ggplot') 



  

def fig_to_base64(fig):
    fig.patch.set_facecolor('#ffffff') 
    buffer = BytesIO()
    # High DPI for "Retina" display crispness
    fig.savefig(buffer, format='png', dpi=300, bbox_inches='tight', transparent=True)
    plt.close(fig)
    buffer.seek(0)
    return 'data:image/png;base64,' + base64.b64encode(buffer.read()).decode('utf-8')

def apply_minimal_theme(ax, title):
    """Removes all 'chart junk' for a floating, modern look."""
    
    ax.set_title(title.upper(), pad=30, fontsize=14, fontweight='900', color='#0f172a')
    
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors="#0a0b0b", labelsize=12, length=0)
    ax.set_facecolor('none')
    ax.grid(axis='y', linestyle='-', alpha=0.1, color='#0f172a', zorder=0)

def generate_bar_chart_base64(labels, values, title='Top Products'):
    fig, ax = plt.subplots(figsize=(12, 7))
    
   
    bars = ax.bar(labels, values, color="#294ABE", edgecolor='#4f46e5', 
                  linewidth=1.5, width=0.5, zorder=3, alpha=0.9)
    
    
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, height + (max(values)*0.02),
                f'${height:,.0f}', ha='center', va='bottom', 
                fontsize=11, fontweight='bold', color='#6366f1')

    apply_minimal_theme(ax, title)
    plt.tight_layout()
    return fig_to_base64(fig)

def generate_pie_chart_base64(labels, values, title='Market Share'):
    fig, ax = plt.subplots(figsize=(4, 4))

    colors = ['#6366f1', '#8b5cf6', '#ec4899', '#f43f5e', '#f59e0b']

    if not values:
        ax.text(0.5, 0.5, "No Data", ha='center', va='center')
    else:
        wedges, texts, autotexts = ax.pie(
            values,
            labels=labels,
            autopct='%1.0f%%',
            startangle=90,
            colors=colors,

            radius=0.85,          
            pctdistance=0.78,
            labeldistance=1.08,

            wedgeprops={
                'width': 0.28,
                'edgecolor': 'white',
                'linewidth': 3
            }
        )

        
        plt.setp(
            autotexts,
            size=7,
            weight="bold",
            color="white"
        )

        plt.setp(
            texts,
            size=7,
            fontweight='bold',
            color="#334155"
        )

    
    ax.text(
        0, 0,
        "SALES",
        ha='center',
        va='center',
        fontsize=10,
        fontweight='bold',
        color='#94a3b8'
    )

   
    ax.set_title(
        title.upper(),
        pad=15,
        fontsize=10,
        fontweight='900',
        color='#0f172a'
    )

    ax.axis('equal')
    plt.tight_layout()

    return fig_to_base64(fig)

def generate_growth_chart_base64(months, revenue, profit, title="Performance Metrics"):
    fig, ax = plt.subplots(figsize=(22, 5))
    
    
    ax.plot(months, revenue, color='#6366f1', marker='o', linewidth=4, 
            label='REVENUE', markersize=12, markerfacecolor='white', markeredgewidth=3, zorder=5)
    ax.fill_between(months, revenue, color='#6366f1', alpha=0.05, zorder=4)
    
    
    ax.plot(months, profit, color='#10b981', marker='s', linewidth=3, linestyle='--',
            label='PROFIT', markersize=8, markerfacecolor='white', markeredgewidth=2, zorder=6)
    
    apply_minimal_theme(ax, title)
    ax.legend(frameon=False, loc='upper left', fontsize=10, ncol=2, labelcolor='#64748b')
    
    plt.tight_layout()
    return fig_to_base64(fig)

def _start_session(user):
    session.permanent = True
    session['user_id'] = user['id']
    session['name'] = user['name']
    session['role'] = user['role']

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']

        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('register.html')

        try:
            with get_db_connection() as conn:
                conn.execute(
                    '''
                    INSERT INTO users
                    (name, email, password)
                    VALUES (?, ?, ?)
                    ''',
                    (name, email, generate_password_hash(password))
                )
                conn.commit()

            flash('Account created! Please log in.', 'success')
            return redirect(url_for('login'))

        except sqlite3.IntegrityError:
            flash('That email is already registered.', 'danger')

    return render_template('register.html')



@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            _start_session(user)
            flash(f'Welcome back, {user["name"]}! 👋', 'success')

            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))

            return redirect(url_for('dashboard'))

        flash('Incorrect email or password.', 'danger')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('home'))

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()

    if request.method == 'POST':
        try:
            product = request.form['product'].strip()
            category = request.form['category']
            date = request.form['date']
            cost_price = float(request.form['cost_price'])
            rate = float(request.form['rate'])
            qty = int(request.form['qty'])

            if rate <= 0 or qty <= 0:
                flash('Rate and quantity must be greater than zero.', 'danger')
            else:
                total = round(rate * qty, 2)
                profit = round((rate - cost_price) * qty, 2)

                conn.execute(
                    '''
                    INSERT INTO sales
                    (user_id, product, category, date, rate, cost_price, quantity, total, profit)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (user_id, product, category, date, rate, cost_price, qty, total, profit)
                )
                conn.commit()
                flash('Sale added successfully!', 'success')
        except Exception as e:
            flash(f'Error saving data: {str(e)}', 'danger')
        
        conn.close()
        return redirect(url_for('dashboard'))

    
    rows = conn.execute('SELECT * FROM sales WHERE user_id = ? ORDER BY date DESC', (user_id,)).fetchall()
    conn.close()

    sales_data = [dict(r) for r in rows]
    df = pd.DataFrame(sales_data)

    
    stats = {'total_revenue': 0, 'top_product': 'N/A', 'count': 0, 'profit': 0}
    monthly_profit_data = []
    growth_chart_url = ""
    category_chart_url = ""
    product_chart_url = ""

    if not df.empty:
       
        df['total'] = pd.to_numeric(df['total'], errors='coerce').fillna(0)
        df['rate'] = pd.to_numeric(df['rate'], errors='coerce').fillna(0)
        df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)
        df['cost_price'] = pd.to_numeric(df.get('cost_price', 0), errors='coerce').fillna(0)
        df['profit'] = (df['rate'] - df['cost_price']) * df['quantity']
        df['date_dt'] = pd.to_datetime(df['date'], errors='coerce')
        df['month'] = df['date_dt'].dt.strftime('%Y-%m')

        
        stats = {
            'total_revenue': round(float(df['total'].sum()), 2),
            'top_product': df.groupby('product')['total'].sum().idxmax(),
            'count': len(df),
            'profit': round(float(df['profit'].sum()), 2)
        }

        
        monthly_profit_data = (
            df.groupby('month')
            .agg({'total': 'sum', 'profit': 'sum'})
            .reset_index()
            .rename(columns={'total': 'revenue'})
            .sort_values('month', ascending=False)
            .to_dict('records')
        )
        
        df_sorted = df.sort_values('month')
        monthly_growth = df_sorted.groupby('month').agg({'total': 'sum', 'profit': 'sum'}).reset_index()

        
        growth_chart_url = generate_growth_chart_base64(
            monthly_growth['month'].tolist(), 
            monthly_growth['total'].tolist(), 
            monthly_growth['profit'].tolist()
        )

        
        cat_counts = df['category'].value_counts()
        category_chart_url = generate_pie_chart_base64(cat_counts.index.tolist(), cat_counts.values.tolist(), "Sales by Category")

        
        prod_revenue = df.groupby('product')['total'].sum().sort_values(ascending=False).head(10)
        product_chart_url = generate_bar_chart_base64(prod_revenue.index.tolist(), prod_revenue.values.tolist(), "Top Products")

        
    return render_template(
        'dashboard.html',
        stats=stats,
        sales=df.to_dict('records') if not df.empty else [],
        monthly_profit_data=monthly_profit_data,
        growth_chart=growth_chart_url,
        category_chart=category_chart_url,
        product_chart=product_chart_url
    )

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
            'cost_price': 'Costprice',
            'quantity': 'Quantity',
            'profit': 'Profit',
            'total': 'Total ($)'
        },
        inplace=True
    )

    output = StringIO()
    df.to_csv(output, index=False)

    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=sales_report.csv'
    response.headers['Content-Type'] = 'text/csv'
    return response

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
        (id, session['user_id'])
    )
    conn.commit()
    conn.close()

    flash('Record deleted.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/edit/<int:id>', methods=['POST'])
def edit_sale(id):
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    try:
        product = request.form['product'].strip()
        category = request.form['category']
        date = request.form['date']
        cost_price = float(request.form['cost_price'])
        rate = float(request.form['rate'])
        qty = int(request.form['qty'])

        if rate <= 0 or qty <= 0 or cost_price < 0:
            return jsonify({"success": False, "error": "Invalid values"}), 400

        total = round(rate * qty, 2)
        profit = round((rate - cost_price) * qty, 2)

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
                total = ?,
                profit = ?
            WHERE id = ? AND user_id = ?
            ''',
            (product, category, date, cost_price, rate, qty, total, profit, id, session['user_id'])
        )
        conn.commit()
        conn.close()

        return jsonify({"success": True})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

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

    return render_template('profile.html', user_email=user['email'])

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
            (name, email, user_id)
        )
        conn.commit()
        conn.close()

        session['name'] = name
        flash('Profile updated! ✅', 'success')

    except Exception as e:
        flash(f'Error updating profile: {e}', 'danger')

    return redirect(url_for('profile'))



@app.route('/change_password', methods=['POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    new_pass = request.form.get('new_password', '')
    confirm_pass = request.form.get('confirm_password', '')

    if len(new_pass) < 8:
        flash('Password must be at least 8 characters.', 'danger')
        return redirect(url_for('profile'))

    if new_pass != confirm_pass:
        flash('Passwords do not match.', 'danger')
        return redirect(url_for('profile'))

    conn = get_db_connection()
    conn.execute(
        '''
        UPDATE users
        SET password = ?
        WHERE id = ?
        ''',
        (generate_password_hash(new_pass), session['user_id'])
    )
    conn.commit()
    conn.close()

    flash('Password changed successfully! 🔐', 'success')
    return redirect(url_for('profile'))



@app.errorhandler(404)
def not_found(e):
    return render_template('home.html'), 404

@app.route('/admin-logout')
def admin_logout():
    session.clear()   # clears EVERYTHING
    flash('Admin logged out successfully.', 'success')
    return redirect(url_for('login'))


@app.route('/admin-panel')
def admin_dashboard():
    if session.get('role') != 'admin':
      return redirect(url_for('login'))

    conn = get_db_connection()

    users = conn.execute('SELECT id, name, email, role FROM users ORDER BY id').fetchall()
    total_sales = conn.execute('SELECT COUNT(*) AS c FROM sales').fetchone()['c']
    total_users = conn.execute('SELECT COUNT(*) AS c FROM users').fetchone()['c']
    total_revenue = conn.execute('SELECT COALESCE(SUM(total),0) AS t FROM sales').fetchone()['t']
    total_profit = conn.execute('SELECT COALESCE(SUM((rate - cost_price) * quantity),0) AS p FROM sales').fetchone()['p']

    prod_rows = conn.execute("""
        SELECT product, COALESCE(SUM(total),0) AS revenue
        FROM sales
        GROUP BY product
        ORDER BY revenue DESC
    """).fetchall()

    cat_rows = conn.execute("""
        SELECT category, COUNT(*) AS cnt
        FROM sales
        GROUP BY category
        ORDER BY cnt DESC
    """).fetchall()

    conn.close()

    bar_labels = [r['product'] for r in prod_rows]
    bar_values = [round(r['revenue'], 2) for r in prod_rows]
    pie_labels = [r['category'] for r in cat_rows]
    pie_values = [r['cnt'] for r in cat_rows]

    bar_chart = generate_bar_chart_base64(bar_labels, bar_values, "Revenue by Product")
    pie_chart = generate_pie_chart_base64(pie_labels, pie_values, "Sales by Category")

    return render_template(
        'admin-panel.html',
        users=users,
        total_sales=total_sales,
        total_users=total_users,
        total_revenue=round(total_revenue, 2),
        total_profit=round(total_profit, 2),
        bar_chart=bar_chart,
        pie_chart=pie_chart
    )
@app.route('/admin/users')
def admin_users():
    if session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    conn = get_db_connection()
    users = conn.execute('SELECT id, name, email, role FROM users ORDER BY id').fetchall()
    conn.close()
    return jsonify([dict(user) for user in users])


@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
def admin_delete_user(user_id):
    if session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    conn = get_db_connection()
    user = conn.execute('SELECT role FROM users WHERE id=?', (user_id,)).fetchone()

    if not user:
        conn.close()
        return jsonify({'success': False, 'error': 'User not found'}), 404

    if user['role'] == 'admin':
        conn.close()
        return jsonify({'success': False, 'error': 'Cannot delete admin'}), 400

    conn.execute('DELETE FROM sales WHERE user_id=?', (user_id,))
    conn.execute('DELETE FROM users WHERE id=?', (user_id,))
    conn.commit()
    conn.close()

    return jsonify({'success': True})


@app.route('/admin/user/<int:user_id>')
def admin_user_details(user_id):
    if session.get('role') != 'admin':
       return redirect(url_for('login'))

    conn = get_db_connection()

    user = conn.execute(
        'SELECT id, name, email, role FROM users WHERE id=?',
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

    bar_chart = generate_bar_chart_base64([], [], "Revenue by Product")
    pie_chart = generate_pie_chart_base64([], [], "Sales by Category")

    if not df.empty:
        df['total'] = pd.to_numeric(df['total'], errors='coerce').fillna(0)
        df['rate'] = pd.to_numeric(df['rate'], errors='coerce').fillna(0)
        df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)
        df['cost_price'] = pd.to_numeric(df.get('cost_price', 0), errors='coerce').fillna(0)
        df['profit'] = (df['rate'] - df['cost_price']) * df['quantity']

        stats = {
            'total_revenue': round(float(df['total'].sum()), 2),
            'profit': round(float(df['profit'].sum()), 2),
            'count': len(df),
            'top_product': df.groupby('product')['total'].sum().idxmax()
        }

        prod_rows = df.groupby('product')['total'].sum().reset_index()
        cat_rows = df.groupby('category').size().reset_index(name='count')

        bar_chart = generate_bar_chart_base64(
            prod_rows['product'].tolist(),
            prod_rows['total'].round(2).tolist(),
            "Revenue by Product"
        )

        pie_chart = generate_pie_chart_base64(
            cat_rows['category'].tolist(),
            cat_rows['count'].tolist(),
            "Sales by Category"
        )

    return render_template(
        'user-details.html',
        user=dict(user),
        stats=stats,
        full_data=df.to_dict('records'),
        bar_chart=bar_chart,
        pie_chart=pie_chart
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

if __name__ == '__main__':
    app.run(debug=True)
    
