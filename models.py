import sqlite3,json,os,re
from typing import List,Dict,Optional
from contextlib import contextmanager

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

def rewrite_sql(sql: str, is_pg: bool) -> str:
    if not is_pg:
        return sql
    
    # Replace ? placeholder with %s for psycopg2
    sql = sql.replace('?', '%s')
    
    # Create table AUTOINCREMENT translation
    if "CREATE TABLE IF NOT EXISTS exams" in sql:
        sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    elif "CREATE TABLE IF NOT EXISTS login_logs" in sql:
        sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    elif "CREATE TABLE IF NOT EXISTS results" in sql:
        sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    elif "CREATE TABLE IF NOT EXISTS notified_exams" in sql:
        sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        
    # INSERT OR IGNORE translation
    if "INSERT OR IGNORE" in sql:
        sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
        if "processed_improvements" in sql:
            sql += " ON CONFLICT (exam_id) DO NOTHING"
        elif "notified_exams" in sql:
            sql += " ON CONFLICT (exam_id) DO NOTHING"
        else:
            sql += " ON CONFLICT DO NOTHING"
            
    # INSERT OR REPLACE translation
    if "INSERT OR REPLACE INTO results" in sql:
        sql = """
        INSERT INTO results(exam_id,registration_no,student_name,college_name,program,session,exam_roll,class_roll,status,gpa,result_data) 
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(exam_id, registration_no) 
        DO UPDATE SET 
            student_name = EXCLUDED.student_name,
            college_name = EXCLUDED.college_name,
            program = EXCLUDED.program,
            session = EXCLUDED.session,
            exam_roll = EXCLUDED.exam_roll,
            class_roll = EXCLUDED.class_roll,
            status = EXCLUDED.status,
            gpa = EXCLUDED.gpa,
            result_data = EXCLUDED.result_data
        """
        
    return sql

class DatabaseCursorWrapper:
    def __init__(self, cursor, is_pg: bool):
        self.cursor = cursor
        self.is_pg = is_pg
        
    def execute(self, sql: str, params=None):
        rewritten_sql = rewrite_sql(sql, self.is_pg)
        if params is None:
            self.cursor.execute(rewritten_sql)
        else:
            self.cursor.execute(rewritten_sql, params)
        return self
        
    def executemany(self, sql: str, params_list):
        rewritten_sql = rewrite_sql(sql, self.is_pg)
        self.cursor.executemany(rewritten_sql, params_list)
        return self
        
    def fetchone(self):
        row = self.cursor.fetchone()
        if row is None:
            return None
        return dict(row) if self.is_pg else row
        
    def fetchall(self):
        rows = self.cursor.fetchall()
        return [dict(row) for row in rows] if self.is_pg else rows
        
    @property
    def rowcount(self):
        return self.cursor.rowcount

    def __iter__(self):
        return self

    def __next__(self):
        row = next(self.cursor)
        return dict(row) if self.is_pg else row

class DatabaseConnectionWrapper:
    def __init__(self, conn, is_pg: bool):
        self.conn = conn
        self.is_pg = is_pg
        
    def execute(self, sql: str, params=None):
        cursor = self.conn.cursor()
        rewritten_sql = rewrite_sql(sql, self.is_pg)
        if params is None:
            cursor.execute(rewritten_sql)
        else:
            cursor.execute(rewritten_sql, params)
        return DatabaseCursorWrapper(cursor, self.is_pg)
        
    def executescript(self, script_sql: str):
        if self.is_pg:
            cursor = self.conn.cursor()
            for query in script_sql.split(';'):
                query_clean = query.strip()
                if query_clean:
                    cursor.execute(rewrite_sql(query_clean, self.is_pg))
        else:
            self.conn.executescript(script_sql)
            
    def cursor(self):
        return DatabaseCursorWrapper(self.conn.cursor(), self.is_pg)
        
    def commit(self):
        self.conn.commit()
        
    def rollback(self):
        self.conn.rollback()
        
    def close(self):
        self.conn.close()

