from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from app.extensions import exam_repo, result_repo, login_log_repo, result_service, api_results_cache, merge_log_repo
from app.routes.main import get_enriched_exams
from app.utils.app_helpers import DEFAULT_SESSION_ID, DEFAULT_PROGRAM_ID, build_regular_exam_name
from app.utils.utils import is_retake_improvement

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('Please log in to access the admin panel', 'error')
            return redirect(url_for('main.login'))
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/')
@login_required
def admin():
    return render_template('admin.html', exams=get_enriched_exams(exam_repo.get_all()), login_logs=login_log_repo.get_all_logs(), merge_logs=merge_log_repo.get_all())

@admin_bp.route('/add_exam', methods=['POST'])
@login_required
def add_exam():
    exam_id = request.form.get('exam_id', '').strip()
    exam_name = request.form.get('exam_name', '').strip()
    semester = request.form.get('semester', '').strip()
    
    if semester and not exam_name:
        exam_name = build_regular_exam_name(semester)
        
    is_retake = request.form.get('is_retake') == '1' or (exam_name and is_retake_improvement(exam_name))
    
    if is_retake:
        if not exam_id or not exam_name:
            flash('Exam ID and Name are required', 'error')
        else:
            session_id = request.form.get('session_id', DEFAULT_SESSION_ID)
            # If the admin explicitly supplied a regular_exam_id, use it directly;
            # otherwise let the service resolve it by semester + session.
            # The service will store the retake→regular mapping in retake_mappings,
            # so /internal/ingest can find it. No separate exams row is created.
            target_regular_id = request.form.get('regular_exam_id', '').strip()
            if target_regular_id:
                result_repo.update_scrape_job_status(exam_id, 'failed')
                res = result_service.process_improvement_results(exam_id, target_regular_id, triggered_by='admin')
                res.setdefault('regular_exam', {'exam_id': target_regular_id})
            else:
                result_repo.update_scrape_job_status(exam_id, 'failed')
                res = result_service.resolve_and_process_improvement(exam_id, exam_name, session_id, triggered_by='admin')

            if not res.get('success') and not res.get('regular_exam'):
                flash(res.get('message', 'No corresponding regular exam found.'), 'error')
            elif res.get('success'):
                if res.get('queued'):
                    flash(f'Retake scrape queued for {res.get("total_students", 0)} students.', 'success')
                else:
                    flash('Retake results merged successfully!', 'success')
            else:
                flash(f'Merge error: {res.get("message")}', 'error')
    else:
        if not exam_id or not exam_name or not semester:
            flash('Exam ID and Semester are required', 'error')
        elif exam_repo.get_by_semester_and_session(semester, request.form.get('session_id', DEFAULT_SESSION_ID)):
            flash("Regular exam already exists. Use 'Retake' to merge.", 'error')
        elif exam_repo.create(exam_id, exam_name, request.form.get('program_id', DEFAULT_PROGRAM_ID), request.form.get('session_id', DEFAULT_SESSION_ID), semester):
            result_repo.update_scrape_job_status(exam_id, 'failed')
            res = result_service.process_exam_results(exam_id)
            if res.get('success'):
                if res.get('queued'):
                    flash(f'Exam added and scrape queued for {res.get("total_students", 0)} students.', 'success')
                elif res.get('already_running'):
                    flash('Exam added. A scrape for this exam is already in progress.', 'warning')
                else:
                    flash(f'Exam added and processing {res.get("total_students", 0)} students.', 'success')
            else:
                flash(f'Exam added, but scraper failed: {res.get("message", "Unknown error")}. Configure GITHUB_REPOSITORY and GITHUB_WORKFLOW_TOKEN to enable remote scraping.', 'warning')
        else:
            flash('Exam ID already exists', 'error')
            
    return redirect(url_for('admin.admin'))

@admin_bp.route('/delete_exam/<int:exam_db_id>', methods=['POST'])
@login_required
def delete_exam(exam_db_id):
    with exam_repo.db.get_connection() as conn:
        row = conn.execute('SELECT exam_id FROM exams WHERE id=?', (exam_db_id,)).fetchone()
        if row:
            api_results_cache.pop(row['exam_id'], None)
            
    result = exam_repo.delete(exam_db_id)
    flash('Exam deleted successfully' if result else 'Delete failed', 'success' if result else 'error')
    return redirect(url_for('admin.admin'))

@admin_bp.route('/toggle_exam/<int:exam_db_id>', methods=['POST'])
@login_required
def toggle_exam(exam_db_id):
    result = exam_repo.toggle_active(exam_db_id)
    flash('Exam status updated' if result else 'Exam not found', 'success' if result else 'error')
    return redirect(url_for('admin.admin'))

@admin_bp.route('/retry_scrape/<exam_id>', methods=['POST'])
@login_required
def retry_scrape(exam_id):
    result_repo.update_scrape_job_status(exam_id, 'failed')
    api_results_cache.pop(exam_id, None)
    res = result_service.process_exam_results(exam_id)
    
    if res.get('queued'):
        flash(f'Scrape re-queued for {res.get("total_students", 0)} students.', 'success')
    elif res.get('already_running'):
        flash('Scrape is already in progress.', 'warning')
    elif res.get('from_cache'):
        flash(f'Results already exist ({res.get("message", "")}).', 'info')
    else:
        flash(f'Retry failed: {res.get("message", "Unknown error")}', 'error')
        
    return redirect(url_for('admin.admin'))
