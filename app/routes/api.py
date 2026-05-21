import os
import json
import re
import html
import requests
from functools import wraps
from flask import Blueprint, request, jsonify

from app.extensions import db, config_service, exam_repo, result_repo, result_service, api_results_cache
from app.utils.app_helpers import format_registration_no, load_nonempty_lines, resolve_registration_from_suffix, parse_subject_grades
from app.utils.utils import standardize_exam_name, is_retake_improvement, parse_semester_from_name
from app.utils import gpa_calc

api_bp = Blueprint('api', __name__)

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        secret = os.environ.get('API_SECRET', '')
        if secret:
            provided = request.args.get('key', '') or request.headers.get('X-API-Key', '')
            if not provided:
                cron_secret = os.environ.get('CRON_SECRET', '')
                auth_header = request.headers.get('Authorization', '')
                if cron_secret and auth_header == f'Bearer {cron_secret}':
                    provided = secret
            if provided != secret:
                return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function

@api_bp.route('/process_results', methods=['POST'])
def process_results():
    try:
        exam_id = request.form.get('exam_id', '').strip()
        if not exam_id:
            return jsonify({'error': 'Exam ID is required'}), 400
        api_results_cache.pop(exam_id, None)
        return jsonify(result_service.process_exam_results(exam_id))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/api/results/<exam_id>')
def api_results(exam_id):
    if exam_id in api_results_cache:
        return jsonify(api_results_cache[exam_id])
    results = result_repo.get_by_exam(exam_id)
    formatted = result_repo.format_for_display(results)
    api_results_cache[exam_id] = formatted
    return jsonify(formatted)

@api_bp.route('/api/student_grades/<registration_no>')
def api_student_grades(registration_no):
    try:
        if not registration_no or not registration_no.strip():
            return jsonify({'success': False, 'message': 'Registration number is required'})

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

@api_bp.route('/api/gpa_courses')
def api_gpa_courses():
    return jsonify(gpa_calc.courses_data)

@api_bp.route('/api/student_count')
def api_student_count():
    try:
        count = len(load_nonempty_lines())
        return jsonify({'count': count})
    except:
        return jsonify({'count': 0})

@api_bp.route('/api/health')
@require_api_key
def api_health():
    import time as _time
    checks = {}
    t_start = _time.time()

    try:
        with db.get_connection() as conn:
            exam_count = conn.execute('SELECT COUNT(*) FROM exams').fetchone()[0]
            result_count = conn.execute('SELECT COUNT(*) FROM results').fetchone()[0]
            recent_jobs = [dict(r) for r in conn.execute(
                'SELECT exam_id, status, updated_at FROM scrape_jobs ORDER BY updated_at DESC LIMIT 5'
            ).fetchall()]
        checks['database'] = {'status': 'ok', 'exams': exam_count, 'results': result_count, 'recent_jobs': recent_jobs}
    except Exception as e:
        checks['database'] = {'status': 'error', 'error': str(e)}

    gh_repo  = os.environ.get('GITHUB_REPOSITORY')  or config_service.get('SETTINGS', 'GITHUB_REPOSITORY', '')
    gh_token = os.environ.get('GITHUB_WORKFLOW_TOKEN') or config_service.get('SETTINGS', 'GITHUB_WORKFLOW_TOKEN', '')
    workflow_file = os.environ.get('GITHUB_WORKFLOW_FILE', 'scrape.yml')
    if not gh_repo or not gh_token:
        missing = []
        if not gh_repo:  missing.append('GITHUB_REPOSITORY')
        if not gh_token: missing.append('GITHUB_WORKFLOW_TOKEN')
        checks['github_actions'] = {'status': 'not_configured', 'missing': missing}
    else:
        try:
            resp = requests.get(
                f'https://api.github.com/repos/{gh_repo}/actions/workflows/{workflow_file}',
                headers={'Authorization': f'Bearer {gh_token}', 'Accept': 'application/vnd.github+json',
                         'X-GitHub-Api-Version': '2022-11-28'},
                timeout=8,
            )
            if resp.status_code == 200:
                wf = resp.json()
                checks['github_actions'] = {
                    'status': 'ok',
                    'repository': gh_repo,
                    'workflow': wf.get('name'),
                    'workflow_state': wf.get('state'),
                }
            elif resp.status_code == 401:
                checks['github_actions'] = {'status': 'auth_failed', 'repository': gh_repo,
                                              'hint': 'GITHUB_WORKFLOW_TOKEN is invalid or expired'}
            elif resp.status_code == 404:
                checks['github_actions'] = {'status': 'not_found', 'repository': gh_repo,
                                              'hint': f'{workflow_file} not found in repo — check GITHUB_WORKFLOW_FILE'}
            else:
                checks['github_actions'] = {'status': 'error', 'http': resp.status_code, 'repository': gh_repo}
        except Exception as e:
            checks['github_actions'] = {'status': 'unreachable', 'error': str(e)}

    tg_token = os.environ.get('TELEGRAM_BOT_TOKEN') or config_service.get('SETTINGS', 'TELEGRAM_BOT_TOKEN', '')
    tg_chat  = os.environ.get('TELEGRAM_CHAT_ID')   or config_service.get('SETTINGS', 'TELEGRAM_CHAT_ID', '')
    if not tg_token or not tg_chat:
        missing = []
        if not tg_token: missing.append('TELEGRAM_BOT_TOKEN')
        if not tg_chat:  missing.append('TELEGRAM_CHAT_ID')
        checks['telegram'] = {'status': 'not_configured', 'missing': missing}
    else:
        try:
            resp = requests.get(f'https://api.telegram.org/bot{tg_token}/getMe', timeout=6)
            data = resp.json()
            if data.get('ok'):
                checks['telegram'] = {'status': 'ok', 'bot': data['result'].get('username')}
            else:
                checks['telegram'] = {'status': 'auth_failed', 'hint': data.get('description', '')}
        except Exception as e:
            checks['telegram'] = {'status': 'unreachable', 'error': str(e)}

    try:
        resp = requests.get('https://ducmc.du.ac.bd/result.php', timeout=8)
        checks['ducmc_portal'] = {'status': 'ok' if resp.status_code == 200 else 'degraded', 'http': resp.status_code}
    except Exception as e:
        checks['ducmc_portal'] = {'status': 'unreachable', 'error': str(e)}

    checks['secrets'] = {
        'SCRAPER_SECRET': 'set' if os.environ.get('SCRAPER_SECRET') else 'missing',
        'CRON_SECRET':    'set' if os.environ.get('CRON_SECRET')    else 'missing',
        'API_SECRET':     'set' if os.environ.get('API_SECRET')     else 'missing',
    }

    checks['environment'] = {
        'vercel':   os.environ.get('VERCEL') == '1',
        'db_mode':  'turso' if db.is_turso else ('postgres' if db.is_pg else 'sqlite'),
        'ingest_url_hint': 'Set INGEST_URL in GitHub Actions secrets pointing to this app' ,
    }

    critical = {
        'database':       checks['database']['status'] == 'ok',
        'github_actions': checks['github_actions']['status'] == 'ok',
        'ducmc_portal':   checks['ducmc_portal']['status'] in ('ok', 'degraded'),
    }
    all_ok = all(critical.values())
    elapsed = round(_time.time() - t_start, 2)

    return jsonify({
        'status': 'ok' if all_ok else 'degraded',
        'elapsed_s': elapsed,
        'critical': critical,
        'checks': checks,
    }), 200 if all_ok else 503

