from flask import Flask, render_template, request, redirect, url_for, send_file
import sqlite3
import pandas as pd
from io import BytesIO
import os

app = Flask(__name__)

# Initialize database
def init_db():
    conn = sqlite3.connect('leave_management.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS Employees (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        total_days_2023 REAL NOT NULL,
        total_days_2024 REAL NOT NULL,
        total_days_2025 REAL NOT NULL)''')
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

# Homepage
@app.route('/')
def index():
    conn = sqlite3.connect('leave_management.db')
    c = conn.cursor()
    c.execute('SELECT * FROM Employees')
    employees = c.fetchall()
    conn.close()
    return render_template('index.html', employees=employees)

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
    total_annual_days = sum(employee[3:6])
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
    return render_template('employee.html', employee=employee, leave_records=leave_records_with_remaining, total_annual_days=total_annual_days)

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
    for emp_id in employees_leaves:
        c.execute('SELECT total_days_2023, total_days_2024, total_days_2025 FROM Employees WHERE id=?', (emp_id,))
        totals = c.fetchone()
        total_annual_days = sum(totals)
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
        total_days_2023 = float(request.form['total_days_2023'])
        total_days_2024 = float(request.form['total_days_2024'])
        total_days_2025 = float(request.form['total_days_2025'])
        conn = sqlite3.connect('leave_management.db')
        c = conn.cursor()
        try:
            c.execute('INSERT INTO Employees (id, name, email, total_days_2023, total_days_2024, total_days_2025) VALUES (?, ?, ?, ?, ?, ?)',
                      (id, name, email, total_days_2023, total_days_2024, total_days_2025))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return "工号已存在", 400
        conn.close()
        return redirect(url_for('index'))
    return render_template('add_employee.html')

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
        total_days_2023 = float(request.form['total_days_2023'])
        total_days_2024 = float(request.form['total_days_2024'])
        total_days_2025 = float(request.form['total_days_2025'])
        c.execute('UPDATE Employees SET name=?, email=?, total_days_2023=?, total_days_2024=?, total_days_2025=? WHERE id=?',
                  (name, email, total_days_2023, total_days_2024, total_days_2025, employee_id))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))
    conn.close()
    return render_template('edit_employee.html', employee=employee)

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

# Import employee data
@app.route('/import_employees', methods=['POST'])
def import_employees():
    file = request.files['file']
    if not file or not file.filename.endswith('.xlsx'):
        return "请上传有效的 .xlsx 文件", 400
    try:
        df = pd.read_excel(file, engine='openpyxl')
    except Exception as e:
        return f"读取 Excel 文件失败: {str(e)}", 400
    column_mapping = {
        '工号': 'id',
        '姓名': 'name',
        '邮箱': 'email',
        '2023年度总天数': 'total_days_2023',
        '2024年度总天数': 'total_days_2024',
        '2025年度总天数': 'total_days_2025'
    }
    df = df.rename(columns=column_mapping)
    required_columns = ['id', 'name', 'email', 'total_days_2023', 'total_days_2024', 'total_days_2025']
    if not all(col in df.columns for col in required_columns):
        missing_cols = [col for col in required_columns if col not in df.columns]
        return f"Excel 文件缺少必要列: {', '.join(missing_cols)}", 400
    # Check for missing values
    for col in required_columns:
        if df[col].isna().any():
            return f"列 '{col}' 包含空值", 400
    conn = sqlite3.connect('leave_management.db')
    try:
        df[required_columns].to_sql('Employees', conn, if_exists='append', index=False)
    except sqlite3.IntegrityError:
        conn.close()
        return "工号重复", 400
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

# Export employee data
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
    df = pd.read_sql_query('''
        SELECT e.id, e.name, e.email, e.total_days_2023, e.total_days_2024, e.total_days_2025,
               lr.leave_info, lr.application_time, lr.leave_type, lr.remark, lr.days
        FROM Employees e
        LEFT JOIN LeaveRecords lr ON e.id = lr.employee_id
        WHERE e.id = ?
        ORDER BY lr.application_time ASC
    ''', conn, params=(employee_id,))
    conn.close()
    df['总年休假天数'] = df[['total_days_2023', 'total_days_2024', 'total_days_2025']].sum(axis=1)
    # Calculate remaining days
    remaining_days = df['总年休假天数'].iloc[0] if not df.empty else 0
    df['剩余年休假天数'] = 0.0
    for i in range(len(df)):
        days = df['days'].iloc[i] if pd.notna(df['days'].iloc[i]) else 0
        if df['leave_type'].iloc[i] == '年假' and days > 0:
            remaining_days -= days
        df.loc[i, '剩余年休假天数'] = remaining_days
    df = df.rename(columns={
        'id': '工号',
        'name': '姓名',
        'email': '邮箱',
        'total_days_2023': '2023年度总天数',
        'total_days_2024': '2024年度总天数',
        'total_days_2025': '2025年度总天数',
        'leave_info': '2023年至今已休年假信息',
        'application_time': '邮件申请时间',
        'leave_type': '假期类型',
        'remark': '备注'
    })
    output = BytesIO()
    df[[
        '工号', '姓名', '邮箱', '2023年度总天数', '2024年度总天数', '2025年度总天数',
        '2023年至今已休年假信息', '总年休假天数', '剩余年休假天数', '邮件申请时间', '假期类型', '备注'
    ]].to_excel(output, index=False, engine='openpyxl')
    output.seek(0)
    return send_file(output, download_name=f'leave_records_{employee_id}.xlsx', as_attachment=True)

# Export all leave records
@app.route('/export_all_leaves')
def export_all_leaves():
    conn = sqlite3.connect('leave_management.db')
    df = pd.read_sql_query('''
        SELECT e.id, e.name, e.email, e.total_days_2023, e.total_days_2024, e.total_days_2025,
               lr.leave_info, lr.application_time, lr.leave_type, lr.remark, lr.days
        FROM Employees e
        LEFT JOIN LeaveRecords lr ON e.id = lr.employee_id
        ORDER BY e.id, lr.application_time ASC
    ''', conn)
    conn.close()
    df['总年休假天数'] = df[['total_days_2023', 'total_days_2024', 'total_days_2025']].sum(axis=1)
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
    df = df.rename(columns={
        'id': '工号',
        'name': '姓名',
        'email': '邮箱',
        'total_days_2023': '2023年度总天数',
        'total_days_2024': '2024年度总天数',
        'total_days_2025': '2025年度总天数',
        'leave_info': '2023年至今已休年假信息',
        'application_time': '邮件申请时间',
        'leave_type': '假期类型',
        'remark': '备注'
    })
    output = BytesIO()
    df[[
        '工号', '姓名', '邮箱', '2023年度总天数', '2024年度总天数', '2025年度总天数',
        '2023年至今已休年假信息', '总年休假天数', '剩余年休假天数', '邮件申请时间', '假期类型', '备注'
    ]].to_excel(output, index=False, engine='openpyxl')
    output.seek(0)
    return send_file(output, download_name='all_leave_records.xlsx', as_attachment=True)

if __name__ == '__main__':
    if not os.path.exists('leave_management.db'):
        init_db()
    app.run(host='0.0.0.0', port=8000)