# Agent Skills — DU Crack

This file provides actionable skills and patterns for an AI agent working on this project.
Read `CLAUDE.md` first for the full project overview.

---

## Skill: Add a New API Endpoint

**Pattern:** Add to `app.py`. Follow existing conventions.

```python
@app.route('/api/my_endpoint/<param>')
def my_endpoint(param):
    try:
        # validation
        if not param or not param.strip():
            return jsonify({'success': False, 'message': 'param is required'}), 400
        # logic using repos
        with db.get_connection() as conn:
            row = conn.execute('SELECT * FROM exams WHERE exam_id=?', (param,)).fetchone()
        return jsonify({'success': True, 'data': dict(row) if row else None})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
```

- Use `@login_required` decorator for admin-only routes.
- Use `@require_api_key` for machine-to-machine / cron routes.
- Always return JSON with a consistent `success` boolean key.
- Clear `api_results_cache[exam_id]` when mutating result data.

---

## Skill: Add a New Database Table

**Where:** `models.py` → `Database.initialize()` method.

```python
# In Database.initialize():
conn.execute('''CREATE TABLE IF NOT EXISTS my_table(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id VARCHAR(50) NOT NULL,
    data TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')
```

**Rules:**
- Always use `CREATE TABLE IF NOT EXISTS`.
- Write SQL in SQLite syntax — `rewrite_sql()` will auto-translate for PostgreSQL.
- Use `?` as placeholder (not `%s`) — translation is automatic.
- For `INSERT OR IGNORE`, the SQL rewriter handles `ON CONFLICT DO NOTHING` for PG.
- Add a corresponding Repository class following the pattern of `ExamRepository`.

---

## Skill: Add a Repository Method

**Pattern:** Look at `ExamRepository` and `ResultRepository` in `models.py`.

```python
class MyRepository:
    def __init__(self, db: Database):
        self.db = db

    def get_by_id(self, id: int) -> Optional[Dict]:
        if not id:
            return None
        with self.db.get_connection() as conn:
            row = conn.execute('SELECT * FROM my_table WHERE id=?', (id,)).fetchone()
            return dict(row) if row else None

    def create(self, exam_id: str, data: str) -> bool:
        if not exam_id or not data:
            return False
        try:
            with self.db.get_connection() as conn:
                conn.execute(
                    'INSERT INTO my_table(exam_id, data) VALUES(?, ?)',
                    (exam_id.strip(), data)
                )
            return True
        except Exception:
            return False
```

**Rules:**
- Always validate inputs before hitting the DB.
- Wrap writes in `try/except` and return `False` on failure.
- Use `with self.db.get_connection() as conn:` — the context manager auto-commits.
- Return `dict(row)` to convert `sqlite3.Row` to a plain dict.

---

## Skill: Modify the GPA Calculation

**Where:** `COURSES_DATA` dict in `ducmc_result_scraper.py` AND `services.py` (`_calculate_gpa()`).

To add a new course:
```python
# In COURSES_DATA dict:
"CSE-4301": 3.0,  # New 4th Year course
```

To change the fallback logic for unknown courses, modify `positional_credit_fallback()` in `utils.py`.

> **Note:** `scraper_worker.py` has its own `calculate_gpa_local()` that uses `positional_credit_fallback` directly (not `COURSES_DATA`). If you add courses to `COURSES_DATA`, also consider updating the worker's GPA logic for consistency.

---

## Skill: Add a New Jinja2 Template

1. Create `templates/my_page.html` extending `base.html`:
```html
{% extends 'base.html' %}

{% block title %}My Page — DU Crack{% endblock %}

{% block content %}
<div class="main-container">
    <div class="card">
        <div class="card-header text-center">
            <h1><i class="fas fa-star"></i> My Page</h1>
        </div>
        <div class="card-body p-4">
            <!-- content -->
        </div>
    </div>
</div>
{% endblock %}

{% block extra_js %}
<script>
    // page-specific JS
</script>
{% endblock %}
```

2. Add a route in `app.py`:
```python
@app.route('/my_page')
def my_page():
    return render_template('my_page.html', data=some_data)
```

3. Import and use component macros if needed:
```html
{% import 'components/badges.html' as badges %}
{% import 'components/cards.html' as cards %}
{% import 'components/loader.html' as loader %}
```

---

## Skill: Add a New Config Key

**Where:** `config.ini` (under `[SETTINGS]`) and read via `ConfigService`.

```ini
[SETTINGS]
MY_NEW_KEY = some_value
```

Read it in Python:
```python
# At module level or in a function:
my_value = os.environ.get('MY_NEW_KEY') or config_service.get('SETTINGS', 'MY_NEW_KEY', 'default_value')
```

**Rule:** Always prefer environment variable over `config.ini` — env var takes priority.

---

## Skill: Add a Telegram Bot Command

**Where:** `app.py` → `telegram_webhook()` → inside the `if 'message' in data:` block.

```python
if text.startswith('/mycommand'):
    # your logic
    reply_text = "Response to /mycommand"
    requests.post(f"https://api.telegram.org/bot{telegram_token}/sendMessage", json={
        "chat_id": chat_id,
        "text": reply_text,
        "parse_mode": "Markdown"
    })
    return jsonify({'status': 'mycommand_processed'}), 200
```

For inline keyboard buttons, add a new `callback_data` prefix:
```python
# In callback_query handling:
if cb_data.startswith('mypfx:'):
    exam_id = cb_data.split(':', 1)[1]
    # handle the button press
```

---

