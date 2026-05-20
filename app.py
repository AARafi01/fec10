from flask import Flask,render_template,request,jsonify,redirect,url_for,flash,session
from datetime import timedelta
import gpa_calc
import json
import re
import os
import requests
import html
from functools import wraps
from models import Database,ExamRepository,ResultRepository,LoginLogRepository
from services import ResultService,ConfigService
from utils import standardize_exam_name, is_retake_improvement, parse_semester_from_name
from app_helpers import (
 format_registration_no,
 load_nonempty_lines,
 normalize_registration,
 resolve_registration_from_suffix,
 build_regular_exam_name,
 parse_subject_grades,
 extract_exam_display_fields,
  DEFAULT_PROGRAM_ID,
  DEFAULT_SESSION_ID,
  DEFAULT_EXAM_YEAR,
)

from flask_compress import Compress

app=Flask(__name__)
Compress(app)

config_service = ConfigService()
app.secret_key = os.environ.get('SECRET_KEY') or config_service.get('SETTINGS', 'SECRET_KEY', 'rafi-sama-secret-key-2026-ducmc-scraper')
app.permanent_session_lifetime = timedelta(hours=24)
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME') or config_service.get('SETTINGS', 'ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD') or config_service.get('SETTINGS', 'ADMIN_PASSWORD', 'admin')

db=Database()
db.initialize()
exam_repo=ExamRepository(db)
result_repo=ResultRepository(db)
login_log_repo=LoginLogRepository(db)
result_service=ResultService(exam_repo,result_repo,config_service)

# Global cache for API results
api_results_cache = {}


@app.before_request
def check_student_login():
 if request.path.startswith('/static') or request.path in ['/student_login','/login','/logout'] or request.path.startswith('/admin') or request.path.startswith('/api/') or request.path.startswith('/internal'):
  return None
 if session.get('student_reg') or session.get('logged_in'):
  return None
 return redirect(url_for('student_login'))



@app.route('/student_login',methods=['GET','POST'])
def student_login():
 if session.get('student_reg') or session.get('logged_in'):
  return redirect(url_for('index'))
 if request.method=='POST':
  reg_no=request.form.get('registration_no','').strip()
  if not reg_no:
   flash('Registration number is required','error')
   return render_template('student_login.html')
  normalized_input=normalize_registration(reg_no)
  matched_reg=next((line_clean for line_clean in load_nonempty_lines() if normalize_registration(line_clean)==normalized_input),None)
  if matched_reg:
   session.permanent=True
   session['student_reg']=matched_reg
   from datetime import datetime
   login_time=datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')
   login_log_repo.log_login(matched_reg,login_time)
   return redirect(url_for('index'))
  else:
   flash('Registration number not found! Please check and try again.','error')
 return render_template('student_login.html')


def login_required(f):
 @wraps(f)
 def decorated_function(*args,**kwargs):
  if not session.get('logged_in'):
   flash('Please log in to access the admin panel','error')
   return redirect(url_for('login'))
  return f(*args,**kwargs)
 return decorated_function

def require_api_key(f):
 @wraps(f)
 def decorated_function(*args,**kwargs):
  secret=os.environ.get('API_SECRET','')
  if secret:
   provided=request.args.get('key','') or request.headers.get('X-API-Key','')
   if provided!=secret:
    return jsonify({'error':'Unauthorized'}),401
  return f(*args,**kwargs)
 return decorated_function


@app.route('/login',methods=['GET','POST'])
def login():
 if session.get('logged_in'):return redirect(url_for('admin'))
 if request.method=='POST':
  if request.form.get('username')==ADMIN_USERNAME and request.form.get('password')==ADMIN_PASSWORD:
   session.permanent=True
   session['logged_in']=True
   session['username']=ADMIN_USERNAME
   return redirect(url_for('admin'))
  flash('Wait a min... Who are you ?!!','error')
 return render_template('login.html')


@app.route('/logout')
def logout():
 session.clear()
 return redirect(url_for('index'))
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


