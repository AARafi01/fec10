# DU Crack — Project Knowledge for AI Agents

## Project Overview

**DU Crack** is a Flask web application that scrapes, stores, and displays academic exam results for students from the **Dhaka University College of Management and Commerce (DUCMC)** portal (`https://ducmc.du.ac.bd/result.php`).

It targets **B.Sc. in Computer Science and Engineering** students (Program ID `14`) and is designed to be deployed on Vercel (serverless) with GitHub Actions handling the heavy scraping workload.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       index.py (entry)                          │
│                  imports app from app/__init__.py               │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                    app/__init__.py                               │
│  Creates Flask app · Registers blueprints · Jinja filters        │
└──────┬────────────────────┬──────────────────────────┬──────────┘
       │                    │                          │
┌──────▼───────┐  ┌─────────▼──────────┐  ┌───────────▼──────────┐
│ app/routes/  │  │  app/extensions.py │  │   app/models/        │
│  main.py     │  │  (singletons)      │  │   models.py          │
│  admin.py    │  │  db, repos,        │  │  Database, Repos     │
│  api.py      │  │  services, cache   │  │  (tri-mode adapter)  │
└──────────────┘  └─────────┬──────────┘  └──────────────────────┘
                            │
               ┌────────────▼───────────────────────────────┐
               │            app/services/services.py         │
               │      ResultService · ConfigService          │
               └────────────┬───────────────────────────────┘
                            │
          ┌─────────────────▼──────────────────────────────────┐
          │               app/scraper/                          │
          │   ducmc_result_scraper.py  ·  scraper_worker.py    │
          └─────────────────────────────────────────────────────┘

          app/utils/
            utils.py        — Exam name parsing, semester inference
            app_helpers.py  — Registration formatting, session helpers
            gpa_calc.py     — COURSES_DATA, calculate_gpa(), CGPA logic
```

### Key Files

| Path | Purpose |
|------|---------|
| `index.py` | Entrypoint — imports and exposes `app` for Vercel / WSGI |
| `app/__init__.py` | Flask app factory — registers blueprints, Jinja filters |
| `app/extensions.py` | Instantiates all singletons: `db`, repos, `result_service`, `api_results_cache` |
| `app/models/models.py` | `Database` tri-mode adapter + all repository classes |
| `app/services/services.py` | `ResultService` (scraping orchestration, improvement merging), `ConfigService` |
| `app/routes/main.py` | Student-facing page routes (`/`, `/login`, `/student_login`, `/gpa_calc`) |
| `app/routes/admin.py` | Admin panel routes (`/admin`, `/admin/add_exam`, `/admin/delete_exam`, etc.) |
| `app/routes/api.py` | API + internal routes (`/api/results`, `/api/student_grades`, `/api/cron/check-exams`, `/api/telegram/webhook`, `/internal/ingest`) |
| `app/scraper/ducmc_result_scraper.py` | Core scraper — HTTP (primary) and Selenium (legacy) modes |
| `app/scraper/scraper_worker.py` | Standalone CLI scraper — run by GitHub Actions |
| `app/utils/utils.py` | `standardize_exam_name`, `parse_semester_from_name`, `is_retake_improvement`, `positional_credit_fallback` |
| `app/utils/app_helpers.py` | `format_registration_no`, `load_nonempty_lines`, `resolve_registration_from_suffix`, `parse_subject_grades`, `infer_session_id` |
| `app/utils/gpa_calc.py` | `courses_data` (full curriculum), `COURSES_DATA` flat map, `calculate_gpa()`, `calculate_semester_gpa()` |
| `config.ini` | Local configuration (secrets, delays, known exam IDs) |
| `sample_registrations.txt` | One registration number per line — the student list to scrape |
| `vercel.json` | Vercel deployment config |

---

## Database Layer

The `Database` class in `app/models/models.py` is a **tri-mode adapter** supporting:

| Mode | Trigger |
|------|---------|
| **SQLite** (default) | No `DATABASE_URL` env var |
| **PostgreSQL** | `DATABASE_URL` starts with `postgres://` or `postgresql://` |
| **Turso (libSQL)** | `DATABASE_URL` starts with `libsql://` or `turso://`, with `TURSO_AUTH_TOKEN` |

