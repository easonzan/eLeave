from flask import Flask, render_template, request, redirect, url_for, send_file, flash
import sqlite3
import pandas as pd
from io import BytesIO
import os
import re
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'eleave-secret-key-change-in-production')

# 年度按当前年动态扩展：2023 为起始年，每年只增加当年列（26 年只有 2023–2026，27 年再出现 2027）
START_YEAR = 2023
def _get_years():
    current = datetime.now().year
    return list(range(START_YEAR, current + 1))
YEARS = _get_years()
YEAR_COLUMNS = [f'total_days_{y}' for y in YEARS]
YEAR_COLUMNS_CN = [f'{y}年度总天数' for y in YEARS]

def get_employee_year_slice(employee_row):
    """从 employee 行元组中取出各年度天数（从第4列起共 len(YEARS) 列）"""
    return employee_row[3:3 + len(YEARS)]


def normalize_employee_row(employee_row):
    """保证 employee 行与当前 YEAR_COLUMNS 数量一致，不足的年度列补 0（兼容迁移前旧表）"""
    if not employee_row or len(employee_row) < 3:
        return employee_row
    base = list(employee_row[:3])
    year_vals = list(employee_row[3:])
    while len(year_vals) < len(YEAR_COLUMNS):
        year_vals.append(0)
    return tuple(base + year_vals[: len(YEAR_COLUMNS)])

# Initialize database
def init_db():
    conn = sqlite3.connect('leave_management.db')
    c = conn.cursor()
    year_cols_sql = ', '.join(f'{col} REAL NOT NULL DEFAULT 0' for col in YEAR_COLUMNS)
    c.execute(f'''CREATE TABLE IF NOT EXISTS Employees (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        {year_cols_sql})''')
    c.execute('''CREATE TABLE IF NOT EXISTS LeaveRecords (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER,
        leave_info TEXT,
        start_date TEXT,
        end_date TEXT,
        days REAL,
        application_time TEXT,
        leave_type TEXT,
        remark TEXT,
        FOREIGN KEY(employee_id) REFERENCES Employees(id))''')
    conn.commit()
    conn.close()

# 对已有数据库做迁移：仅追加当前 YEARS 中缺失的年度列（当年才加当年列）
def migrate_db():
    conn = sqlite3.connect('leave_management.db')
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Employees'")
    if not c.fetchone():
        conn.close()
        return
    c.execute('PRAGMA table_info(Employees)')
    existing = {row[1] for row in c.fetchall()}
    for col in YEAR_COLUMNS:
        if col not in existing:
            c.execute(f'ALTER TABLE Employees ADD COLUMN {col} REAL NOT NULL DEFAULT 0')
    conn.commit()
    conn.close()

# Homepage
@app.route('/')
def index():
    if os.path.exists('leave_management.db'):
        migrate_db()
    conn = sqlite3.connect('leave_management.db')
    c = conn.cursor()
    c.execute('SELECT * FROM Employees')
    employees = [normalize_employee_row(r) for r in c.fetchall()]
    conn.close()
    return render_template('index.html', employees=employees, year_columns_cn=YEAR_COLUMNS_CN, num_years=len(YEARS))

# Employee detail page
@app.route('/employee/<int:employee_id>')
def employee(employee_id):
    conn = sqlite3.connect('leave_management.db')
    c = conn.cursor()
    c.execute('SELECT * FROM Employees WHERE id=?', (employee_id,))
    employee = c.fetchone()
    if employee is None:
        conn.close()
        return "员工不存在", 404
    employee = normalize_employee_row(employee)
    total_annual_days = sum(get_employee_year_slice(employee))
    c.execute('SELECT id, leave_info, application_time, leave_type, remark, days FROM LeaveRecords WHERE employee_id=? ORDER BY application_time ASC', (employee_id,))
    leave_records = c.fetchall()
    # Calculate remaining days for each record
    leave_records_with_remaining = []
    remaining_days = total_annual_days
    for record in leave_records:
        days = record[5] if record[5] is not None else 0
        if record[3] == '年假' and days > 0:
            remaining_days -= days
        leave_records_with_remaining.append(record + (remaining_days,))
    conn.close()
    return render_template('employee.html', employee=employee, leave_records=leave_records_with_remaining, total_annual_days=total_annual_days, year_columns_cn=YEAR_COLUMNS_CN, num_years=len(YEARS))