@app.route('/')
def index():return render_template('index.html',exams=get_enriched_exams(exam_repo.get_active()))


@app.route('/process_results',methods=['POST'])
def process_results():
 try:
  exam_id=request.form.get('exam_id','').strip()
  if not exam_id:return jsonify({'error':'Exam ID is required'}),400
  api_results_cache.pop(exam_id, None)
  return jsonify(result_service.process_exam_results(exam_id))
 except Exception as e:return jsonify({'error':str(e)}),500


@app.route('/results/<exam_id>')
def view_results(exam_id):
 exam=exam_repo.get_by_exam_id(exam_id)
 results=result_repo.get_by_exam(exam_id)
 for r in results:
  class_roll = r.get('class_roll')
  if class_roll and class_roll.strip().isdigit():
   r['class_roll'] = str(int(class_roll.strip()))
 return render_template('results.html',exam=exam,results=results)
@app.route('/api/results/<exam_id>')
def api_results(exam_id):
 if exam_id in api_results_cache:
  return jsonify(api_results_cache[exam_id])
 results=result_repo.get_by_exam(exam_id)
 formatted=result_repo.format_for_display(results)
 api_results_cache[exam_id]=formatted
 return jsonify(formatted)


@app.route('/admin')
@login_required
def admin():return render_template('admin.html',exams=get_enriched_exams(exam_repo.get_all()),login_logs=login_log_repo.get_all_logs())



@app.route('/admin/add_exam',methods=['POST'])
@login_required
def add_exam():
 exam_id=request.form.get('exam_id','').strip()
 exam_name=request.form.get('exam_name','').strip()
 semester=request.form.get('semester','').strip()
 if semester and not exam_name:
  exam_name = build_regular_exam_name(semester)
 is_retake=request.form.get('is_retake')=='1' or (exam_name and is_retake_improvement(exam_name))
 if is_retake:
  if not exam_id or not exam_name:
   flash('Exam ID and Name are required','error')
  else:
   target_regular_id=request.form.get('regular_exam_id','').strip()
   regular_exam=None
   if target_regular_id:
    regular_exam=exam_repo.get_by_exam_id(target_regular_id)
  if not regular_exam and semester:
   regular_exam=exam_repo.get_by_semester_and_session(semester,request.form.get('session_id',DEFAULT_SESSION_ID))
   if not regular_exam:
    flash('No corresponding regular exam found.','error')
   else:
    res=result_service.process_improvement_results(exam_id,regular_exam['exam_id'])
    if res.get('success'):
     flash('Retake results merged successfully!','success')
    else:
     flash(f'Merge error: {res.get("message")}','error')
 else:
  if not exam_id or not exam_name or not semester:
   flash('Exam ID and Semester are required','error')
  elif exam_repo.get_by_semester_and_session(semester, request.form.get('session_id', DEFAULT_SESSION_ID)):
   flash("Regular exam already exists. Use 'Retake' to merge.",'error')
  elif exam_repo.create(exam_id,exam_name,request.form.get('program_id',DEFAULT_PROGRAM_ID),request.form.get('session_id',DEFAULT_SESSION_ID),semester):
   res = result_service.process_exam_results(exam_id)
   if res.get('success'):
    if res.get('queued'):
     flash(f'Exam added and scrape queued for {res.get("total_students", 0)} students.','success')
    else:
     flash(f'Exam added! Processed {res.get("processed_count", 0)} students.','success')
   else:
    flash('Exam added, but scraper portal failed. Please retry later.','warning')
  else:
   flash('Exam ID already exists','error')
 return redirect(url_for('admin'))


@app.route('/admin/delete_exam/<int:exam_db_id>',methods=['POST'])
@login_required
def delete_exam(exam_db_id):
 with db.get_connection() as conn:
  row = conn.execute('SELECT exam_id FROM exams WHERE id=?', (exam_db_id,)).fetchone()
  if row:
   api_results_cache.pop(row['exam_id'], None)
 result=exam_repo.delete(exam_db_id)
 flash('Exam deleted successfully'if result else'Delete failed','success'if result else'error')
 return redirect(url_for('admin'))