> **Important:** All SQL is written in SQLite syntax. `rewrite_sql()` in `models.py` transparently translates it to PostgreSQL syntax (e.g., `?` → `%s`, `INSERT OR IGNORE` → `ON CONFLICT DO NOTHING`).

### Tables

| Table | Description |
|-------|------------|
| `exams` | Each registered exam (ID, name, program, session, semester, active status) |
| `results` | Per-student per-exam result rows; full JSON result data in `result_data`, computed GPA in `gpa` column |
| `scrape_jobs` | Tracks scrape job status (`queued`, `processing`, `completed`, `failed`) per exam |
| `notified_exams` | Exams that have been Telegram-notified (to avoid repeat alerts) |
| `processed_improvements` | Tracks retake/improvement exams that have already been merged |
| `retake_mappings` | Maps `retake_exam_id → regular_exam_id`; set at approval time before scraping starts |
| `merge_logs` | Audit log of every retake merge operation (who triggered it, how many students merged) |
| `login_logs` | Student login history |

### Repositories (all in `app/models/models.py`)

| Class | Manages |
|-------|---------|
| `ExamRepository` | `exams` table — CRUD, lookup by exam_id/semester/session |
| `ResultRepository` | `results`, `scrape_jobs`, `processed_improvements` tables |
| `LoginLogRepository` | `login_logs` table |
| `MergeLogRepository` | `merge_logs` table |
| `RetakeMappingRepository` | `retake_mappings` table |

All singletons (db + repos + services) are created once in `app/extensions.py` and imported from there throughout the app.

---

## Scraping System

### Primary Method: HTTP/requests (no browser)
`DUCMCResultScraper.get_result_requests()` in `app/scraper/ducmc_result_scraper.py` and the mirrored function in `scraper_worker.py`:
- POSTs to `https://ducmc.du.ac.bd/ajax/get_program_by_exam.php`
- Parses HTML response with BeautifulSoup
- Extracts student info table + subject grades table

### Secondary Method: Selenium (legacy/fallback)
The `DUCMCResultScraper` class (Selenium-based) is used only for local testing. The HTTP method is always preferred in production.

### Registration Number Format
- Full format: `YYYY-NNN-NNN` (10 digits with dashes, e.g., `2022-001-005`)
- Short format: last 3 digits only (e.g., `005`) — resolved to full reg via DB lookup
- For scraping: all non-numeric characters are stripped before the POST

### Session ID Inference (`app/utils/app_helpers.infer_session_id`)
- Default session: `23` (2022–2023)
- If registration has only 3 digits and session is `23`, it uses `22` (2021–2022 students)

---

## Scraping Workflow (Production)

1. **Admin adds exam** via `/admin/add_exam` form (or Telegram `✅ Approve & Scrape` button).
2. `ResultService.process_exam_results()` is called.
3. If `GITHUB_REPOSITORY` + `GITHUB_WORKFLOW_TOKEN` are set → dispatches `scrape.yml` GitHub Actions workflow.
4. The GitHub Action runs `app/scraper/scraper_worker.py` with the exam ID.
5. Worker scrapes results and POSTs batches to `/internal/ingest` (protected by `SCRAPER_SECRET`).
6. `/internal/ingest` in `api.py` saves each result to the DB via `ResultRepository.save()`.

> **Vercel constraint:** Vercel's serverless functions time out quickly. All scraping must be offloaded to GitHub Actions. Local background threading (`threading.Thread`) is only a fallback for local dev.

---

## Telegram Bot Integration

- **Notification on new exam discovery:** `/api/cron/check-exams` (called by cron or Vercel cron job) checks the DUCMC portal and sends Telegram alerts for new exams not yet in the DB.
- **Webhook:** `/api/telegram/webhook` handles:
  - `/check` command — manually check for new exams
  - Inline button `✅ Approve & Scrape` — triggers scraping for a specific exam
  - Inline button `❌ Ignore` — dismisses the Telegram notification