# All leave records page
@app.route('/all_leaves')
def all_leaves():
    conn = sqlite3.connect('leave_management.db')
    c = conn.cursor()
    c.execute('''
        SELECT e.id, e.name, lr.id as leave_id, lr.leave_info, lr.application_time, lr.leave_type, lr.remark, lr.days
        FROM Employees e
        LEFT JOIN LeaveRecords lr ON e.id = lr.employee_id
        ORDER BY e.id, lr.application_time ASC
    ''')
    leave_records = c.fetchall()
    # Group records by employee
    employees_leaves = {}
    for record in leave_records:
        emp_id = record[0]
        if emp_id not in employees_leaves:
            employees_leaves[emp_id] = {'name': record[1], 'leaves': [], 'total_annual_days': 0}
        if record[2]:  # Check if leave_id exists (not NULL)
            employees_leaves[emp_id]['leaves'].append(list(record[2:]))
    # Calculate total and remaining days
    cols = ', '.join(YEAR_COLUMNS)
    for emp_id in employees_leaves:
        c.execute(f'SELECT {cols} FROM Employees WHERE id=?', (emp_id,))
        totals = c.fetchone()
        total_annual_days = sum(totals) if totals else 0
        employees_leaves[emp_id]['total_annual_days'] = total_annual_days
        remaining_days = total_annual_days
        for leave in employees_leaves[emp_id]['leaves']:
            days = leave[5] if leave[5] is not None else 0
            if leave[3] == '年假' and days > 0:
                remaining_days -= days
            leave.append(remaining_days)
    conn.close()
    return render_template('all_leaves.html', employees_leaves=employees_leaves)

# Add employee
@app.route('/add_employee', methods=['GET', 'POST'])
def add_employee():
    if request.method == 'POST':
        id = request.form['id']
        name = request.form['name']
        email = request.form['email']
        year_values = [float(request.form.get(col, 0) or 0) for col in YEAR_COLUMNS]
        conn = sqlite3.connect('leave_management.db')
        c = conn.cursor()
        placeholders = ', '.join(['?'] * (3 + len(YEAR_COLUMNS)))
        cols = 'id, name, email, ' + ', '.join(YEAR_COLUMNS)
        try:
            c.execute(f'INSERT INTO Employees ({cols}) VALUES ({placeholders})',
                      (id, name, email, *year_values))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return "工号已存在", 400
        conn.close()
        return redirect(url_for('index'))
    return render_template('add_employee.html', year_pairs=list(zip(YEAR_COLUMNS, YEAR_COLUMNS_CN)))

# Edit employee
@app.route('/edit_employee/<int:employee_id>', methods=['GET', 'POST'])
def edit_employee(employee_id):
    conn = sqlite3.connect('leave_management.db')
    c = conn.cursor()
    c.execute('SELECT * FROM Employees WHERE id=?', (employee_id,))
    employee = c.fetchone()
    if employee is None:
        conn.close()
        return "员工不存在", 404
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        year_values = [float(request.form.get(col, 0) or 0) for col in YEAR_COLUMNS]
        set_clause = 'name=?, email=?, ' + ', '.join(f'{col}=?' for col in YEAR_COLUMNS) + ' WHERE id=?'
        c.execute(f'UPDATE Employees SET {set_clause}', (name, email, *year_values, employee_id))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))
    conn.close()
    employee = normalize_employee_row(employee)
    return render_template('edit_employee.html', employee=employee, year_pairs=list(zip(YEAR_COLUMNS, YEAR_COLUMNS_CN)))

# Delete employee
@app.route('/delete_employee/<int:employee_id>', methods=['GET', 'POST'])
def delete_employee(employee_id):
    conn = sqlite3.connect('leave_management.db')
    c = conn.cursor()
    c.execute('SELECT * FROM Employees WHERE id=?', (employee_id,))
    employee = c.fetchone()
    if employee is None:
        conn.close()
        return "员工不存在", 404
    if request.method == 'POST':
        c.execute('DELETE FROM LeaveRecords WHERE employee_id=?', (employee_id,))
        c.execute('DELETE FROM Employees WHERE id=?', (employee_id,))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))
    conn.close()
    return render_template('confirm_delete.html', employee=employee)

