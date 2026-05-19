from flask import Flask,render_template,request,jsonify,redirect,url_for,flash,session
from datetime import timedelta
import gpa_calc
import json
import re
from functools import wraps
from models import Database,ExamRepository,ResultRepository,LoginLogRepository
from services import ResultService,ConfigService
app=Flask(__name__)
app.secret_key='rafi-sama-secret-key-2026-ducmc-scraper'
app.permanent_session_lifetime = timedelta(hours=24)
ADMIN_USERNAME,ADMIN_PASSWORD='Rafi_Sama','09032003'
db=Database()
exam_repo=ExamRepository(db)
result_repo=ResultRepository(db)
login_log_repo=LoginLogRepository(db)
result_service=ResultService(exam_repo,result_repo,ConfigService())


@app.before_request
def check_student_login():
 if request.path.startswith('/static') or request.path in ['/student_login','/login','/logout'] or request.path.startswith('/admin') or request.path.startswith('/api/'):
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
  normalized_input=re.sub(r'[^a-zA-Z0-9]','',reg_no).upper()
  match_found=False
  matched_reg=None
  try:
   with open('sample_registrations.txt','r')as f:
    for line in f:
     line_clean=line.strip()
     if not line_clean:continue
     normalized_line=re.sub(r'[^a-zA-Z0-9]','',line_clean).upper()
     if normalized_input==normalized_line:
      match_found=True
      matched_reg=line_clean
      break
  except Exception as e:
   flash(f'Error reading registration database: {str(e)}','error')
   return render_template('student_login.html')
  if match_found:
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
 enriched = []
 for exam in exams:
  exam_dict = dict(exam)
  with exam_repo.db.get_connection() as conn:
   row = conn.execute('SELECT result_data FROM results WHERE exam_id=? LIMIT 1', (exam_dict['exam_id'],)).fetchone()
   if row and row['result_data']:
    try:
     data = json.loads(row['result_data'])
     info = data.get('student_info', {})
     exam_year = next((v for k,v in info.items() if k.lower().strip() == 'exam year'), None)
     pub_date = next((v for k,v in info.items() if k.lower().strip() == 'result publication date'), None)
     exam_dict['exam_year'] = exam_year or "2024"
     exam_dict['pub_date'] = pub_date or (exam_dict['created_at'].split(' ')[0] if exam_dict.get('created_at') else "N/A")
    except Exception:
     exam_dict['exam_year'] = "2024"
     exam_dict['pub_date'] = exam_dict['created_at'].split(' ')[0] if exam_dict.get('created_at') else "N/A"
   else:
    exam_dict['exam_year'] = "2024"
    exam_dict['pub_date'] = exam_dict['created_at'].split(' ')[0] if exam_dict.get('created_at') else "N/A"
  enriched.append(exam_dict)
 return enriched


@app.route('/')
def index():return render_template('index.html',exams=get_enriched_exams(exam_repo.get_active()))


@app.route('/process_results',methods=['POST'])
def process_results():
 try:
  exam_id=request.form.get('exam_id','').strip()
  if not exam_id:return jsonify({'error':'Exam ID is required'}),400
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
 results=result_repo.get_by_exam(exam_id)
 return jsonify(result_repo.format_for_display(results))


@app.route('/admin')
@login_required
def admin():return render_template('admin.html',exams=get_enriched_exams(exam_repo.get_all()),login_logs=login_log_repo.get_all_logs())
def is_retake_improvement(exam_name:str)->bool:
 name_lower=exam_name.lower()
 return "retake/improvement" in name_lower or "retake/impovement" in name_lower