## Skill: Trigger a GitHub Actions Scrape

**Automatically (via admin panel):** Handled by `ResultService._queue_scrape_workflow()`.

**Manually (via API):**
```bash
curl -X POST https://api.github.com/repos/OWNER/REPO/actions/workflows/scrape.yml/dispatches \
  -H "Authorization: Bearer $GITHUB_WORKFLOW_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -d '{"ref":"main","inputs":{"exam_id":"1563"}}'
```

**Required env vars on the Actions runner:**
- `SCRAPER_SECRET` — must match the app's `SCRAPER_SECRET`
- `INGEST_URL` — e.g., `https://your-app.vercel.app/internal/ingest`

---

## Skill: Handle Retake/Improvement Exams

The system distinguishes retake exams by name keywords: `retake`, `improvement`, `retake/improvement`, `retake/impovement` (typo is intentional — matches the portal).

**Detection:** `utils.is_retake_improvement(exam_name)` → `bool`

**Processing flow:**
1. Identify the corresponding regular exam using `exam_repo.get_by_semester_and_session(semester, session_id)`.
2. Call `result_service.process_improvement_results(retake_exam_id, regular_exam_id)`.
3. Internally calls `merge_and_save_improvement()` which:
   - Looks up the student's existing result for the regular exam.
   - For each subject, keeps the higher grade point.
   - Marks improved subjects with `improved: True`.
   - Recalculates GPA and PASS/FAIL status.

---

## Skill: Debug Registration Number Lookup

The system accepts 3 formats:
1. Full: `2022-001-005` or `2022001005` (10 digits) → formatted via `format_registration_no()`
2. Short: `005` (3 digits) → resolved via DB lookup (`LIKE '%-005'`)
3. Arbitrary suffix: falls back to `resolve_registration_from_suffix()`

If a registration isn't being found:
- Check `sample_registrations.txt` — the reg must be in this file for the student to log in.
- Check `normalize_registration()` — it strips all non-alphanumeric chars and uppercases.
- Check the DB `results` table — the registration format stored there must match what's in the file.

---

## Skill: Add a New Sort Column to Results Table

**In `templates/index.html`:**
1. Add a `<th>` with `onclick="sortTable('myfield')"` and a `sort-indicator` span.
2. Add the reset and set logic in the `sortTable()` JS function.
3. Add the comparison logic in `filterAndRender()` → the `.sort()` call.

**In `models.py` → `ResultRepository.format_for_display()`:**
- Ensure the field is included in the returned dicts.

**In `models.py` → `ResultRepository.get_by_exam()`:**
- Add the field to the `ORDER BY` clause if it should be the default sort.

---

## Skill: Clear Stale Caches

**API result cache** (in-memory, per process):
```python
api_results_cache.pop(exam_id, None)  # done automatically on add/delete/ingest
```

**`load_nonempty_lines` LRU cache** (stale after file changes):
```python
from app_helpers import load_nonempty_lines
load_nonempty_lines.cache_clear()
```
> ⚠️ There's currently no endpoint to do this — add one if hot-reloading registrations is needed.

---

## Skill: Run the Scraper Worker Locally

```bash
# Set required env vars
export SCRAPER_SECRET="your-secret-here"
export INGEST_URL="http://localhost:5000/internal/ingest"

# Run the worker
python scraper_worker.py \
  --exam-id 1563 \
  --input-file sample_registrations.txt \
  --min-delay 0.5 \
  --max-delay 1.5
```

The worker will:
1. Read all registrations from the input file.
2. Scrape results from the DUCMC portal.
3. POST results in batches to `INGEST_URL`.
4. Retry up to 3 times per registration with exponential backoff.

---

## Skill: Check Scrape Job Status

Via the admin panel (`/admin`), scrape job status is shown per exam.

Via DB directly:
```sql
SELECT exam_id, status, created_at, updated_at FROM scrape_jobs ORDER BY updated_at DESC;
```

Possible statuses:
- `queued` — GitHub Actions workflow dispatched, not yet started
- `processing` — local background thread is running
- `completed` — scrape finished successfully
- `failed` — scrape encountered errors (partial data may exist)

---

## Skill: Add Multi-Program Support

Currently hardcoded to Program ID `14` (B.Sc. CSE). To support other programs:
1. Add a `program_id` selector to the admin `add_exam` form.
2. Pass it through `exam_repo.create()` (already accepts `program_id` param).
3. Expand `COURSES_DATA` in `ducmc_result_scraper.py` with the new program's courses.
4. Update `infer_session_id()` in `app_helpers.py` if different programs use different session IDs.
5. Add program-specific credit fallback logic to `positional_credit_fallback()` if needed.

---

## Common Pitfalls to Avoid

| Pitfall | Correct Approach |
|---------|-----------------|
| Using `%s` in SQL queries | Use `?` — `rewrite_sql()` handles translation |
| Calling `conn.commit()` manually | The `get_connection()` context manager auto-commits |
| Storing secrets in `config.ini` for production | Use environment variables |
| Running scraping on Vercel directly | Always dispatch to GitHub Actions |
| Forgetting to clear `api_results_cache` after DB writes | Pop the key: `api_results_cache.pop(exam_id, None)` |
| Adding exam without checking for duplicates | `exam_repo.get_by_semester_and_session()` first |
| Assuming `row['field']` returns a string | DB rows may return `None` — always use `.get()` or check |
| Editing `sample_registrations.txt` and expecting immediate effect | `load_nonempty_lines` is `@lru_cache` — call `.cache_clear()` |