# Add leave record
@app.route('/employee/<int:employee_id>/add_leave', methods=['GET', 'POST'])
def add_leave(employee_id):
    if request.method == 'POST':
        start_date = request.form.get('start_date', '')
        start_period = request.form.get('start_period', '上午')
        end_date = request.form.get('end_date', '')
        end_period = request.form.get('end_period', '上午')
        days = request.form.get('days', '')
        application_time = request.form.get('application_time', '')
        leave_type = request.form.get('leave_type', '年假')
        remark = request.form.get('remark', '')
        # Construct leave_info with '天' unit
        if start_date and end_date and days:
            leave_info = f"{start_date.replace('-', '/')}{' ' + start_period if start_period else ''}~{end_date.replace('-', '/')}{' ' + end_period if end_period else ''}, {days}天 {leave_type}"
        else:
            leave_info = ''
        # Convert days
        try:
            days = float(days) if days else None
        except ValueError:
            days = None
        # Store start_date and end_date with period
        start_date_full = f"{start_date} {start_period}" if start_date and start_period else start_date
        end_date_full = f"{end_date} {end_period}" if end_date and end_period else end_date
        conn = sqlite3.connect('leave_management.db')
        c = conn.cursor()
        c.execute('INSERT INTO LeaveRecords (employee_id, leave_info, start_date, end_date, days, application_time, leave_type, remark) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                  (employee_id, leave_info, start_date_full or None, end_date_full or None, days, application_time or None, leave_type, remark or None))
        conn.commit()
        conn.close()
        return redirect(url_for('employee', employee_id=employee_id))
    return render_template('add_leave.html', employee_id=employee_id)

# Edit leave record
@app.route('/employee/<int:employee_id>/edit_leave/<int:leave_id>', methods=['GET', 'POST'])
def edit_leave(employee_id, leave_id):
    conn = sqlite3.connect('leave_management.db')
    c = conn.cursor()
    c.execute('SELECT * FROM LeaveRecords WHERE id=? AND employee_id=?', (leave_id, employee_id))
    leave = c.fetchone()
    if not leave:
        conn.close()
        return "休假记录不存在", 404
    if request.method == 'POST':
        start_date = request.form.get('start_date', '')
        start_period = request.form.get('start_period', '上午')
        end_date = request.form.get('end_date', '')
        end_period = request.form.get('end_period', '上午')
        days = request.form.get('days', '')
        application_time = request.form.get('application_time', '')
        leave_type = request.form.get('leave_type', '年假')
        remark = request.form.get('remark', '')
        # Construct leave_info with '天' unit
        if start_date and end_date and days:
            leave_info = f"{start_date.replace('-', '/')}{' ' + start_period if start_period else ''}~{end_date.replace('-', '/')}{' ' + end_period if end_period else ''}, {days}天 {leave_type}"
        else:
            leave_info = ''
        # Convert days
        try:
            days = float(days) if days else None
        except ValueError:
            days = None
        # Store start_date and end_date with period
        start_date_full = f"{start_date} {start_period}" if start_date and start_period else start_date
        end_date_full = f"{end_date} {end_period}" if end_date and end_period else end_date
        c.execute('''UPDATE LeaveRecords SET
                     leave_info=?, start_date=?, end_date=?, days=?,
                     application_time=?, leave_type=?, remark=?
                     WHERE id=? AND employee_id=?''',
                  (leave_info, start_date_full or None, end_date_full or None, days,
                   application_time or None, leave_type, remark or None, leave_id, employee_id))
        conn.commit()
        conn.close()
        return redirect(url_for('employee', employee_id=employee_id))
    # Parse existing data for form
    start_date, start_period = (leave[3].split(' ') + ['上午'])[:2] if leave[3] else ('', '上午')
    end_date, end_period = (leave[4].split(' ') + ['上午'])[:2] if leave[4] else ('', '上午')
    conn.close()
    return render_template('edit_leave.html', employee_id=employee_id, leave=leave,
                         start_date=start_date, start_period=start_period,
                         end_date=end_date, end_period=end_period)

# Delete leave record
@app.route('/employee/<int:employee_id>/delete_leave/<int:leave_id>', methods=['GET', 'POST'])
def delete_leave(employee_id, leave_id):
    conn = sqlite3.connect('leave_management.db')
    c = conn.cursor()
    c.execute('SELECT * FROM LeaveRecords WHERE id=? AND employee_id=?', (leave_id, employee_id))
    leave = c.fetchone()
    if not leave:
        conn.close()
        return "休假记录不存在", 404
    if request.method == 'POST':
        c.execute('DELETE FROM LeaveRecords WHERE id=? AND employee_id=?', (leave_id, employee_id))
        conn.commit()
        conn.close()
        return redirect(url_for('employee', employee_id=employee_id))
    conn.close()
    return render_template('confirm_delete_leave.html', employee_id=employee_id, leave=leave)

# Import employee data（兼容历史 Excel：仅有 2023–2025 列时，2026/2027 自动填 0）
@app.route('/import_employees', methods=['POST'])
def import_employees():
    file = request.files['file']
    if not file or not file.filename.endswith('.xlsx'):
        return "请上传有效的 .xlsx 文件", 400
    try:
        df = pd.read_excel(file, engine='openpyxl')
    except Exception as e:
        return f"读取 Excel 文件失败: {str(e)}", 400
    column_mapping = {'工号': 'id', '姓名': 'name', '邮箱': 'email'}
    column_mapping.update({cn: col for cn, col in zip(YEAR_COLUMNS_CN, YEAR_COLUMNS)})
    df = df.rename(columns=column_mapping)
    base_required = ['id', 'name', 'email'] + [f'total_days_{y}' for y in (2023, 2024, 2025)]
    if not all(col in df.columns for col in base_required):
        missing_cols = [col for col in base_required if col not in df.columns]
        return f"Excel 文件缺少必要列: {', '.join(missing_cols)}", 400
    for col in base_required:
        if df[col].isna().any():
            return f"列 '{col}' 包含空值", 400
    for col in YEAR_COLUMNS:
        if col not in df.columns:
            df[col] = 0
    use_columns = ['id', 'name', 'email'] + YEAR_COLUMNS
    conn = sqlite3.connect('leave_management.db')
    try:
        df[use_columns].to_sql('Employees', conn, if_exists='append', index=False)
    except sqlite3.IntegrityError:
        conn.close()
        return "工号重复", 400
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

# Export employee data（导出含全部年度列，便于来年再导入）
@app.route('/export_employees')
def export_employees():
    conn = sqlite3.connect('leave_management.db')
    df = pd.read_sql_query('SELECT * FROM Employees', conn)
    conn.close()
    output = BytesIO()
    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)
    return send_file(output, download_name='employees.xlsx', as_attachment=True)