@app.route('/admin/add_exam',methods=['POST'])
@login_required
def add_exam():
 exam_id=request.form.get('exam_id','').strip()
 exam_name=request.form.get('exam_name','').strip()
 semester=request.form.get('semester','').strip()
 if semester and not exam_name:
  year_suffixes = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}
  sem_suffixes = {1: "1st", 2: "2nd"}
  sem_num = int(semester)
  year = (sem_num - 1) // 2 + 1
  sem = (sem_num - 1) % 2 + 1
  exam_name = f"{year_suffixes[year]} Year {sem_suffixes[sem]} Semester"
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
    regular_exam=exam_repo.get_by_semester_and_session(semester,request.form.get('session_id','23'))
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
  elif exam_repo.get_by_semester_and_session(semester, request.form.get('session_id', '23')):
   flash("Regular exam already exists. Use 'Retake' to merge.",'error')
  elif exam_repo.create(exam_id,exam_name,request.form.get('program_id','14'),request.form.get('session_id','23'),semester):
   res = result_service.process_exam_results(exam_id)
   if res.get('success'):
    flash(f'Exam added! Processed {res.get("processed_count", 0)} students.','success')
   else:
    flash('Exam added, but scraper portal failed. Please retry later.','warning')
  else:
   flash('Exam ID already exists','error')
 return redirect(url_for('admin'))


@app.route('/admin/delete_exam/<int:exam_db_id>',methods=['POST'])
@login_required
def delete_exam(exam_db_id):
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
 count=result_repo.clear_by_exam(exam_id)
 flash(f'Cleared {count} cached results','success')
 return redirect(url_for('admin'))
@app.route('/api/student_grades/<registration_no>')
def api_student_grades(registration_no):
 try:
  if not registration_no or not registration_no.strip():return jsonify({'success':False,'message':'Registration number is required'})
  # Sanitize: Allow only alphanumeric characters and hyphens to prevent injection and XSS
  sanitized = re.sub(r'[^a-zA-Z0-9-]', '', registration_no)
  if not sanitized:return jsonify({'success':False,'message':'Invalid registration number format'})
  reg = sanitized.replace('-', '')
  if len(reg) == 10 and reg.isdigit():
   registration_no = f"{reg[:4]}-{reg[4:7]}-{reg[7:]}"
  elif len(reg) == 3 and reg.isdigit():
   resolved_reg = None
   with db.get_connection() as conn:
    row = conn.execute("SELECT DISTINCT registration_no FROM results WHERE registration_no LIKE ?", (f"%-{reg}",)).fetchone()
    if row:
     resolved_reg = row['registration_no']
   if not resolved_reg:
    try:
     with open('sample_registrations.txt', 'r') as f:
      for line in f:
       line_clean = line.strip()
       if not line_clean:continue
       normalized_line = re.sub(r'[^a-zA-Z0-9]', '', line_clean)
       if normalized_line.endswith(reg) or line_clean == reg:
        resolved_reg = line_clean
        break
    except Exception:
     pass
   if resolved_reg:
    registration_no = resolved_reg
   else:
    return jsonify({'success':False,'message':f'No registration found matching the last 3 digits: {reg}'})
  else:
   registration_no = sanitized
  with db.get_connection()as conn:
   cursor=conn.execute('SELECT exam_id,result_data FROM results WHERE registration_no=?',(registration_no,))
   results=cursor.fetchall()
   if not results:return jsonify({'success':False,'message':'No results found for this registration number'})
   grades_data={}
   for row in results:
    try:
     result_data=json.loads(row['result_data'])if row['result_data']else{}
     subjects=result_data.get('subjects',[])
     if subjects:
      grades_data[row['exam_id']]=[]
      for subject in subjects:
       grade_value = 0.0
       # Check if subject has a valid grade point
       if subject.get('point') is not None and subject.get('point') != '':
        try:
         grade_value = float(subject.get('point'))
        except (ValueError, TypeError):
         grade_value = 0.0
       
       # If status indicates failure, force grade to 0.0
       status = str(subject.get('status', '')).lower()
       if 'fail' in status or 'f' == status:
        grade_value = 0.0
        
       grades_data[row['exam_id']].append({
        'code':subject.get('code',''),
        'title':subject.get('title',''),
        'grade':grade_value,
        'status':subject.get('status','')
        })
    except(json.JSONDecodeError,KeyError,ValueError):continue
   return jsonify({'success':True,'grades':grades_data,'registration_no':registration_no,'message':f'Found grades for {len(grades_data)} semester(s)'})
 except Exception as e:return jsonify({'success':False,'message':f'Error: {str(e)}'})
