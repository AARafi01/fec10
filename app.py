from flask import Flask,render_template,request,jsonify,redirect,url_for,flash,session
import gpa_calc
import json
from functools import wraps
from models import Database,ExamRepository,ResultRepository
from services import ResultService,ConfigService
app=Flask(__name__)
app.secret_key='rafi-sama-secret-key-2026-ducmc-scraper'
ADMIN_USERNAME,ADMIN_PASSWORD='Rafi_Sama','09032003'
db=Database()
exam_repo=ExamRepository(db)
result_repo=ResultRepository(db)
result_service=ResultService(exam_repo,result_repo,ConfigService())


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
   session['logged_in']=True
   session['username']=ADMIN_USERNAME
   return redirect(url_for('admin'))
  flash('Wait a min... Who are you ?!!','error')
 return render_template('login.html')


@app.route('/logout')
def logout():
 session.clear()
 return redirect(url_for('index'))
@app.route('/')
def index():return render_template('index.html',exams=exam_repo.get_active())


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
 return render_template('results.html',exam=exam,results=results)
@app.route('/api/results/<exam_id>')
def api_results(exam_id):
 results=result_repo.get_by_exam(exam_id)
 return jsonify(result_repo.format_for_display(results))


@app.route('/admin')
@login_required
def admin():return render_template('admin.html',exams=exam_repo.get_all())
@app.route('/admin/add_exam',methods=['POST'])
@login_required
def add_exam():
 exam_id,exam_name=request.form.get('exam_id','').strip(),request.form.get('exam_name','').strip()
 semester=request.form.get('semester','').strip()
 if not exam_id or not exam_name or not semester:flash('Exam ID, Name, and Semester are required','error')
 elif exam_repo.create(exam_id,exam_name,request.form.get('program_id','14'),request.form.get('session_id','23'),semester):
  flash(f'Exam added successfully for Semester {semester}','success')
 else:flash('Exam ID already exists','error')
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
  with db.get_connection()as conn:
   cursor=conn.execute('SELECT exam_id,result_data FROM results WHERE registration_no=?',(registration_no.strip(),))
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
   return jsonify({'success':True,'grades':grades_data,'message':f'Found grades for {len(grades_data)} semester(s)'})
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
if __name__=='__main__':
 db.initialize()
 app.run(debug=True,host='0.0.0.0',port=5000)
