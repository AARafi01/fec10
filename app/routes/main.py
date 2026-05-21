import os
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from app.extensions import exam_repo, login_log_repo, config_service
from app.utils.app_helpers import normalize_registration, load_nonempty_lines, extract_exam_display_fields
from app.utils.app_helpers import DEFAULT_EXAM_YEAR

main_bp = Blueprint('main', __name__)

ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME') or config_service.get('SETTINGS', 'ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD') or config_service.get('SETTINGS', 'ADMIN_PASSWORD', 'admin')

def get_enriched_exams(exams):
    if not exams:
        return []
    
    exam_ids = tuple(exam['exam_id'] for exam in exams)
    result_data_map = {}
    
    if exam_ids:
        placeholders = ','.join(['?'] * len(exam_ids))
        query = f'''
            SELECT exam_id, result_data 
            FROM results 
            WHERE exam_id IN ({placeholders}) 
            GROUP BY exam_id 
            HAVING result_data IS NOT NULL
        '''
        with exam_repo.db.get_connection() as conn:
            try:
                cursor = conn.execute(query, exam_ids)
                for row in cursor.fetchall():
                    result_data_map[row['exam_id']] = row['result_data']
            except Exception:
                pass
    
    enriched = []
    for exam in exams:
        exam_dict = dict(exam)
        result_data_json = result_data_map.get(exam_dict['exam_id'])
        exam_year, pub_date = extract_exam_display_fields(result_data_json, exam_dict.get('created_at'), DEFAULT_EXAM_YEAR)
        exam_dict['exam_year'] = exam_year
        exam_dict['pub_date'] = pub_date
        enriched.append(exam_dict)
    return enriched

@main_bp.before_request
def check_student_login():
    if request.path.startswith('/static') or request.path in ['/student_login','/login','/logout'] or request.path.startswith('/admin') or request.path.startswith('/api/') or request.path.startswith('/internal'):
        return None
    if session.get('student_reg') or session.get('logged_in'):
        return None
    return redirect(url_for('main.student_login'))

@main_bp.route('/student_login', methods=['GET', 'POST'])
def student_login():
    if session.get('student_reg') or session.get('logged_in'):
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        reg_no = request.form.get('registration_no', '').strip()
        if not reg_no:
            flash('Registration number is required', 'error')
            return render_template('student_login.html')
        normalized_input = normalize_registration(reg_no)
        matched_reg = next((line_clean for line_clean in load_nonempty_lines() if normalize_registration(line_clean) == normalized_input), None)
        if matched_reg:
            session.permanent = True
            session['student_reg'] = matched_reg
            login_time = datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')
            login_log_repo.log_login(matched_reg, login_time)
            return redirect(url_for('main.index'))
        else:
            flash('Registration number not found! Please check and try again.', 'error')
    return render_template('student_login.html')

@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('admin.admin'))
    if request.method == 'POST':
        if request.form.get('username') == ADMIN_USERNAME and request.form.get('password') == ADMIN_PASSWORD:
            session.permanent = True
            session['logged_in'] = True
            session['username'] = ADMIN_USERNAME
            return redirect(url_for('admin.admin'))
        flash('Wait a min... Who are you ?!!', 'error')
    return render_template('login.html')

@main_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('main.index'))

@main_bp.route('/')
def index():
    return render_template('index.html', exams=get_enriched_exams(exam_repo.get_active()))

@main_bp.route('/gpa_calc')
def gpa_calc_page():
    return render_template('gpa_calc.html')
