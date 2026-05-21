#!/usr/bin/env python3
"""Lightweight scraper worker for GitHub Actions.

Usage:
- Set `INGEST_URL` env var (e.g. https://your-app.vercel.app/internal/ingest)
- Set `SCRAPER_SECRET` env var (must match app's SCRAPER_SECRET)
- Run: python scraper_worker.py --exam-id <id>
"""
import os
import sys
import time
import random
import argparse
import requests
from bs4 import BeautifulSoup
from utils import positional_credit_fallback

# Use authoritative COURSES_DATA for accurate, consistent GPA calculation.
try:
    from ducmc_result_scraper import COURSES_DATA
except ImportError:
    COURSES_DATA = {}


def calculate_gpa(subjects: list) -> float:
    """Credit-weighted GPA using COURSES_DATA with positional fallback."""
    total_weighted = 0.0
    total_credits = 0.0
    for idx, s in enumerate(subjects):
        grade = s.get('grade', '').strip().upper()
        point_str = s.get('point', '0')
        if grade == 'F' or 'FAIL' in grade:
            point = 0.0
        else:
            try:
                point = float(point_str)
            except (ValueError, TypeError):
                point = 0.0
        code = s.get('code', '').strip()
        credit = COURSES_DATA.get(code) if code else None
        if credit is None:
            credit = positional_credit_fallback(idx)
        total_weighted += credit * point
        total_credits += credit
    return round(total_weighted / total_credits, 2) if total_credits else 0.0


def get_result(registration_no: str, program_id: str, exam_id: str, session_id: str) -> dict:
    """Fetch student result from DUCMC portal via HTTP POST."""
    import re
    reg_clean = re.sub(r'[^0-9]', '', registration_no)
    # 3-digit registrations belong to the previous session
    if session_id == '23' and len(reg_clean) == 3:
        session_id = '22'

    try:
        resp = requests.post(
            'https://ducmc.du.ac.bd/ajax/get_program_by_exam.php',
            data={'reg_no': reg_clean, 'pro_id': program_id, 'sess_id': session_id,
                  'exam_id': exam_id, 'gdata': '99'},
            headers={'User-Agent': 'du-crack-bot/1.0',
                     'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'},
            timeout=15,
        )
        if resp.status_code != 200:
            return {'error': f'HTTP {resp.status_code}'}

        soup = BeautifulSoup(resp.text, 'html.parser')

        output_div = soup.find(id='outputspass')
        if output_div and output_div.text.strip():
            return {'error': output_div.text.strip()}

        info_table = soup.find('table', class_='table table-bordered')
        if not info_table:
            return {'error': 'Result table not found'}

        student_info = {}
        for row in info_table.find_all('tr'):
            cells = row.find_all(['th', 'td'])
            if len(cells) >= 2 and cells[0].text.strip():
                student_info[cells[0].text.strip()] = cells[1].text.strip()

        subject_table = soup.find('table', width='100%', border='1')
        if not subject_table:
            return {'error': 'Subject table not found'}

        subjects = []
        for row in subject_table.find_all('tr')[1:]:
            cells = row.find_all('td')
            if len(cells) >= 5:
                grade = cells[3].text.strip()
                point_str = cells[4].text.strip()
                if grade.upper() == 'F' or 'FAIL' in grade.upper():
                    point_str = '0.0'
                subjects.append({
                    'sl': cells[0].text.strip(),
                    'code': cells[1].text.strip(),
                    'title': cells[2].text.strip(),
                    'grade': grade,
                    'point': point_str,
                    'status': 'FAIL' if grade.upper() == 'F' or 'FAIL' in grade.upper() else 'PASS',
                })

        status_div = soup.find('div', style=lambda v: v and 'text-align: center' in v and 'font-size: 25px' in v)
        status = status_div.text.strip() if status_div else 'Unknown'

        result = {'student_info': student_info, 'subjects': subjects, 'status': status}
        result['calculated_gpa'] = calculate_gpa(subjects)
        return result

    except Exception as e:
        return {'error': f'Scraping error: {e}'}


def post_results(ingest_url: str, secret: str, exam_id: str, results: list) -> None:
    """POST all results to the ingest endpoint in one call."""
    resp = requests.post(
        ingest_url,
        json={'exam_id': exam_id, 'results': results},
        headers={'Content-Type': 'application/json', 'X-SCRAPER-SECRET': secret},
        timeout=60,
    )
    if resp.status_code == 200:
        data = resp.json()
        print(f'Ingest OK — saved: {data.get("saved")}, skipped: {data.get("skipped")}, errors: {len(data.get("errors", []))}')
    else:
        print(f'Ingest FAILED — HTTP {resp.status_code}: {resp.text[:300]}')
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='DU Crack scraper worker')
    parser.add_argument('--exam-id',    dest='exam_id',    required=True)
    parser.add_argument('--input-file', dest='input_file', default='sample_registrations.txt')
    parser.add_argument('--ingest-url', dest='ingest_url', default=os.environ.get('INGEST_URL', 'http://localhost:5000/internal/ingest'))
    parser.add_argument('--program-id', dest='program_id', default=os.environ.get('PROGRAM_ID', '14'))
    parser.add_argument('--session-id', dest='session_id', default=os.environ.get('SESSION_ID', '23'))
    parser.add_argument('--min-delay',  dest='min_delay',  type=float, default=1.0)
    parser.add_argument('--max-delay',  dest='max_delay',  type=float, default=3.0)
    args = parser.parse_args()

    secret = os.environ.get('SCRAPER_SECRET')
    if not secret:
        print('ERROR: SCRAPER_SECRET is required')
        sys.exit(2)

    try:
        with open(args.input_file, encoding='utf-8') as f:
            registrations = [l.strip() for l in f if l.strip()]
    except FileNotFoundError:
        print(f'ERROR: {args.input_file} not found')
        sys.exit(1)

    if not registrations:
        print('ERROR: No registrations in input file')
        sys.exit(1)

    print(f'Scraping exam {args.exam_id} for {len(registrations)} students...')

    results = []
    errors = 0

    for idx, reg in enumerate(registrations):
        print(f'[{idx+1}/{len(registrations)}] {reg}', end=' ')
        result = None
        backoff = 1.0

        for attempt in range(1, 4):
            try:
                result = get_result(reg, args.program_id, args.exam_id, args.session_id)
                break
            except Exception as e:
                print(f'(attempt {attempt} failed: {e})', end=' ')
                if attempt < 3:
                    time.sleep(backoff)
                    backoff *= 2

        if result is None or result.get('error'):
            print(f'SKIP — {result.get("error") if result else "all attempts failed"}')
            errors += 1
        else:
            print(f'OK (GPA={result["calculated_gpa"]})')
            results.append({'registration': reg, 'data': result})

        # Polite delay between portal requests (skip after last)
        if idx < len(registrations) - 1:
            time.sleep(random.uniform(args.min_delay, args.max_delay))

    print(f'\nScraped: {len(results)} OK, {errors} skipped')
    print('Posting to ingest...')
    post_results(args.ingest_url, secret, args.exam_id, results)


if __name__ == '__main__':
    main()