# Export leave records for a single employee
@app.route('/employee/<int:employee_id>/export_leaves')
def export_leaves(employee_id):
    conn = sqlite3.connect('leave_management.db')
    c = conn.cursor()
    c.execute('SELECT * FROM Employees WHERE id=?', (employee_id,))
    employee = c.fetchone()
    if not employee:
        conn.close()
        return "员工不存在", 404
    year_cols_sql = ', '.join(f'e.{col}' for col in YEAR_COLUMNS)
    df = pd.read_sql_query(f'''
        SELECT e.id, e.name, e.email, {year_cols_sql},
               lr.leave_info, lr.application_time, lr.leave_type, lr.remark, lr.days
        FROM Employees e
        LEFT JOIN LeaveRecords lr ON e.id = lr.employee_id
        WHERE e.id = ?
        ORDER BY lr.application_time ASC
    ''', conn, params=(employee_id,))
    conn.close()
    df['总年休假天数'] = df[YEAR_COLUMNS].sum(axis=1)
    # Calculate remaining days
    remaining_days = df['总年休假天数'].iloc[0] if not df.empty else 0
    df['剩余年休假天数'] = 0.0
    for i in range(len(df)):
        days = df['days'].iloc[i] if pd.notna(df['days'].iloc[i]) else 0
        if df['leave_type'].iloc[i] == '年假' and days > 0:
            remaining_days -= days
        df.loc[i, '剩余年休假天数'] = remaining_days
    rename_map = {'id': '工号', 'name': '姓名', 'email': '邮箱',
                  'leave_info': '2023年至今已休年假信息', 'application_time': '邮件申请时间',
                  'leave_type': '假期类型', 'remark': '备注', 'days': '本次休假天数'}
    rename_map.update({col: cn for col, cn in zip(YEAR_COLUMNS, YEAR_COLUMNS_CN)})
    df = df.rename(columns=rename_map)
    export_cols = ['工号', '姓名', '邮箱'] + YEAR_COLUMNS_CN + ['2023年至今已休年假信息', '总年休假天数', '剩余年休假天数', '邮件申请时间', '假期类型', '本次休假天数', '备注']
    output = BytesIO()
    df[export_cols].to_excel(output, index=False, engine='openpyxl')
    output.seek(0)
    return send_file(output, download_name=f'leave_records_{employee_id}.xlsx', as_attachment=True)