@app.route('/admin/toggle_exam/<int:exam_db_id>',methods=['POST'])
@login_required
def toggle_exam(exam_db_id):
 result=exam_repo.toggle_active(exam_db_id)
 flash('Exam status updated'if result else'Exam not found','success'if result else'error')
 return redirect(url_for('admin'))


@app.route('/admin/clear_cache/<exam_id>',methods=['POST'])
@login_required
def clear_cache(exam_id):
 api_results_cache.pop(exam_id, None)
 count=result_repo.clear_by_exam(exam_id)
 flash(f'Cleared {count} cached results','success')
 return redirect(url_for('admin'))
@app.route('/api/student_grades/<registration_no>')
def api_student_grades(registration_no):
 try:
  if not registration_no or not registration_no.strip():
    return jsonify({'success': False, 'message': 'Registration number is required'})

  # Sanitize: Allow only alphanumeric characters and hyphens to prevent injection and XSS
  sanitized = re.sub(r'[^a-zA-Z0-9-]', '', registration_no)
  if not sanitized:
    return jsonify({'success': False, 'message': 'Invalid registration number format'})

  reg = sanitized.replace('-', '')
  if len(reg) == 10 and reg.isdigit():
    registration_no = format_registration_no(reg)
  elif len(reg) == 3 and reg.isdigit():
    resolved_reg = None
    with db.get_connection() as conn:
      row = conn.execute("SELECT DISTINCT registration_no FROM results WHERE registration_no LIKE ?", (f"%-{reg}",)).fetchone()
      if row:
        resolved_reg = row['registration_no']

    if not resolved_reg:
      try:
        registrations = load_nonempty_lines()
        with db.get_connection() as conn:
          existing_rows = [row['registration_no'] for row in conn.execute('SELECT DISTINCT registration_no FROM results').fetchall()]
        resolved_reg = resolve_registration_from_suffix(reg, existing_rows, registrations)
      except Exception:
        resolved_reg = None

    if resolved_reg:
      registration_no = resolved_reg
    else:
      return jsonify({'success': False, 'message': f'No registration found matching the last 3 digits: {reg}'})
  else:
    registration_no = sanitized

  with db.get_connection() as conn:
    cursor = conn.execute('SELECT exam_id,result_data FROM results WHERE registration_no=?', (registration_no,))
    results = cursor.fetchall()
    if not results:
      return jsonify({'success': False, 'message': 'No results found for this registration number'})

    grades_data = {}
    for row in results:
      try:
        result_data = json.loads(row['result_data']) if row['result_data'] else {}
        subjects = parse_subject_grades(result_data)
        if subjects:
          grades_data[row['exam_id']] = subjects
      except (json.JSONDecodeError, KeyError, ValueError):
        continue

    return jsonify({'success': True, 'grades': grades_data, 'registration_no': registration_no, 'message': f'Found grades for {len(grades_data)} semester(s)'})
 except Exception as e:
  return jsonify({'success': False, 'message': f'Error: {str(e)}'})
@app.route('/gpa_calc')
def gpa_calc_page():return render_template('gpa_calc.html')
@app.route('/api/gpa_courses')
def api_gpa_courses():return jsonify(gpa_calc.courses_data)
@app.route('/api/student_count')
def api_student_count():
 try:
  count=len(load_nonempty_lines())
  return jsonify({'count':count})
 except:return jsonify({'count':0})

