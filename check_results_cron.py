#!/usr/bin/env python3
"""
DU Crack - Automated Results Publication Checker Cron Job
Checks the DU CMC website every 6 hours for new CSE exam result publications,
registers new exams dynamically, and processes student grade reports in the background.
"""

import sys
import os
import re
import datetime
import traceback

# Add the current directory to python path to ensure local imports work
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ducmc_result_scraper import DUCMCResultScraper
from models import Database, ExamRepository, ResultRepository
from services import ResultService, ConfigService, RegistrationService

# Logging configuration
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cron_log.log')

def log(message: str):
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"[{timestamp}] {message}"
    print(log_line)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_line + '\n')
    except Exception as e:
        print(f"Failed to write to log file: {e}")

def parse_semester_from_name(exam_name: str) -> int:
    """
    Intelligently infer the semester number (1-8) from the exam's printed text
    """
    name_lower = exam_name.lower()
    
    # 1st Year
    if "1st year" in name_lower or "1st-year" in name_lower:
        if "1st semester" in name_lower or "1st-semester" in name_lower:
            return 1
        if "2nd semester" in name_lower or "2nd-semester" in name_lower:
            return 2
            
    # 2nd Year
    elif "2nd year" in name_lower or "2nd-year" in name_lower:
        if "1st semester" in name_lower or "1st-semester" in name_lower:
            return 3
        if "2nd semester" in name_lower or "2nd-semester" in name_lower:
            return 4
            
    # 3rd Year
    elif "3rd year" in name_lower or "3rd-year" in name_lower:
        if "1st semester" in name_lower or "1st-semester" in name_lower:
            return 5
        if "2nd semester" in name_lower or "2nd-semester" in name_lower:
            return 6
            
    # 4th Year
    elif "4th year" in name_lower or "4th-year" in name_lower:
        if "1st semester" in name_lower or "1st-semester" in name_lower:
            return 7
        if "2nd semester" in name_lower or "2nd-semester" in name_lower:
            return 8
            
    # Default fallback
    return None

def is_retake_improvement(exam_name: str) -> bool:
    name_lower = exam_name.lower()
    return "retake/improvement" in name_lower or "retake/impovement" in name_lower

def run_checker():
    log("="*60)
    log("DU CMC AUTOMATED RESULT PUBLICATION CHECKER STARTED")
    log("="*60)
    
    # Initialize repositories and services
    db = Database()
    db.initialize()
    
    exam_repo = ExamRepository(db)
    result_repo = ResultRepository(db)
    config_service = ConfigService()
    result_service = ResultService(exam_repo, result_repo, config_service)
    
    # Get active session IDs from existing exams in DB to check multiple sessions
    sessions_to_check = {'23'} # Default: 2022-2023 session
    try:
        exams = exam_repo.get_all()
        for exam in exams:
            sess_id = exam.get('session_id')
            if sess_id:
                sessions_to_check.add(sess_id)
    except Exception as e:
        log(f"Warning: Failed to fetch existing sessions from DB: {e}")
        
    log(f"Configured to check sessions: {sorted(list(sessions_to_check))}")
    
    PROGRAM_ID = "14" # B.Sc. in CSE
    new_exams_found = 0
    scraped_results_count = 0
    
    # Launch Headless Chrome browser
    try:
        log("Launching headless browser...")
        with DUCMCResultScraper(headless=True) as scraper:
            for session_id in sessions_to_check:
                log(f"Checking results for Session ID: {session_id}...")
                available_exams = scraper.fetch_available_exams(program_id=PROGRAM_ID, session_id=session_id)
                
                if not available_exams:
                    log(f"No exams found or error loading list for session {session_id}.")
                    continue
                    
                log(f"Found {len(available_exams)} total exams on DU website for session {session_id}.")
                
                for exam in available_exams:
                    exam_id = exam['id']
                    exam_name = exam['name']
                    
                    if is_retake_improvement(exam_name):
                        if result_repo.is_improvement_processed(exam_id):
                            continue
                        log(f"🔔 NEW RETAKE/IMPROVEMENT RESULT DETECTED!")
                        log(f"   Exam ID:   {exam_id}")
                        log(f"   Exam Name: {exam_name}")
                        semester = parse_semester_from_name(exam_name)
                        log(f"   Inferred Semester: {semester if semester else 'Unknown (None)'}")
                        regular_exam = exam_repo.get_by_semester_and_session(semester, session_id)
                        if not regular_exam:
                            log(f"   ⚠️ Warning: Corresponding regular exam for Semester {semester} and Session {session_id} not found in DB. Skipping for now.")
                            continue
                        log(f"   Matching regular exam found: {regular_exam['exam_name']}")
                        log(f"   Starting automatic background batch scraping and merge...")
                        crawl_result = result_service.process_improvement_results(exam_id, regular_exam['exam_id'])
                        if crawl_result.get('success'):
                            processed = crawl_result.get('processed_count', 0)
                            total = crawl_result.get('total_students', 0)
                            scraped_results_count += processed
                            new_exams_found += 1
                            log(f"   ✅ Batch crawling finished! Scraped and merged {processed}/{total} student results.")
                        else:
                            log(f"   ❌ Batch crawling error: {crawl_result.get('message', 'Unknown error')}")
                        continue

                    # Check if this exam is already registered in our DB
                    existing_exam = exam_repo.get_by_exam_id(exam_id)
                    if existing_exam:
                        # Already tracked, skip
                        continue
                        
                    # We have a NEW exam publication!
                    new_exams_found += 1
                    log(f"🔔 NEW RESULT PUBLICATION DETECTED!")
                    log(f"   Exam ID:   {exam_id}")
                    log(f"   Exam Name: {exam_name}")
                    
                    # Infer semester number
                    semester = parse_semester_from_name(exam_name)
                    log(f"   Inferred Semester: {semester if semester else 'Unknown (None)'}")
                    
                    # 1. Register the new exam in our SQLite database
                    log(f"   Registering new exam in database...")
                    success = exam_repo.create(
                        exam_id=exam_id,
                        exam_name=exam_name,
                        program_id=PROGRAM_ID,
                        session_id=session_id,
                        semester=str(semester) if semester else None
                    )
                    
                    if not success:
                        log(f"   ❌ Error: Failed to register exam {exam_id} in database.")
                        continue
                        
                    log(f"   ✅ Exam successfully registered!")
                    
                    # 2. Trigger automatic background crawl for all registered students
                    log(f"   Starting automatic background batch scraping for student list...")
                    crawl_result = result_service.process_exam_results(exam_id)
                    
                    if crawl_result.get('success'):
                        processed = crawl_result.get('processed_count', 0)
                        total = crawl_result.get('total_students', 0)
                        scraped_results_count += processed
                        log(f"   ✅ Batch crawling finished! Scraped {processed}/{total} student results.")
                    else:
                        log(f"   ❌ Batch crawling error: {crawl_result.get('message', 'Unknown error')}")
                        
        log("Headless browser closed successfully.")
        
    except Exception as e:
        log(f"❌ CRITICAL SCRAPER RUNTIME ERROR: {e}")
        log(traceback.format_exc())
        
    log("="*60)
    log(f"CHECK SUMMARY: Found {new_exams_found} new exam(s). Crawled {scraped_results_count} student result(s).")
    log("DU CMC AUTOMATED RESULT PUBLICATION CHECKER FINISHED")
    log("="*60)

if __name__ == "__main__":
    run_checker()
