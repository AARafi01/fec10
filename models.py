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
    if "AUTOINCREMENT" in sql:
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

class TursoRow:
    def __init__(self, fields, values):
        self._fields = fields
        self._values = values
        self._field_map = {f: i for i, f in enumerate(fields)}
        
    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        if key in self._field_map:
            return self._values[self._field_map[key]]
        raise KeyError(key)
        
    def get(self, key, default=None):
        if key in self._field_map:
            return self._values[self._field_map[key]]
        return default
        
    def __iter__(self):
        return iter(self._values)
        
    def __len__(self):
        return len(self._values)
        
    def _asdict(self):
        return dict(zip(self._fields, self._values))
        
    def keys(self):
        return self._fields

class TursoCursorWrapper:
    def __init__(self, rs):
        self.rs = rs
        self._idx = 0
        
    @property
    def rowcount(self):
        return self.rs.rows_affected if self.rs else 0
        
    def _to_row(self, row):
        if row is None:
            return None
        return TursoRow(row._fields, row._values)

    def fetchone(self):
        if self.rs and self._idx < len(self.rs.rows):
            row = self.rs.rows[self._idx]
            self._idx += 1
            return self._to_row(row)
        return None

    def fetchall(self):
        if not self.rs:
            return []
        rows = [self._to_row(row) for row in self.rs.rows[self._idx:]]
        self._idx = len(self.rs.rows)
        return rows

    def __iter__(self):
        return self

    def __next__(self):
        row = self.fetchone()
        if row is None:
            raise StopIteration
        return row

class TursoConnectionWrapper:
    def __init__(self, client):
        self.client = client
        self.is_pg = False
        
    def execute(self, sql: str, params=None):
        if params is None:
            params = []
        import libsql_client
        if params:
            stmt = libsql_client.Statement(sql, params)
            rs = self.client.execute(stmt)
        else:
            rs = self.client.execute(sql)
        return TursoCursorWrapper(rs)
        
    def executemany(self, sql: str, params_list):
        import libsql_client
        stmts = [libsql_client.Statement(sql, params) for params in params_list]
        if stmts:
            self.client.batch(stmts)
        return self
        
    def cursor(self):
        return self
        
    def executescript(self, script_sql: str):
        import libsql_client
        statements = []
        for query in script_sql.split(';'):
            q = query.strip()
            if q:
                statements.append(libsql_client.Statement(q))
        if statements:
            self.client.batch(statements)

class Database:
    def __init__(self, db_path: str = 'database.db'):
        if os.environ.get('VERCEL') == '1':
            self.db_path = '/tmp/database.db'
            if not os.path.exists('/tmp/database.db'):
                try:
                    import shutil
                    if os.path.exists('database.db'):
                        shutil.copy('database.db', '/tmp/database.db')
                    else:
                        with open('/tmp/database.db', 'w') as f:
                            pass

                except Exception:
                    pass
        else:
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
                
        self.turso_token = os.environ.get('TURSO_AUTH_TOKEN', '')
        if not self.turso_token:
            try:
                import configparser
                config = configparser.ConfigParser()
                config.read('config.ini')
                self.turso_token = config.get('SETTINGS', 'TURSO_AUTH_TOKEN', fallback='').strip()
            except Exception:
                pass
                
        self.is_turso = bool(self.db_url and (self.db_url.startswith('libsql://') or self.db_url.startswith('turso://') or (self.turso_token and self.db_url.startswith('https://'))))
        
        self.is_pg = bool(not self.is_turso and psycopg2 and self.db_url and (self.db_url.startswith('postgres://') or self.db_url.startswith('postgresql://')))
        
    @contextmanager
    def get_connection(self):
        conn = None
        client = None
        try:
            if self.is_turso:
                import libsql_client
                url = self.db_url
                if url.startswith('libsql://'):
                    url = url.replace('libsql://', 'https://', 1)
                elif url.startswith('turso://'):
                    url = url.replace('turso://', 'https://', 1)
                client = libsql_client.create_client_sync(url, auth_token=self.turso_token)
                yield TursoConnectionWrapper(client)
                return
            elif self.is_pg:
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
            if client:
                client.close()

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
                    conn.execute('CREATE INDEX IF NOT EXISTS idx_registration_no ON results(registration_no)')
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
                    conn.execute('CREATE INDEX IF NOT EXISTS idx_registration_no ON results(registration_no)')
                else:
                    conn.execute('CREATE INDEX IF NOT EXISTS idx_exam_id ON results(exam_id)')
                    conn.execute('CREATE INDEX IF NOT EXISTS idx_gpa ON results(gpa DESC)')
                    conn.execute('CREATE INDEX IF NOT EXISTS idx_registration_no ON results(registration_no)')

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
from utils import standardize_exam_name

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
  
  if not results:
   return formatted
   
  reg_numbers = list(set(r.get('registration_no') for r in results if r.get('registration_no')))
  cgpa_map = {}
  if reg_numbers:
   placeholders = ','.join(['?'] * len(reg_numbers))
   query = f'SELECT registration_no, gpa FROM results WHERE registration_no IN ({placeholders}) AND gpa IS NOT NULL AND gpa > 0'
   try:
    with self.db.get_connection() as conn:
     cursor = conn.execute(query, reg_numbers)
     for row in cursor.fetchall():
      reg = row['registration_no']
      gpa_val = row['gpa']
      if reg not in cgpa_map:
       cgpa_map[reg] = []
      cgpa_map[reg].append(gpa_val)
   except Exception:
    pass
    
  for row in results:
   try:
    data=json.loads(row.get('result_data','{}'))if row.get('result_data')else{}
    reg_no=row.get('registration_no','')
    
    cgpa = 0.0
    if reg_no in cgpa_map and cgpa_map[reg_no]:
     gpas = cgpa_map[reg_no]
     cgpa = round(sum(gpas)/len(gpas), 2)
     
    class_roll=row.get('class_roll') or data.get('student_info',{}).get('Class Roll') or data.get('student_info',{}).get('Class Roll No') or 'N/A'
    if isinstance(class_roll, str) and class_roll.strip().isdigit():
     class_roll = str(int(class_roll.strip()))
    formatted.append({'registration':row.get('registration_no','N/A'),'name':row.get('student_name','N/A'),'college':row.get('college_name','N/A'),'gpa':row.get('gpa',0),'cgpa':cgpa,'exam_roll':row.get('exam_roll','N/A'),'class_roll':class_roll,'status':row.get('status','Unknown'),'result_data':row.get('result_data','{}'),'subjects':data.get('subjects',[])})
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