def send_telegram_alert(exam_id: str, exam_name: str):
  telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')
  chat_id = os.environ.get('TELEGRAM_CHAT_ID')
  if not telegram_token or not chat_id:
    try:
      config = ConfigService()
      telegram_token = config.get('SETTINGS', 'TELEGRAM_BOT_TOKEN', '')
      chat_id = config.get('SETTINGS', 'TELEGRAM_CHAT_ID', '')
    except Exception:
      pass

  if not telegram_token or not chat_id:
    print("Telegram configuration is missing!")
    return False
  name_lower = exam_name.lower()
  is_retake = "retake" in name_lower or "improvement" in name_lower or "retake/improvement" in name_lower
  exam_type_badge = "🔄 *[Retake/Improvement Exam]*" if is_retake else "📚 *[Regular Semester Exam]*"
  text = (
    "🚨 *New DU CMC Exam Detected!*\n\n"
    f"• *Type*: {exam_type_badge}\n"
    f"• *Exam ID*: `{exam_id}`\n"
    f"• *Name*: `{standardize_exam_name(exam_name)}`\n\n"
    "Would you like to approve and start scraping?"
  )
  reply_markup = {
    "inline_keyboard": [
      [
        {"text": "✅ Approve & Scrape", "callback_data": f"app:{exam_id}"},
        {"text": "❌ Ignore", "callback_data": f"ign:{exam_id}"}
      ]
    ]
  }
  url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
  payload = {
    "chat_id": chat_id,
    "text": text,
    "parse_mode": "Markdown",
    "reply_markup": json.dumps(reply_markup)
  }
  try:
    res = requests.post(url, json=payload, timeout=10)
    return res.status_code == 200
  except Exception as e:
    print(f"Error sending Telegram alert: {e}")
    return False

@app.route('/api/cron/check-exams', methods=['GET', 'POST'])
@require_api_key
def cron_check_exams():
 try:
  from ducmc_result_scraper import DUCMCResultScraper
  available_exams = DUCMCResultScraper.fetch_available_exams_requests("14")
  if not available_exams:
   return jsonify({'status': 'no_data', 'message': 'No available exams fetched from portal'}), 200
  new_count = 0
  with db.get_connection() as conn:
   notified_exams_set = set(row['exam_id'] for row in conn.execute("SELECT exam_id FROM notified_exams").fetchall())
   exams_set = set(row['exam_id'] for row in conn.execute("SELECT exam_id FROM exams").fetchall())
   
  for exam in available_exams:
   exam_id = exam['id']
   exam_name = exam['name']
   is_new = False
   
   if exam_id not in exams_set and exam_id not in notified_exams_set:
    is_new = True
   if is_new:
    with db.get_connection() as conn:
     conn.execute("INSERT OR IGNORE INTO notified_exams(exam_id, exam_name) VALUES(?, ?)", (exam_id, exam_name))
    send_telegram_alert(exam_id, exam_name)
    new_count += 1
  return jsonify({'status': 'success', 'message': f'Checked {len(available_exams)} exams. Notified {new_count} new exams.'}), 200
 except Exception as e:
  return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/telegram/setup')