class Database:
    def __init__(self, db_path: str = 'database.db'):
        self.db_path = db_path
        self.db_url = os.environ.get('DATABASE_URL')
        if not self.db_url:
            try:
                import configparser
                config = configparser.ConfigParser()
                config.read('config.ini')
                self.db_url = config.get('SETTINGS', 'DATABASE_URL', fallback='').strip()
            except Exception:
                pass
        self.is_pg = bool(psycopg2 and self.db_url and (self.db_url.startswith('postgres://') or self.db_url.startswith('postgresql://')))
        
    @contextmanager
    def get_connection(self):
        conn = None
        try:
            if self.is_pg:
                url = self.db_url
                if url.startswith('postgres://'):
                    url = url.replace('postgres://', 'postgresql://', 1)
                conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.DictCursor)
            else:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
            yield DatabaseConnectionWrapper(conn, self.is_pg)
            conn.commit()
        except Exception:
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def initialize(self):
        with self.get_connection() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS exams(id INTEGER PRIMARY KEY AUTOINCREMENT,exam_id VARCHAR(50)NOT NULL UNIQUE,exam_name TEXT NOT NULL,program_id VARCHAR(50)DEFAULT'14',session_id VARCHAR(50)DEFAULT'23',semester INTEGER,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,is_active BOOLEAN DEFAULT 1)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS login_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,registration_no VARCHAR(50)NOT NULL,login_time TEXT NOT NULL)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS processed_improvements(exam_id VARCHAR(50)PRIMARY KEY,processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS notified_exams(exam_id VARCHAR(50)PRIMARY KEY,exam_name TEXT,notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            
            if self.is_pg:
                conn.execute('''CREATE TABLE IF NOT EXISTS results(id SERIAL PRIMARY KEY,exam_id VARCHAR(50)NOT NULL,registration_no VARCHAR(50)NOT NULL,student_name TEXT,college_name TEXT,program TEXT,session TEXT,exam_roll VARCHAR(50),class_roll VARCHAR(50),status TEXT,gpa REAL,result_data TEXT,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(exam_id,registration_no))''')
                try:
                    conn.execute('CREATE INDEX IF NOT EXISTS idx_exam_id ON results(exam_id)')
                    conn.execute('CREATE INDEX IF NOT EXISTS idx_gpa ON results(gpa DESC)')
                except Exception:
                    pass
            else:
                cursor = conn.execute("PRAGMA table_info(results)")
                columns = [col[1] for col in cursor.fetchall()]
                if 'cgpa' in columns and 'gpa' not in columns:
                    conn.executescript('''ALTER TABLE results ADD COLUMN gpa REAL;CREATE INDEX IF NOT EXISTS idx_gpa ON results(gpa DESC);''')
                    self._recalculate_gpas_from_result_data(conn)
                elif 'gpa' not in columns:
                    conn.execute('''CREATE TABLE IF NOT EXISTS results(id INTEGER PRIMARY KEY AUTOINCREMENT,exam_id VARCHAR(50)NOT NULL,registration_no VARCHAR(50)NOT NULL,student_name TEXT,college_name TEXT,program TEXT,session TEXT,exam_roll VARCHAR(50),class_roll VARCHAR(50),status TEXT,gpa REAL,result_data TEXT,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(exam_id,registration_no))''')
                    conn.execute('CREATE INDEX IF NOT EXISTS idx_exam_id ON results(exam_id)')
                    conn.execute('CREATE INDEX IF NOT EXISTS idx_gpa ON results(gpa DESC)')
                else:
                    conn.execute('CREATE INDEX IF NOT EXISTS idx_exam_id ON results(exam_id)')
                    conn.execute('CREATE INDEX IF NOT EXISTS idx_gpa ON results(gpa DESC)')

    def _recalculate_gpas_from_result_data(self, conn):
        try:
            import json
            cursor = conn.execute('SELECT id, result_data FROM results WHERE result_data IS NOT NULL')
            for row_id, result_data_json in cursor.fetchall():
                try:
                    result_data = json.loads(result_data_json)
                    calculated_gpa = result_data.get('calculated_gpa', 0.0)
                    if calculated_gpa and calculated_gpa > 0:
                        conn.execute('UPDATE results SET gpa=? WHERE id=?', (calculated_gpa, row_id))
                except (json.JSONDecodeError, Exception):
                    conn.execute('UPDATE results SET gpa=? WHERE id=?', (0.0, row_id))
        except Exception as e:
            pass

    def fix_gpa_values(self):
        with self.get_connection() as conn:
            self._recalculate_gpas_from_result_data(conn)
def standardize_exam_name(exam_name: str) -> str:
    name_lower = exam_name.lower()
    year_match = re.search(r'([1-4])(?:st|nd|rd|th)?\s+year', name_lower)
    sem_match = re.search(r'([1-2])(?:st|nd|rd|th)?\s+semester', name_lower)
    if year_match and sem_match:
        year = int(year_match.group(1))
        sem = int(sem_match.group(1))
        
        year_suffixes = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}
        sem_suffixes = {1: "1st", 2: "2nd"}
        
        is_retake = "retake" in name_lower or "improvement" in name_lower or "retake/improvement" in name_lower
        
        standardized_base = f"{year_suffixes[year]} Year {sem_suffixes[sem]} Semester"
        if is_retake:
            return f"{standardized_base} - Retake/Improvement"
        return standardized_base
    return exam_name

class ExamRepository:
 def __init__(self,db:Database):self.db=db
 def get_all(self)->List[Dict]:
  with self.db.get_connection()as conn:return[dict(row)for row in conn.execute('SELECT*FROM exams ORDER BY created_at DESC')]
 def get_active(self)->List[Dict]:
  with self.db.get_connection()as conn:return[dict(row)for row in conn.execute('SELECT*FROM exams WHERE is_active=1 ORDER BY created_at DESC')]
 def get_by_exam_id(self,exam_id:str)->Optional[Dict]:
  if not exam_id or not exam_id.strip():return None
  with self.db.get_connection()as conn:
   row=conn.execute('SELECT*FROM exams WHERE exam_id=?',(exam_id.strip(),)).fetchone()
   return dict(row)if row else None
 def get_by_semester_and_session(self,semester:int,session_id:str)->Optional[Dict]:
  if semester is None or not session_id:return None
  with self.db.get_connection()as conn:
   row=conn.execute('SELECT*FROM exams WHERE semester=? AND session_id=?',(int(semester),session_id.strip())).fetchone()
   return dict(row)if row else None
 def create(self,exam_id:str,exam_name:str,program_id:str='14',session_id:str='23',semester:str=None)->bool:
  if not exam_id or not exam_name or not exam_id.strip()or not exam_name.strip():return False
  
  if not semester:
      name_lower = exam_name.lower()
      year_match = re.search(r'([1-4])(?:st|nd|rd|th)?\s+year', name_lower)
      sem_match = re.search(r'([1-2])(?:st|nd|rd|th)?\s+semester', name_lower)
      if year_match and sem_match:
          semester = str((int(year_match.group(1)) - 1) * 2 + int(sem_match.group(1)))
          
  std_name = standardize_exam_name(exam_name)
  try:
   with self.db.get_connection()as conn:
    conn.execute('INSERT INTO exams(exam_id,exam_name,program_id,session_id,semester)VALUES(?,?,?,?,?)',(exam_id.strip(),std_name,program_id.strip(),session_id.strip(),int(semester)if semester else None))
   return True
  except Exception:return False
 def delete(self,exam_db_id:int)->bool:
  try:
   with self.db.get_connection()as conn:
    row = conn.execute('SELECT exam_id FROM exams WHERE id=?', (exam_db_id,)).fetchone()
    if row:
     exam_id = row['exam_id']
     conn.execute('DELETE FROM exams WHERE id=?', (exam_db_id,))
     conn.execute('DELETE FROM results WHERE exam_id=?', (exam_id,))
     conn.execute('DELETE FROM processed_improvements WHERE exam_id=?', (exam_id,))
   return True
  except Exception:return False
 def toggle_active(self,exam_db_id:int)->bool:
  try:
   with self.db.get_connection()as conn:
    row=conn.execute('SELECT is_active FROM exams WHERE id=?',(exam_db_id,)).fetchone()
    if row:
     conn.execute('UPDATE exams SET is_active=? WHERE id=?',(0 if row['is_active']else 1,exam_db_id))
     return True
   return False
  except Exception:return False
class ResultRepository:
 def __init__(self,db:Database):self.db=db
 def get_by_exam(self,exam_id:str)->List[Dict]:
  if not exam_id or not exam_id.strip():return[]
  with self.db.get_connection()as conn:return[dict(row)for row in conn.execute('SELECT*FROM results WHERE exam_id=? ORDER BY gpa DESC NULLS LAST',(exam_id.strip(),))]
 def save(self,exam_id:str,reg_no:str,result_data:Dict)->bool:
  if not exam_id or not reg_no or not result_data:return False
  try:
   info=result_data.get('student_info',{})
   with self.db.get_connection()as conn:
    conn.execute('''INSERT OR REPLACE INTO results(exam_id,registration_no,student_name,college_name,program,session,exam_roll,class_roll,status,gpa,result_data)VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(exam_id,reg_no,info.get("Student's Name",'N/A'),info.get('College Name','N/A'),info.get('Program','N/A'),info.get('Session','N/A'),info.get('Exam Roll','N/A'),info.get('Class Roll','N/A'),result_data.get('status','Unknown'),result_data.get('calculated_gpa'),json.dumps(result_data)))
   return True
  except Exception:return False
 def clear_by_exam(self,exam_id:str)->int:
  if not exam_id or not exam_id.strip():return 0
  try:
   with self.db.get_connection()as conn:return conn.execute('DELETE FROM results WHERE exam_id=?',(exam_id.strip(),)).rowcount
  except Exception:return 0
 def format_for_display(self,results:List[Dict])->List[Dict]:
  formatted=[]
  for row in results:
   try:
    data=json.loads(row.get('result_data','{}'))if row.get('result_data')else{}
    reg_no=row.get('registration_no','')
    cgpa=self._calculate_cgpa_for_student(reg_no)
    class_roll=row.get('class_roll') or data.get('student_info',{}).get('Class Roll') or data.get('student_info',{}).get('Class Roll No') or 'N/A'
    if isinstance(class_roll, str) and class_roll.strip().isdigit():
     class_roll = str(int(class_roll.strip()))
    formatted.append({'registration':row.get('registration_no','N/A'),'name':row.get('student_name','N/A'),'gpa':row.get('gpa',0),'cgpa':cgpa,'exam_roll':row.get('exam_roll','N/A'),'class_roll':class_roll,'subjects':data.get('subjects',[])})
   except(json.JSONDecodeError,KeyError):continue
  return formatted
 def _calculate_cgpa_for_student(self,registration_no:str)->float:
  if not registration_no:return 0.0
  try:
   with self.db.get_connection()as conn:
    cursor=conn.execute('SELECT gpa FROM results WHERE registration_no=? AND gpa IS NOT NULL AND gpa > 0 ORDER BY exam_id',(registration_no,))
    gpas=[row[0]for row in cursor.fetchall()if row[0]is not None and row[0]>0]
    if len(gpas)>1:return round(sum(gpas)/len(gpas),2)
    elif len(gpas)==1:return round(gpas[0],2)
    return 0.0
  except Exception:return 0.0
 def is_improvement_processed(self,exam_id:str)->bool:
  if not exam_id or not exam_id.strip():return False
  try:
   with self.db.get_connection()as conn:
    row=conn.execute('SELECT 1 FROM processed_improvements WHERE exam_id=?',(exam_id.strip(),)).fetchone()
    return bool(row)
  except Exception:return False
 def mark_improvement_processed(self,exam_id:str)->bool:
  if not exam_id or not exam_id.strip():return False
  try:
   with self.db.get_connection()as conn:
    conn.execute('INSERT OR IGNORE INTO processed_improvements(exam_id)VALUES(?)',(exam_id.strip(),))
   return True
  except Exception:return False


class LoginLogRepository:
 def __init__(self,db:Database):self.db=db
 def log_login(self,registration_no:str,login_time:str)->bool:
  if not registration_no or not login_time:return False
  try:
   with self.db.get_connection()as conn:
    conn.execute('INSERT INTO login_logs(registration_no,login_time)VALUES(?,?)',(registration_no.strip(),login_time))
   return True
  except Exception:return False
 def get_all_logs(self)->List[Dict]:
  try:
   with self.db.get_connection()as conn:
    return[dict(row)for row in conn.execute('SELECT*FROM login_logs ORDER BY id DESC')]
  except Exception:return[]