def send_telegram_alert(exam_id: str, exam_name: str):
    telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN') or config_service.get('SETTINGS', 'TELEGRAM_BOT_TOKEN', '')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID') or config_service.get('SETTINGS', 'TELEGRAM_CHAT_ID', '')
    if not telegram_token or not chat_id:
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
    except Exception:
        return False

@api_bp.route('/api/cron/check-exams', methods=['GET', 'POST'])
@require_api_key
def cron_check_exams():
    try:
        from app.scraper.ducmc_result_scraper import DUCMCResultScraper
        available_exams = DUCMCResultScraper.fetch_available_exams_requests("14")
        if not available_exams:
            return jsonify({'status': 'no_data', 'message': 'No available exams fetched from portal'}), 200
            
        with db.get_connection() as conn:
            notified_exams_set = set(row['exam_id'] for row in conn.execute("SELECT exam_id FROM notified_exams").fetchall())
            exams_set = set(row['exam_id'] for row in conn.execute("SELECT exam_id FROM exams").fetchall())
            
        new_exams = [
            exam for exam in available_exams
            if exam['id'] not in exams_set and exam['id'] not in notified_exams_set
        ]
        
        if new_exams:
            with db.get_connection() as conn:
                conn.cursor().executemany(
                    "INSERT OR IGNORE INTO notified_exams(exam_id, exam_name) VALUES(?, ?)",
                    [(e['id'], e['name']) for e in new_exams]
                )
            for exam in new_exams:
                send_telegram_alert(exam['id'], exam['name'])
                
        return jsonify({'status': 'success', 'message': f'Checked {len(available_exams)} exams. Notified {len(new_exams)} new exams.'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@api_bp.route('/api/telegram/setup')
@require_api_key
def telegram_setup():
    telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN') or config_service.get('SETTINGS', 'TELEGRAM_BOT_TOKEN', '')
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

@api_bp.route('/internal/ingest', methods=['POST'])
def internal_ingest():
    secret = os.environ.get('SCRAPER_SECRET', '')
    provided = request.headers.get('X-SCRAPER-SECRET', '')
    if not secret or provided != secret:
        return jsonify({'error': 'Unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    exam_id = payload.get('exam_id')
    results = payload.get('results') or []
    if not exam_id or not isinstance(results, list):
        return jsonify({'error': 'Invalid payload'}), 400

    exam = exam_repo.get_by_exam_id(exam_id)
    is_retake = False
    regular_exam_id = None
    if exam and is_retake_improvement(exam['exam_name']):
        is_retake = True
        regular_exam = exam_repo.get_by_semester_and_session(exam['semester'], exam['session_id'])
        if regular_exam:
            regular_exam_id = regular_exam['exam_id']

    saved = 0
    skipped = 0
    errors = []
    for item in results:
        reg = item.get('registration') or item.get('registration_no') or item.get('reg')
        result_data = item.get('data') or item.get('result_data') or item.get('result')
        if not reg or not result_data:
            errors.append({'registration': reg or None, 'error': 'missing data'})
            continue
        if isinstance(result_data, dict) and result_data.get('error'):
            skipped += 1
            continue
        try:
            if is_retake and regular_exam_id:
                ok = result_service.merge_and_save_improvement(regular_exam_id, reg, result_data)
            else:
                ok = result_repo.save(exam_id, reg, result_data)
            if ok:
                saved += 1
            else:
                errors.append({'registration': reg, 'error': 'db_save_failed'})
        except Exception as e:
            errors.append({'registration': reg, 'error': str(e)})

    api_results_cache.pop(exam_id, None)
    if is_retake and regular_exam_id:
        api_results_cache.pop(regular_exam_id, None)
        try:
            result_repo.mark_improvement_processed(exam_id)
        except:
            pass

    try:
        status = 'completed_with_errors' if errors else 'completed'
        result_repo.update_scrape_job_status(exam_id, status)
    except Exception:
        pass
    return jsonify({'success': True, 'saved': saved, 'skipped': skipped, 'errors': errors}), 200

@api_bp.route('/api/telegram/webhook', methods=['POST'])
def telegram_webhook():
    telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN') or config_service.get('SETTINGS', 'TELEGRAM_BOT_TOKEN', '')
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
                from app.scraper.ducmc_result_scraper import DUCMCResultScraper
                available_exams = DUCMCResultScraper.fetch_available_exams_requests("14")

                known_exam_ids_str = config_service.get('SETTINGS', 'KNOWN_EXAM_IDS', '')
                known_exam_ids = [eid.strip() for eid in known_exam_ids_str.split(',') if eid.strip()]

                new_exams = []
                with db.get_connection() as conn:
                    notified_exams_set = set(row['exam_id'] for row in conn.execute("SELECT exam_id FROM notified_exams").fetchall())
                    exams_set = set(row['exam_id'] for row in conn.execute("SELECT exam_id FROM exams").fetchall())

                    for exam in available_exams:
                        exam_id = exam['id']
                        if exam_id not in known_exam_ids and exam_id not in notified_exams_set and exam_id not in exams_set:
                            new_exams.append({'id': exam_id, 'name': exam['name']})

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
        return jsonify({'status': 'message_processed'}), 200

    if 'callback_query' not in data:
        return jsonify({'status': 'ignored'}), 200

    cb = data['callback_query']
    cb_id = cb['id']
    cb_data = cb.get('data', '')
    message = cb.get('message', {})
    chat_id = message.get('chat', {}).get('id')
    message_id = message.get('message_id')

    requests.post(f"https://api.telegram.org/bot{telegram_token}/answerCallbackQuery", json={"callback_query_id": cb_id})

    if cb_data.startswith('ign:'):
        requests.post(f"https://api.telegram.org/bot{telegram_token}/deleteMessage", json={"chat_id": chat_id, "message_id": message_id})
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

        requests.post(f"https://api.telegram.org/bot{telegram_token}/editMessageText", json={
            "chat_id": chat_id,
            "message_id": message_id,
            "text": f"⏳ *Scraping Started...*\n\n*Exam ID*: `{exam_id}`\n*Name*: `{standardize_exam_name(exam_name)}`",
            "parse_mode": "Markdown"
        })
        
        # NOTE: process_exam_results is handled via admin.py but we can call it here
        # (assuming background queue or github actions)
        result_repo.update_scrape_job_status(exam_id, 'failed')
        res = result_service.process_exam_results(exam_id)
        
        status_text = f"✅ *Scrape Queued/Started*\n\n*Exam ID*: `{exam_id}`\n*Name*: `{standardize_exam_name(exam_name)}`\n"
        if not res.get('success'):
            status_text = f"❌ *Scrape Failed*\n\n*Exam ID*: `{exam_id}`\n*Error*: `{res.get('message')}`"
            
        requests.post(f"https://api.telegram.org/bot{telegram_token}/sendMessage", json={
            "chat_id": chat_id,
            "text": status_text,
            "parse_mode": "Markdown"
        })

    return jsonify({'status': 'callback_processed'}), 200