@require_api_key
def telegram_setup():
 telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')
 if not telegram_token:
  try:
   telegram_token = ConfigService().get('SETTINGS', 'TELEGRAM_BOT_TOKEN', '')
  except Exception:
   pass
 if not telegram_token:
  return jsonify({'status': 'error', 'message': 'TELEGRAM_BOT_TOKEN not found!'}), 400

 api_secret = os.environ.get('API_SECRET', '')
 host = request.headers.get('Host', '')
 scheme = 'https' if 'vercel.app' in host or request.is_secure else 'http'
 webhook_url = f"{scheme}://{host}/api/telegram/webhook"
 telegram_url = f"https://api.telegram.org/bot{telegram_token}/setWebhook?url={webhook_url}"
 if api_secret:
  tg_secret = re.sub(r'[^A-Za-z0-9_-]', '', api_secret)[:256]
  if tg_secret:
   telegram_url += f"&secret_token={tg_secret}"
 
 try:
  response = requests.get(telegram_url)
  res_data = response.json()
  desc = html.escape(res_data.get('description', ''))
  if res_data.get('ok'):
   return f"""
   <div style="font-family: sans-serif; max-width: 600px; margin: 50px auto; padding: 30px; border-radius: 12px; background: #0f172a; color: #f8fafc; border: 1px solid #1e293b; box-shadow: 0 4px 20px rgba(0,0,0,0.3);">
       <h2 style="color: #38bdf8; margin-top: 0;">✓ Telegram Webhook Configured!</h2>
       <p>The webhook has been registered successfully with Telegram.</p>
       <div style="background: #1e293b; padding: 15px; border-radius: 8px; font-family: monospace; font-size: 14px; margin-bottom: 20px; word-break: break-all;">
           <strong>Webhook URL:</strong><br>{webhook_url}
       </div>
       <div style="background: #15803d; color: #dcfce7; padding: 15px; border-radius: 8px; font-size: 15px;">
           <strong>Status:</strong> {desc}
       </div>
   </div>
   """
  else:
   return f"""
   <div style="font-family: sans-serif; max-width: 600px; margin: 50px auto; padding: 30px; border-radius: 12px; background: #0f172a; color: #f8fafc; border: 1px solid #1e293b; box-shadow: 0 4px 20px rgba(0,0,0,0.3);">
       <h2 style="color: #ef4444; margin-top: 0;">✗ Webhook Registration Failed</h2>
       <p>Telegram returned an error trying to set the webhook.</p>
       <div style="background: #ef4444; color: #fee2e2; padding: 15px; border-radius: 8px; font-size: 15px;">
           <strong>Error:</strong> {desc}
       </div>
   </div>
   """
 except Exception as e:
  return jsonify({'status': 'error', 'message': f'Failed to contact Telegram: {str(e)}'}), 500

@app.route('/internal/ingest', methods=['POST'])
def internal_ingest():
  """Secure ingest endpoint for external scraper workers.
  Expects JSON: {"exam_id":"<id>", "results":[{"registration":"...","data":{...}}, ...]}
  Auth: header X-SCRAPER-SECRET must match SCRAPER_SECRET env var.
  """
  secret = os.environ.get('SCRAPER_SECRET', '')
  provided = request.headers.get('X-SCRAPER-SECRET', '')
  if not secret or provided != secret:
    return jsonify({'error': 'Unauthorized'}), 401

  payload = request.get_json(silent=True) or {}
  exam_id = payload.get('exam_id')
  results = payload.get('results') or []
  if not exam_id or not isinstance(results, list):
    return jsonify({'error': 'Invalid payload'}), 400

  saved = 0
  errors = []
  for item in results:
    reg = item.get('registration') or item.get('registration_no') or item.get('reg')
    result_data = item.get('data') or item.get('result_data') or item.get('result')
    if not reg or not result_data:
      errors.append({'registration': reg or None, 'error': 'missing data'})
      continue
    try:
      ok = result_repo.save(exam_id, reg, result_data)
      if ok:
        saved += 1
      else:
        errors.append({'registration': reg, 'error': 'db_save_failed'})
    except Exception as e:
      errors.append({'registration': reg, 'error': str(e)})

  # Clear any cached API result for this exam
  api_results_cache.pop(exam_id, None)
  # Update scrape job status based on ingest outcome so admin can see progress
  try:
    if errors:
      result_repo.update_scrape_job_status(exam_id, 'failed')
    else:
      result_repo.update_scrape_job_status(exam_id, 'completed')
  except Exception:
    pass
  return jsonify({'success': True, 'saved': saved, 'errors': errors}), 200

