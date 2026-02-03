#!/usr/bin/env python3
"""Database Models and Repository Pattern"""
import sqlite3
import json
from typing import List, Dict, Optional
from contextlib import contextmanager


class Database:
    """Database connection manager with context manager support"""
    def __init__(self, db_path: str = 'results.db'):
        self.db_path = db_path
    
    @contextmanager
    def get_connection(self):
        """Safe database connection with auto-commit/rollback"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            yield conn
            conn.commit()
        except Exception:
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()
    
    def initialize(self):
        """Initialize database schema"""
        with self.get_connection() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS exams (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exam_id VARCHAR(50) NOT NULL UNIQUE,
                    exam_name TEXT NOT NULL,
                    program_id VARCHAR(50) DEFAULT '14',
                    session_id VARCHAR(50) DEFAULT '23',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exam_id VARCHAR(50) NOT NULL,
                    registration_no VARCHAR(50) NOT NULL,
                    student_name TEXT,
                    college_name TEXT,
                    program TEXT,
                    session TEXT,
                    exam_roll VARCHAR(50),
                    class_roll VARCHAR(50),
                    status TEXT,
                    cgpa REAL,
                    result_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(exam_id, registration_no)
                );
                CREATE INDEX IF NOT EXISTS idx_exam_id ON results(exam_id);
                CREATE INDEX IF NOT EXISTS idx_cgpa ON results(cgpa DESC);
            ''')


class ExamRepository:
    """Repository for exam operations"""
    def __init__(self, db: Database):
        self.db = db
    
    def get_all(self) -> List[Dict]:
        with self.db.get_connection() as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM exams ORDER BY created_at DESC')]
    
    def get_active(self) -> List[Dict]:
        with self.db.get_connection() as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM exams WHERE is_active = 1 ORDER BY created_at DESC')]
    
    def get_by_exam_id(self, exam_id: str) -> Optional[Dict]:
        if not exam_id or not exam_id.strip():
            return None
        with self.db.get_connection() as conn:
            row = conn.execute('SELECT * FROM exams WHERE exam_id = ?', (exam_id.strip(),)).fetchone()
            return dict(row) if row else None
    
    def create(self, exam_id: str, exam_name: str, program_id: str = '14', session_id: str = '23') -> bool:
        if not exam_id or not exam_name or not exam_id.strip() or not exam_name.strip():
            return False
        try:
            with self.db.get_connection() as conn:
                conn.execute('INSERT INTO exams (exam_id, exam_name, program_id, session_id) VALUES (?, ?, ?, ?)',
                           (exam_id.strip(), exam_name.strip(), program_id.strip(), session_id.strip()))
            return True
        except (sqlite3.IntegrityError, AttributeError):
            return False
    
    def delete(self, exam_db_id: int) -> bool:
        try:
            with self.db.get_connection() as conn:
                conn.execute('DELETE FROM exams WHERE id = ?', (exam_db_id,))
            return True
        except Exception:
            return False
    
    def toggle_active(self, exam_db_id: int) -> bool:
        try:
            with self.db.get_connection() as conn:
                row = conn.execute('SELECT is_active FROM exams WHERE id = ?', (exam_db_id,)).fetchone()
                if row:
                    conn.execute('UPDATE exams SET is_active = ? WHERE id = ?', (0 if row['is_active'] else 1, exam_db_id))
                    return True
            return False
        except Exception:
            return False


class ResultRepository:
    """Repository for result operations"""
    def __init__(self, db: Database):
        self.db = db
    
    def get_by_exam(self, exam_id: str) -> List[Dict]:
        if not exam_id or not exam_id.strip():
            return []
        with self.db.get_connection() as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM results WHERE exam_id = ? ORDER BY cgpa DESC NULLS LAST', (exam_id.strip(),))]
    
    def save(self, exam_id: str, reg_no: str, result_data: Dict) -> bool:
        if not exam_id or not reg_no or not result_data:
            return False
        try:
            info = result_data.get('student_info', {})
            with self.db.get_connection() as conn:
                conn.execute('''INSERT OR REPLACE INTO results 
                    (exam_id, registration_no, student_name, college_name, program, session, exam_roll, class_roll, status, cgpa, result_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (exam_id, reg_no, info.get("Student's Name", 'N/A'), info.get('College Name', 'N/A'),
                     info.get('Program', 'N/A'), info.get('Session', 'N/A'), info.get('Exam Roll', 'N/A'),
                     info.get('Class Roll', 'N/A'), result_data.get('status', 'Unknown'),
                     result_data.get('calculated_cgpa'), json.dumps(result_data)))
            return True
        except Exception:
            return False
    
    def clear_by_exam(self, exam_id: str) -> int:
        if not exam_id or not exam_id.strip():
            return 0
        try:
            with self.db.get_connection() as conn:
                return conn.execute('DELETE FROM results WHERE exam_id = ?', (exam_id.strip(),)).rowcount
        except Exception:
            return 0
    
    def format_for_display(self, results: List[Dict]) -> List[Dict]:
        formatted = []
        for row in results:
            try:
                data = json.loads(row.get('result_data', '{}')) if row.get('result_data') else {}
                formatted.append({
                    'registration': row.get('registration_no', 'N/A'),
                    'name': row.get('student_name', 'N/A'),
                    'cgpa': row.get('cgpa', 0),
                    'status': row.get('status', 'Unknown'),
                    'subjects': data.get('subjects', [])
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return formatted
