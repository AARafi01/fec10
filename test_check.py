import os
from app import db, config_service, standardize_exam_name
db.initialize()
from ducmc_result_scraper import DUCMCResultScraper

def test_logic():
    available_exams = DUCMCResultScraper.fetch_available_exams_requests("14")
    known_exam_ids_str = config_service.get('SETTINGS', 'KNOWN_EXAM_IDS', '')
    known_exam_ids = [eid.strip() for eid in known_exam_ids_str.split(',') if eid.strip()]
    print('Known IDs:', known_exam_ids)
    new_exams = []
    with db.get_connection() as conn:
        notified_exams_set = set(row['exam_id'] for row in conn.execute("SELECT exam_id FROM notified_exams").fetchall())
        exams_set = set(row['exam_id'] for row in conn.execute("SELECT exam_id FROM exams").fetchall())
        for exam in available_exams:
            exam_id = exam['id']
            exam_name = exam['name']
            if exam_id not in known_exam_ids and exam_id not in notified_exams_set and exam_id not in exams_set:
                new_exams.append({'id': exam_id, 'name': exam_name})
    print('New Exams:', new_exams)
    if available_exams:
        with db.get_connection() as conn:
            params_list = [(exam['id'], exam['name']) for exam in available_exams]
            conn.cursor().executemany("INSERT OR IGNORE INTO notified_exams(exam_id, exam_name) VALUES(?, ?)", params_list)
    if new_exams:
        print("Sending new exams")
    else:
        last_exam = None
        with db.get_connection() as conn:
            row = conn.execute("SELECT exam_id, exam_name FROM notified_exams ORDER BY CAST(exam_id AS INTEGER) DESC LIMIT 1").fetchone()
            if row:
                last_exam = dict(row)
        print("Sending last exam:", last_exam)

test_logic()