@app.route('/api/telegram/webhook', methods=['POST'])
def telegram_webhook():
 telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')
 if not telegram_token:
  try:
   telegram_token = ConfigService().get('SETTINGS', 'TELEGRAM_BOT_TOKEN', '')
  except Exception:
   pass

 api_secret = os.environ.get('API_SECRET', '')
 if api_secret:
  tg_secret = re.sub(r'[^A-Za-z0-9_-]', '', api_secret)[:256]
  incoming_token = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
  if tg_secret and incoming_token != tg_secret:
   return jsonify({'status': 'ignored'}), 200

 data = request.get_json(silent=True) or {}
 if not data:
  return jsonify({'status': 'ignored'}), 200

 if 'message' in data:
  message = data['message']
  chat_id = message.get('chat', {}).get('id')
  text = message.get('text', '').strip()
  if text.startswith('/check'):
   try:
    from ducmc_result_scraper import DUCMCResultScraper
    available_exams = DUCMCResultScraper.fetch_available_exams_requests("14")

    known_exam_ids_str = config_service.get('SETTINGS', 'KNOWN_EXAM_IDS', '')
    known_exam_ids = [eid.strip() for eid in known_exam_ids_str.split(',') if eid.strip()]

    new_exams = []
    with db.get_connection() as conn:
     notified_exams_set = set(row['exam_id'] for row in conn.execute("SELECT exam_id FROM notified_exams").fetchall())
     exams_set = set(row['exam_id'] for row in conn.execute("SELECT exam_id FROM exams").fetchall())

     for exam in available_exams:
      exam_id = exam['id']
      exam_name = exam['name']
      if exam_id not in known_exam_ids and exam_id not in notified_exams_set and exam_id not in exams_set:
       new_exams.append({'id': exam_id, 'name': exam_name})

    if available_exams:
     with db.get_connection() as conn:
      params_list = [(exam['id'], exam['name']) for exam in available_exams]
      conn.cursor().executemany("INSERT OR IGNORE INTO notified_exams(exam_id, exam_name) VALUES(?, ?)", params_list)

    if new_exams:
     reply_text = f"🔍 *DU CMC Check Complete!*\n\n🚀 Found *{len(new_exams)}* new exam(s):\n\n"
     inline_keyboard = []
     for exam in new_exams:
      name = standardize_exam_name(exam['name'])
      reply_text += f"• *{name}* (ID: `{exam['id']}`)\n"
      inline_keyboard.append([
       {"text": f"✅ Approve {exam['id']}", "callback_data": f"app:{exam['id']}"},
       {"text": f"❌ Ignore {exam['id']}", "callback_data": f"ign:{exam['id']}"}
      ])

     reply_markup = {"inline_keyboard": inline_keyboard}
     requests.post(f"https://api.telegram.org/bot{telegram_token}/sendMessage", json={
      "chat_id": chat_id,
      "text": reply_text,
      "parse_mode": "Markdown",
      "reply_markup": json.dumps(reply_markup)
     })
    else:
     last_exam = None
     with db.get_connection() as conn:
      row = conn.execute("SELECT exam_id, exam_name FROM notified_exams ORDER BY CAST(exam_id AS INTEGER) DESC LIMIT 1").fetchone()
      if row:
       last_exam = dict(row)
     if last_exam:
      reply_text = (
       "🔍 *DU CMC Check Complete!*\n\n"
       "✅ No new exams found.\n\n"
       "📌 *Last known exam*:\n"
       f"• *Name*: `{standardize_exam_name(last_exam['exam_name'])}`\n"
       f"• *Exam ID*: `{last_exam['exam_id']}`"
      )
     else:
      reply_text = (
       "🔍 *DU CMC Check Complete!*\n\n"
       "✅ No new exams found, and no recorded history exists yet."
      )
     requests.post(f"https://api.telegram.org/bot{telegram_token}/sendMessage", json={
      "chat_id": chat_id,
      "text": reply_text,
      "parse_mode": "Markdown"
     })
   except Exception as e:
    requests.post(f"https://api.telegram.org/bot{telegram_token}/sendMessage", json={
     "chat_id": chat_id,
     "text": f"❌ *Error occurred during check:* `{str(e)}`",
     "parse_mode": "Markdown"
    })
   return jsonify({'status': 'check_processed'}), 200
  return jsonify({'status': 'message_ignored'}), 200

 if 'callback_query' not in data:
  return jsonify({'status': 'ignored'}), 200

 cb = data['callback_query']
 cb_id = cb['id']
 cb_data = cb.get('data', '')
 message = cb.get('message', {})
 chat_id = message.get('chat', {}).get('id')
 message_id = message.get('message_id')

 requests.post(f"https://api.telegram.org/bot{telegram_token}/answerCallbackQuery", json={
  "callback_query_id": cb_id
 })

 if cb_data.startswith('ign:'):
  requests.post(f"https://api.telegram.org/bot{telegram_token}/deleteMessage", json={
   "chat_id": chat_id,
   "message_id": message_id
  })
  return jsonify({'status': 'ignored'}), 200

 if cb_data.startswith('app:'):
  exam_id = cb_data.split(':', 1)[1]
  exam_name = ""
  with db.get_connection() as conn:
   row = conn.execute("SELECT exam_name FROM notified_exams WHERE exam_id=?", (exam_id,)).fetchone()
   if row:
    exam_name = row['exam_name']

  if not exam_name:
   exam_name = f"Exam {exam_id}"

  semester = parse_semester_from_name(exam_name)
  is_retake = is_retake_improvement(exam_name)

  requests.post(f"https://api.telegram.org/bot{telegram_token}/editMessageText", json={
   "chat_id": chat_id,
   "message_id": message_id,
   "text": f"⏳ *Scraping Started...*\n\n*Exam ID*: `{exam_id}`\n*Name*: `{standardize_exam_name(exam_name)}`",
   "parse_mode": "Markdown"
  })

  try:
   created = exam_repo.create(
    exam_id,
    exam_name,
    DEFAULT_PROGRAM_ID,
    DEFAULT_SESSION_ID,
    str(semester) if semester else None,
   )

   if is_retake:
    regular_exam = exam_repo.get_by_semester_and_session(semester, DEFAULT_SESSION_ID)
    if regular_exam:
     res = result_service.process_improvement_results(exam_id, regular_exam['exam_id'])
     if res.get('success'):
      if res.get('queued'):
       msg = f"⏳ *Retake Scraping Queued!*\n\nRetake results for `{exam_id}` were queued for `{regular_exam['exam_id']}`.\nTotal students: *{res.get('total_students', 0)}*."
      else:
       msg = f"✅ *Retake Scraping Completed!*\n\nMerged retake results for `{exam_id}` into regular `{regular_exam['exam_id']}`.\nProcessed *{res.get('processed_count', 0)}* students."
     else:
      msg = f"❌ *Retake Scraping Failed!*\n\n*Exam ID*: `{exam_id}`\n*Error*: `{res.get('message', 'Unknown portal error')}`"
    else:
     msg = f"⚠️ *Scraping Warning!*\n\nRetake Exam `{exam_id}` approved, but matching regular exam for semester {semester} was not found to merge."
   else:
    res = result_service.process_exam_results(exam_id)
    if res.get('success'):
     if created:
      # Newly approved discovery exam; creation handled here.
      pass
     if res.get('queued'):
      msg = f"⏳ *Regular Scraping Queued!*\n\nQueued `{standardize_exam_name(exam_name)}` (ID `{exam_id}`).\nTotal students: *{res.get('total_students', 0)}*."
     else:
      msg = f"✅ *Regular Scraping Completed!*\n\nScraped and registered `{standardize_exam_name(exam_name)}` (ID `{exam_id}`).\nTotal processed: *{res.get('processed_count', 0)}* students."
    else:
     msg = f"❌ *Regular Scraping Failed!*\n\n*Exam ID*: `{exam_id}`\n*Error*: `{res.get('message', 'Unknown portal error')}`"
  except Exception as e:
   msg = f"❌ *Scraping Encountered an Error!*\n\n*Exam ID*: `{exam_id}`\n*Exception*: `{str(e)}`"

  requests.post(f"https://api.telegram.org/bot{telegram_token}/editMessageText", json={
   "chat_id": chat_id,
   "message_id": message_id,
   "text": msg,
   "parse_mode": "Markdown"
  })
  return jsonify({'status': 'processed', 'message': msg}), 200

 return jsonify({'status': 'ignored'}), 200

if __name__=='__main__':
 db.initialize()
 debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() in ('true', '1', 't')
 app.run(debug=debug_mode,host='0.0.0.0',port=5000)