- **Setup:** `/api/telegram/setup` (protected by API key) registers the webhook with Telegram.
- **Retake handling in webhook:** When approving a retake exam, `ResultService.resolve_and_process_improvement()` is called instead of `process_exam_results()`. This sets the `retake_mappings` entry before dispatching the GitHub Action.

---

## Authentication

| Access Level | Mechanism |
|-------------|-----------|
| **Student** | Registration number looked up in `sample_registrations.txt`; stored in `session['student_reg']` |
| **Admin** | Username/password from env/config.ini; stored in `session['logged_in']` |
| **API/Cron** | `?key=<API_SECRET>` query param, `X-API-Key` header, or `Authorization: Bearer <CRON_SECRET>` |
| **Scraper ingest** | `X-SCRAPER-SECRET` header must match `SCRAPER_SECRET` env var |

---

## GPA Calculation

All GPA logic lives in `app/utils/gpa_calc.py` — the single source of truth.

- **`courses_data`** — Full curriculum dict organized by semester name (`"Semester 1"` … `"Semester 8"`), each containing a list of `{code, title, credit}` objects.
- **`COURSES_DATA`** — Flat `code → credit` dict derived from `courses_data`. Used for O(1) credit lookup by course code.
- **`_NORMALIZED_COURSES`** — Same as `COURSES_DATA` but with codes normalized (spaces/dashes stripped, uppercased) for fuzzy matching.

### `calculate_gpa(subjects)` — authoritative function
- Iterates over a student's `subjects` list (from `result_data`)
- Looks up credit by normalized course code (`_NORMALIZED_COURSES`)
- Falls back to `positional_credit_fallback(idx)` if the code isn't in the map:
  - idx 0–4 → 3.0 credits
  - idx 5 → 2.0 credits
  - idx 6–8 → 1.5 credits
  - idx 9+ → 0.75 credits
- Grades of `F` or containing `FAIL` → 0.0 grade points
- Returns `round(total_weighted / total_credits, 2)`

### `calculate_semester_gpa(semester_name, grades)` — used by GPA calculator page
- Takes a semester name (e.g. `"Semester 3"`) and a dict of `{course_code: grade_point}`
- Computes credit-weighted GPA for that semester only

### CGPA Calculation
CGPA is computed at display time in `ResultRepository.format_for_display()`:
- Queries `AVG(gpa)` grouped by `registration_no` across all non-retake exams
- Retake exam rows are excluded via `exam_id NOT IN (SELECT retake_exam_id FROM retake_mappings)`

**Retake/Improvement merging:** When a retake exam is approved, `ResultService.merge_and_save_improvement()` compares new grades with existing ones subject-by-subject, keeping whichever grade point is higher. The `improved: True` flag is set on upgraded subjects in `result_data`.

---

## Exam Naming

`utils.standardize_exam_name()` normalizes exam names to a consistent format:
- Input: `"B.Sc. in CSE 2nd year 1st Semester Examination of 2024"`
- Output: `"2nd Year 1st Semester"`
- Retake output: `"2nd Year 1st Semester - Retake/Improvement"`

Semester numbers (1–8) are derived from year+semester ordinals:
- 1st Year 1st Sem → Semester 1
- 1st Year 2nd Sem → Semester 2
- ... up to 4th Year 2nd Sem → Semester 8

---

## Environment Variables

| Variable | Purpose |
|----------|---------| 
| `SECRET_KEY` | Flask session secret key |
| `ADMIN_USERNAME` | Admin panel login |
| `ADMIN_PASSWORD` | Admin panel password |
| `DATABASE_URL` | PostgreSQL / Turso connection string (optional, falls back to SQLite) |
| `TURSO_AUTH_TOKEN` | Auth token for Turso (libSQL) |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Telegram chat/channel ID for alerts |
| `API_SECRET` | Secret for protecting cron/API endpoints |
| `CRON_SECRET` | Alternative secret accepted as `Authorization: Bearer <CRON_SECRET>` |
| `SCRAPER_SECRET` | Secret for the `/internal/ingest` endpoint |
| `GITHUB_REPOSITORY` | e.g. `Rafi-Sama/du-crack` — for Actions dispatch |
| `GITHUB_WORKFLOW_TOKEN` | GitHub PAT with `workflow` scope |
| `GITHUB_WORKFLOW_FILE` | Workflow filename (default: `scrape.yml`) |
| `GITHUB_WORKFLOW_REF` | Branch ref (default: `main`) |
| `INGEST_URL` | URL the scraper worker posts results to (used in GitHub Actions) |
| `VERCEL` | Set to `1` automatically by Vercel — disables local threading, redirects DB to `/tmp` |