@app.route('/gpa_calc')
def gpa_calc_page():return render_template('gpa_calc.html')
@app.route('/api/gpa_courses')
def api_gpa_courses():return jsonify(gpa_calc.courses_data)
@app.route('/api/student_count')
def api_student_count():
 try:
  with open('sample_registrations.txt','r')as f:count=len([line.strip()for line in f if line.strip()])
  return jsonify({'count':count})
 except:return jsonify({'count':0})

def send_telegram_alert(exam_id: str, exam_name: str):
 import requests, os
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
 from models import standardize_exam_name
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
def cron_check_exams():
 import random, requests
 force = request.args.get('force', '').lower() == 'true'
 # 30% chance to execute check-exams to provide randomized checks (unless forced)
 if not force and random.random() > 0.30:
  return jsonify({'status': 'skipped', 'message': 'Skipped by probabilistic jitter threshold'}), 200
 try:
  from ducmc_result_scraper import DUCMCResultScraper
  available_exams = DUCMCResultScraper.fetch_available_exams_requests("14")
  if not available_exams:
   return jsonify({'status': 'no_data', 'message': 'No available exams fetched from portal'}), 200
  new_count = 0
  for exam in available_exams:
   exam_id = exam['id']
   exam_name = exam['name']
   is_new = False
   with db.get_connection() as conn:
    row_exam = conn.execute("SELECT 1 FROM exams WHERE exam_id=?", (exam_id,)).fetchone()
    row_notified = conn.execute("SELECT 1 FROM notified_exams WHERE exam_id=?", (exam_id,)).fetchone()
    if not row_exam and not row_notified:
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
def telegram_setup():
 import os, requests
 telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')
 if not telegram_token:
  try:
   telegram_token = ConfigService().get('SETTINGS', 'TELEGRAM_BOT_TOKEN', '')
  except Exception:
   pass
 if not telegram_token:
  return jsonify({'status': 'error', 'message': 'TELEGRAM_BOT_TOKEN not found!'}), 400

 host = request.headers.get('Host', '')
 scheme = 'https' if 'vercel.app' in host or request.is_secure else 'http'
 webhook_url = f"{scheme}://{host}/api/telegram/webhook"
 telegram_url = f"https://api.telegram.org/bot{telegram_token}/setWebhook?url={webhook_url}"
 
 try:
  response = requests.get(telegram_url)
  res_data = response.json()
  if res_data.get('ok'):
   return f"""
   <div style="font-family: sans-serif; max-width: 600px; margin: 50px auto; padding: 30px; border-radius: 12px; background: #0f172a; color: #f8fafc; border: 1px solid #1e293b; box-shadow: 0 4px 20px rgba(0,0,0,0.3);">
       <h2 style="color: #38bdf8; margin-top: 0;">✓ Telegram Webhook Configured!</h2>
       <p>The webhook has been registered successfully with Telegram.</p>
       <div style="background: #1e293b; padding: 15px; border-radius: 8px; font-family: monospace; font-size: 14px; margin-bottom: 20px; word-break: break-all;">
           <strong>Webhook URL:</strong><br>{webhook_url}
       </div>
       <div style="background: #15803d; color: #dcfce7; padding: 15px; border-radius: 8px; font-size: 15px;">
           <strong>Status:</strong> {res_data.get('description')}
       </div>
   </div>
   """
  else:
   return f"""
   <div style="font-family: sans-serif; max-width: 600px; margin: 50px auto; padding: 30px; border-radius: 12px; background: #0f172a; color: #f8fafc; border: 1px solid #1e293b; box-shadow: 0 4px 20px rgba(0,0,0,0.3);">
       <h2 style="color: #ef4444; margin-top: 0;">✗ Webhook Registration Failed</h2>
       <p>Telegram returned an error trying to set the webhook.</p>
       <div style="background: #ef4444; color: #fee2e2; padding: 15px; border-radius: 8px; font-size: 15px;">
           <strong>Error:</strong> {res_data.get('description')}
       </div>
   </div>
   """
 except Exception as e:
  return jsonify({'status': 'error', 'message': f'Failed to contact Telegram: {str(e)}'}), 500

