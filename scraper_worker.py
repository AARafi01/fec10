#!/usr/bin/env python3
"""Lightweight scraper worker for GitHub Actions or other schedulers.

Usage: set environment variables or pass args. The simplest flow:
- Set `INGEST_URL` (default http://localhost:5000/internal/ingest)
- Set `SCRAPER_SECRET` (secret header value) as repo secret in Actions
- Provide `EXAM_ID` and `INPUT_FILE` (default: sample_registrations.txt)
"""
import os
import sys
import time
import random
import json
import argparse
import requests
from bs4 import BeautifulSoup
from utils import positional_credit_fallback


def calculate_gpa_local(subjects):
    # Simple weighted GPA using positional credit fallback for robustness
    total_weighted = 0.0
    total_credits = 0.0
    for idx, s in enumerate(subjects):
        try:
            point = float(s.get('point', 0) or 0)
        except Exception:
            point = 0.0
        credit = positional_credit_fallback(idx)
        total_weighted += credit * point
        total_credits += credit
    if total_credits == 0:
        return 0.0
    return round(total_weighted / total_credits, 2)


def get_result_requests(registration_no: str, program_id: str = "14", exam_id: str = "1563", session_id: str = "23") -> dict:
    """HTTP-only result fetcher using requests + BeautifulSoup (no Selenium).
    Mirrors the behavior of the original scraper static method but avoids browser usage.
    """
    import re
    reg_clean = re.sub(r'[^0-9]', '', registration_no)
    if session_id == "23" and len(reg_clean) == 3:
        session_id = "22"

    url = "https://ducmc.du.ac.bd/ajax/get_program_by_exam.php"
    payload = {
        'reg_no': reg_clean,
        'pro_id': program_id,
        'sess_id': session_id,
        'exam_id': exam_id,
        'gdata': '99'
    }
    headers = {
        'User-Agent': 'du-crack-bot/1.0 (+https://example.com/contact)',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
    }
    try:
        resp = requests.post(url, data=payload, headers=headers, timeout=15)
        if resp.status_code != 200:
            return {'error': f'HTTP Error {resp.status_code}'}
        soup = BeautifulSoup(resp.text, 'html.parser')
        output_div = soup.find(id="outputspass")
        if output_div and output_div.text.strip():
            return {'error': output_div.text.strip()}

        result_data = {'student_info': {}, 'subjects': [], 'status': 'Unknown'}
        info_table = soup.find('table', class_='table table-bordered')
        if not info_table:
            return {'error': 'Student result details table not found on page'}
        for row in info_table.find_all('tr'):
            cells = row.find_all(['th', 'td'])
            if len(cells) >= 2:
                key = cells[0].text.strip()
                value = cells[1].text.strip()
                if key:
                    result_data['student_info'][key] = value

        subject_table = soup.find('table', width='100%', border='1')
        if not subject_table:
            return {'error': 'Grades subject table not found on page'}
        rows = subject_table.find_all('tr')[1:]
        for row in rows:
            cells = row.find_all('td')
            if len(cells) >= 5:
                grade = cells[3].text.strip()
                point_str = cells[4].text.strip()
                if grade.upper() == 'F' or point_str.upper() == 'F' or 'FAIL' in grade.upper():
                    point_str = '0.0'
                subject = {
                    'sl': cells[0].text.strip(),
                    'code': cells[1].text.strip(),
                    'title': cells[2].text.strip(),
                    'grade': grade,
                    'point': point_str,
                    'status': 'FAIL' if grade.upper() == 'F' or 'FAIL' in grade.upper() else 'PASS'
                }
                result_data['subjects'].append(subject)

        status_div = soup.find('div', style=lambda v: v and 'text-align: center' in v and 'font-size: 25px' in v)
        if status_div:
            result_data['status'] = status_div.text.strip()
        return result_data
    except Exception as e:
        return {'error': f'Requests scraping error: {str(e)}'}


def post_results(ingest_url, secret, exam_id, payload):
    headers = {'Content-Type': 'application/json', 'X-SCRAPER-SECRET': secret}
    try:
        res = requests.post(ingest_url, json={'exam_id': exam_id, 'results': payload}, headers=headers, timeout=30)
        return res.status_code, res.text
    except Exception as e:
        return None, str(e)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exam-id', dest='exam_id', help='Exam ID to scrape', required=True)
    parser.add_argument('--input-file', dest='input_file', default='sample_registrations.txt')
    parser.add_argument('--ingest-url', dest='ingest_url', default=os.environ.get('INGEST_URL', 'http://localhost:5000/internal/ingest'))
    parser.add_argument('--program-id', dest='program_id', default=os.environ.get('PROGRAM_ID', '14'))
    parser.add_argument('--session-id', dest='session_id', default=os.environ.get('SESSION_ID', '23'))
    parser.add_argument('--min-delay', dest='min_delay', type=float, default=1.0)
    parser.add_argument('--max-delay', dest='max_delay', type=float, default=3.0)
    args = parser.parse_args()

    secret = os.environ.get('SCRAPER_SECRET')
    if not secret:
        print('SCRAPER_SECRET environment variable is required')
        sys.exit(2)

    try:
        with open(args.input_file, 'r', encoding='utf-8') as f:
            registrations = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print('Input file not found:', args.input_file)
        sys.exit(1)

    session = requests.Session()
    results_payload = []

    for idx, reg in enumerate(registrations):
        print(f'Processing {reg} ({idx+1}/{len(registrations)})')
        attempts = 0
        max_attempts = 3
        backoff = 1.0
        while attempts < max_attempts:
            attempts += 1
            try:
                res = get_result_requests(reg, program_id=args.program_id, exam_id=args.exam_id, session_id=args.session_id)
                if isinstance(res, dict) and res.get('error'):
                    print(f'Error for {reg}: {res.get("error")}')
                else:
                    if isinstance(res, dict) and res.get('subjects'):
                        try:
                            res['calculated_gpa'] = calculate_gpa_local(res.get('subjects', []))
                        except Exception:
                            res['calculated_gpa'] = 0.0
                results_payload.append({'registration': reg, 'data': res})
                break
            except Exception as e:
                print(f'Attempt {attempts} failed for {reg}: {e}')
                time.sleep(backoff + random.uniform(0, backoff * 0.5))
                backoff *= 2
        # polite delay between requests
        if idx < len(registrations) - 1:
            delay = random.uniform(args.min_delay, args.max_delay)
            print(f'Waiting {delay:.2f}s before next request...')
            time.sleep(delay)

    print('Posting results to ingest URL...')
    code, text = post_results(args.ingest_url, secret, args.exam_id, results_payload)
    print('Ingest response:', code)
    print(text)


if __name__ == '__main__':
    main()