All variables can also be set in `config.ini` under `[SETTINGS]` as fallback.

---

## Frontend

- Jinja2 templates extending `templates/base.html`
- Bootstrap 5 + FontAwesome icons
- Custom CSS in `static/css/`
- Vanilla JS for dynamic result loading, sorting, filtering, and modals
- Component macros in `templates/components/`:
  - `badges.html` — GPA/status badge rendering
  - `cards.html` — reusable card layout
  - `loader.html` — loading spinner

### Key Frontend Behavior
- Results are fetched via `POST /process_results` (triggers re-scrape or returns cache)
- Raw data is fetched via `GET /api/results/<exam_id>` (cached in `api_results_cache` dict in `app/extensions.py`)
- Student grades across all semesters are fetched via `GET /api/student_grades/<registration_no>`
- GPA calculator course data is fetched via `GET /api/gpa_courses` (returns `courses_data` from `gpa_calc.py`)
- Table supports live search (by reg no, roll, name) and sort (by GPA, CGPA, reg no, class roll)

---

## GitHub Actions Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------| 
| `scrape.yml` | `workflow_dispatch` with `exam_id` input | Runs `app/scraper/scraper_worker.py` for a specific exam |
| `discovery.yml` | Scheduled (cron) | Calls `/api/cron/check-exams` to find new exams |

---

## Known Issues & Gotchas

1. **`load_nonempty_lines` is cached with `@lru_cache`** — changes to `sample_registrations.txt` at runtime won't be picked up without a server restart.
2. **`api_results_cache` is in-memory** — stored in `app/extensions.py`. Cleared on exam add/delete and on ingest, but lost on server restart. Not suitable for multi-worker deployments.
3. **Vercel ephemeral `/tmp` DB** — When running on Vercel, the SQLite DB is copied to `/tmp/database.db` at startup, but writes are lost after the function instance terminates. Use PostgreSQL or Turso for persistent storage on Vercel.
4. **Duplicate scrape protection** — `ResultRepository.claim_scrape_job()` uses `INSERT OR IGNORE` to prevent two parallel scrapes of the same exam from running simultaneously.
5. **Config.ini contains secrets** — `config.ini` has real Telegram tokens, admin credentials, and secret keys committed in plain text. These should be moved to environment variables for production and `config.ini` should be in `.gitignore`.
6. **`positional_credit_fallback`** — Used when a course code isn't in `COURSES_DATA`. This may produce inaccurate GPAs for courses not in the hardcoded map.
7. **Retake flow requires `retake_mappings` entry** — During `/internal/ingest`, the system first checks `retake_mappings` to identify retake exams. If the entry is missing (e.g., exam was added manually without going through the approval flow), the fallback logic reads the exam name from `exams` table. A missing regular exam causes the result to be silently skipped (not saved under the retake exam_id either).

---

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Run the Flask dev server
python index.py
# or
bash run.sh
```

The app runs at `http://localhost:5000`.

For testing scraper worker standalone:
```bash
SCRAPER_SECRET=test python app/scraper/scraper_worker.py \
  --exam-id 1563 \
  --ingest-url http://localhost:5000/internal/ingest
```

---

## Deployment (Vercel)

- `vercel.json` configures the Flask app as a serverless function.
- Set all environment variables in Vercel dashboard or via `vercel env`.
- Use PostgreSQL (e.g., Supabase, Neon) or Turso as the database.
- Enable the `discovery.yml` cron in GitHub Actions or use Vercel's cron jobs to call `/api/cron/check-exams`.
- Health check available at `/api/health?key=<API_SECRET>` — reports DB, GitHub Actions, Telegram, and DUCMC portal status.