# Export all leave records
@app.route('/export_all_leaves')
def export_all_leaves():
    conn = sqlite3.connect('leave_management.db')
    year_cols_sql = ', '.join(f'e.{col}' for col in YEAR_COLUMNS)
    df = pd.read_sql_query(f'''
        SELECT e.id, e.name, e.email, {year_cols_sql},
               lr.leave_info, lr.application_time, lr.leave_type, lr.remark, lr.days
        FROM Employees e
        LEFT JOIN LeaveRecords lr ON e.id = lr.employee_id
        ORDER BY e.id, lr.application_time ASC
    ''', conn)
    conn.close()
    df['总年休假天数'] = df[YEAR_COLUMNS].sum(axis=1)
    # Calculate remaining days per employee
    df['剩余年休假天数'] = 0.0
    for emp_id in df['id'].unique():
        emp_mask = df['id'] == emp_id
        remaining_days = df.loc[emp_mask, '总年休假天数'].iloc[0] if emp_mask.any() else 0
        for i in df[emp_mask].index:
            days = df.loc[i, 'days'] if pd.notna(df.loc[i, 'days']) else 0
            if df.loc[i, 'leave_type'] == '年假' and days > 0:
                remaining_days -= days
            df.loc[i, '剩余年休假天数'] = remaining_days
    rename_map = {'id': '工号', 'name': '姓名', 'email': '邮箱',
                  'leave_info': '2023年至今已休年假信息', 'application_time': '邮件申请时间',
                  'leave_type': '假期类型', 'remark': '备注', 'days': '本次休假天数'}
    rename_map.update({col: cn for col, cn in zip(YEAR_COLUMNS, YEAR_COLUMNS_CN)})
    df = df.rename(columns=rename_map)
    export_cols = ['工号', '姓名', '邮箱'] + YEAR_COLUMNS_CN + ['2023年至今已休年假信息', '总年休假天数', '剩余年休假天数', '邮件申请时间', '假期类型', '本次休假天数', '备注']
    output = BytesIO()
    df[export_cols].to_excel(output, index=False, engine='openpyxl')
    output.seek(0)
    return send_file(output, download_name='all_leave_records.xlsx', as_attachment=True)


def _parse_days_from_leave_info(leave_info):
    """从「已休年假信息」中解析本次天数，如 ', 2.5天 年假' -> 2.5"""
    if not leave_info or pd.isna(leave_info):
        return None
    s = str(leave_info).strip()
    m = re.search(r'[,，]\s*(\d+(?:\.\d+)?)\s*天', s) or re.search(r'(\d+(?:\.\d+)?)\s*天', s)
    return float(m.group(1)) if m else None


def _parse_start_end_from_leave_info(leave_info):
    """从「已休年假信息」解析起止日期，如 '2024/1/1 上午~2024/1/3 下午' -> (start_full, end_full)"""
    if not leave_info or pd.isna(leave_info):
        return None, None
    s = str(leave_info).strip()
    part = s.split(',')[0].strip() if ',' in s else s
    if '~' not in part:
        return None, None
    a, b = part.split('~', 1)
    a, b = a.strip(), b.strip()
    def norm(x):
        x = x.replace('/', '-')
        if re.match(r'\d{4}-\d{1,2}-\d{1,2}', x):
            return x
        return x
    return norm(a), norm(b)