@app.route('/api/telegram/webhook', methods=['POST'])
def telegram_webhook():
 import os, requests
 telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')
 if not telegram_token:
  try:
   telegram_token = ConfigService().get('SETTINGS', 'TELEGRAM_BOT_TOKEN', '')
  except Exception:
   pass
 data = request.get_json()
 if not data:
  return jsonify({'status': 'ignored'}), 200
 
 # 1. Handle command /check text message
 if 'message' in data:
  message = data['message']
  chat_id = message.get('chat', {}).get('id')
  text = message.get('text', '').strip()
  if text.startswith('/check'):
   try:
    from ducmc_result_scraper import DUCMCResultScraper
    available_exams = DUCMCResultScraper.fetch_available_exams_requests("14")

    # Step 1: Identify truly new exam IDs (not in exams table AND not in notified_exams)
    new_exams = []
    for exam in available_exams:
     exam_id = exam['id']
     exam_name = exam['name']
     with db.get_connection() as conn:
      row_exam = conn.execute("SELECT 1 FROM exams WHERE exam_id=?", (exam_id,)).fetchone()
      row_notified = conn.execute("SELECT 1 FROM notified_exams WHERE exam_id=?", (exam_id,)).fetchone()
      if not row_exam and not row_notified:
       new_exams.append({'id': exam_id, 'name': exam_name})

    # Step 2: Mark ALL fetched exams as seen in notified_exams (prevent future re-notification)
    for exam in available_exams:
     with db.get_connection() as conn:
      conn.execute("INSERT OR IGNORE INTO notified_exams(exam_id, exam_name) VALUES(?, ?)", (exam['id'], exam['name']))

    # Step 3: Send alerts only for truly new exams
    for exam in new_exams:
     send_telegram_alert(exam['id'], exam['name'])

    from models import standardize_exam_name
    if new_exams:
     reply_text = f"🔍 *DU CMC Check Complete!*\n\n🚀 Found *{len(new_exams)}* new exam(s) and dispatched approval alerts!"
    else:
     last_exam = None
     with db.get_connection() as conn:
      row = conn.execute("SELECT exam_id, exam_name FROM notified_exams ORDER BY notified_at DESC LIMIT 1").fetchone()
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

 # 2. Handle callback queries (Approve / Ignore button click events)
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
  from models import standardize_exam_name
  name_lower = exam_name.lower()
  year_match = re.search(r'([1-4])(?:st|nd|rd|th)?\s+year', name_lower)
  sem_match = re.search(r'([1-2])(?:st|nd|rd|th)?\s+semester', name_lower)
  semester = None
  if year_match and sem_match:
   semester = (int(year_match.group(1)) - 1) * 2 + int(sem_match.group(1))
  is_retake = "retake" in name_lower or "improvement" in name_lower or "retake/improvement" in name_lower
  requests.post(f"https://api.telegram.org/bot{telegram_token}/editMessageText", json={
   "chat_id": chat_id,
   "message_id": message_id,
   "text": f"⏳ *Scraping Started...*\n\n*Exam ID*: `{exam_id}`\n*Name*: `{standardize_exam_name(exam_name)}`",
   "parse_mode": "Markdown"
  })
  try:
   if is_retake:
    regular_exam = exam_repo.get_by_semester_and_session(semester, "23")
    if regular_exam:
     res = result_service.process_improvement_results(exam_id, regular_exam['exam_id'])
     if res.get('success'):
      msg = f"✅ *Retake Scraping Completed!*\n\nMerged retake results for `{exam_id}` into regular `{regular_exam['exam_id']}`.\nProcessed *{res.get('processed_count', 0)}* students."
     else:
      msg = f"❌ *Retake Scraping Failed!*\n\n*Exam ID*: `{exam_id}`\n*Error*: `{res.get('message', 'Unknown portal error')}`"
    else:
     msg = f"⚠️ *Scraping Warning!*\n\nRetake Exam `{exam_id}` approved, but matching regular exam for semester {semester} was not found to merge."
   else:
    res = result_service.process_exam_results(exam_id)
    if res.get('success'):
     exam_repo.create(exam_id, exam_name, "14", "23", str(semester))
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
 app.run(debug=True,host='0.0.0.0',port=5000)