# 导入休假记录（与「导出所有休假记录」同格式的 xlsx，兼容无「本次休假天数」列的历史导出）
@app.route('/import_leave_records', methods=['POST'])
def import_leave_records():
    file = request.files.get('file')
    if not file or not file.filename.lower().endswith('.xlsx'):
        return "请上传有效的 .xlsx 文件（与「导出所有休假记录」格式一致）", 400
    try:
        df = pd.read_excel(file, engine='openpyxl')
    except Exception as e:
        return f"读取 Excel 失败: {str(e)}", 400
    # 列名兼容中英文
    col_cn = {
        '工号': 'id', '姓名': 'name', '邮箱': 'email',
        '2023年至今已休年假信息': 'leave_info', '邮件申请时间': 'application_time',
        '假期类型': 'leave_type', '备注': 'remark', '本次休假天数': 'days'
    }
    df = df.rename(columns=col_cn)
    if 'leave_info' not in df.columns:
        return "Excel 缺少列「2023年至今已休年假信息」", 400
    if 'id' not in df.columns:
        return "Excel 缺少列「工号」", 400
    # 只处理有休假内容的行
    df = df[df['leave_info'].notna() & (df['leave_info'].astype(str).str.strip() != '')]
    if df.empty:
        return "文件中没有有效的休假记录行", 400
    conn = sqlite3.connect('leave_management.db')
    c = conn.cursor()
    c.execute('SELECT id FROM Employees')
    valid_ids = {row[0] for row in c.fetchall()}
    inserted, skipped_no_emp, skipped_dup = 0, 0, 0
    for _, row in df.iterrows():
        eid = row.get('id')
        if pd.isna(eid):
            skipped_no_emp += 1
            continue
        try:
            eid = int(eid)
        except (TypeError, ValueError):
            skipped_no_emp += 1
            continue
        if eid not in valid_ids:
            skipped_no_emp += 1
            continue
        leave_info = row.get('leave_info')
        leave_info = None if pd.isna(leave_info) else str(leave_info).strip() or None
        application_time = row.get('application_time')
        application_time = None if pd.isna(application_time) else str(application_time).strip() or None
        leave_type = row.get('leave_type')
        leave_type = '年假' if pd.isna(leave_type) or str(leave_type).strip() == '' else str(leave_type).strip()
        remark = row.get('remark')
        remark = None if pd.isna(remark) else str(remark).strip() or None
        days = row.get('days')
        if pd.isna(days) or (isinstance(days, str) and days.strip() == ''):
            days = _parse_days_from_leave_info(leave_info)
        else:
            try:
                days = float(days)
            except (TypeError, ValueError):
                days = _parse_days_from_leave_info(leave_info)
        start_full, end_full = _parse_start_end_from_leave_info(leave_info)
        # 防重复：同一员工、同一申请时间、同一 leave_info 视为同一条
        c.execute('SELECT 1 FROM LeaveRecords WHERE employee_id=? AND application_time=? AND leave_info=? LIMIT 1',
                  (eid, application_time, leave_info))
        if c.fetchone():
            skipped_dup += 1
            continue
        c.execute('''INSERT INTO LeaveRecords (employee_id, leave_info, start_date, end_date, days, application_time, leave_type, remark)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                  (eid, leave_info, start_full, end_full, days, application_time, leave_type, remark))
        inserted += 1
    conn.commit()
    conn.close()
    msg = f"休假记录导入完成：成功 {inserted} 条"
    if skipped_no_emp:
        msg += f"，工号不存在或无效跳过 {skipped_no_emp} 条"
    if skipped_dup:
        msg += f"，重复跳过 {skipped_dup} 条"
    flash(msg)
    return redirect(url_for('index'))


if __name__ == '__main__':
    if not os.path.exists('leave_management.db'):
        init_db()
    else:
        migrate_db()
    app.run(host='0.0.0.0', port=8000)
