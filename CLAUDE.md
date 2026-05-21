# DU Crack — Project Knowledge for AI Agents

## Project Overview

**DU Crack** is a Flask web application that scrapes, stores, and displays academic exam results for students from the **Dhaka University College of Management and Commerce (DUCMC)** portal (`https://ducmc.du.ac.bd/result.php`).

It targets **B.Sc. in Computer Science and Engineering** students (Program ID `14`) and is designed to be deployed on Vercel (serverless) with GitHub Actions handling the heavy scraping workload.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Flask App (app.py)                    │
│  Routes · Auth · Telegram Webhook · Cron Endpoints     │
└────────────┬──────────────────────────┬─────────────────┘
             │                          │
    ┌────────▼────────┐      ┌──────────▼──────────┐
    │   services.py   │      │      models.py       │
    │ ResultService   │      │  Database (SQLite /  │
    │ ConfigService   │      │  PostgreSQL / Turso) │
    └────────┬────────┘      └──────────────────────┘
             │
    ┌────────▼────────────────────────────────────┐
    │          ducmc_result_scraper.py             │
    │  DUCMCResultScraper (HTTP + Selenium modes) │
    └────────┬────────────────────────────────────┘
             │
    ┌────────▼────────────────┐
    │    scraper_worker.py    │  ← Run by GitHub Actions
    │  Standalone CLI worker  │
    └─────────────────────────┘
```

### Key Files

| File | Purpose |
|------|---------|
| `app.py` | Main Flask application, all routes and request handling |
| `models.py` | Database abstraction (SQLite/PostgreSQL/Turso) + all repositories |
| `services.py` | Business logic — `ResultService`, `ConfigService`, `RegistrationService` |
| `ducmc_result_scraper.py` | Core scraper — HTTP mode (primary) and Selenium mode (legacy) |
| `scraper_worker.py` | Standalone CLI scraper for GitHub Actions workflow dispatch |
| `utils.py` | Pure utility functions — exam name parsing, GPA credit fallback |
| `app_helpers.py` | Request-layer helpers — registration formatting, session inference, caching |
| `gpa_calc.py` | GPA/CGPA calculator logic used in the `/gpa_calc` page |
| `check_results_cron.py` | Standalone cron script (alternative to the webhook-based cron) |
| `config.ini` | Local configuration (secrets, delays, known exam IDs) |
| `sample_registrations.txt` | One registration number per line — the student list to scrape |
| `vercel.json` | Vercel deployment config |

---

## Database Layer

The `Database` class in `models.py` is a **tri-mode adapter** supporting:

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
| `results` | Per-student per-exam result rows, with full JSON result data stored in `result_data` |
| `scrape_jobs` | Tracks scrape job status (`queued`, `processing`, `completed`, `failed`) per exam |
| `notified_exams` | Exams that have been Telegram-notified (to avoid repeat alerts) |
| `processed_improvements` | Tracks retake/improvement exams that have already been merged |
| `login_logs` | Student login history |

---

## Scraping System

### Primary Method: HTTP/requests (no browser)
`DUCMCResultScraper.get_result_requests()` in `ducmc_result_scraper.py` and the mirrored `get_result_requests()` in `scraper_worker.py`:
- POSTs to `https://ducmc.du.ac.bd/ajax/get_program_by_exam.php`
- Parses HTML response with BeautifulSoup
- Extracts student info table + subject grades table

### Secondary Method: Selenium (legacy/fallback)
The `DUCMCResultScraper` class (Selenium-based) is used only for local testing. The `headless=True` flag exists but the HTTP method is always preferred in production.

### Registration Number Format
- Full format: `YYYY-NNN-NNN` (10 digits with dashes, e.g., `2022-001-005`)
- Short format: last 3 digits only (e.g., `005`) — resolved to full reg via DB lookup
- For scraping: all non-numeric characters are stripped before the POST

### Session ID Inference (`app_helpers.infer_session_id`)
- Default session: `23` (2022–2023)
- If registration has only 3 digits and session is `23`, it uses `22` (2021–2022 students)

---

## Scraping Workflow (Production)

1. **Admin adds exam** via `/admin/add_exam` form.
2. `ResultService.process_exam_results()` is called.
3. If `GITHUB_REPOSITORY` + `GITHUB_WORKFLOW_TOKEN` are set → dispatches `scrape.yml` GitHub Actions workflow.
4. The GitHub Action runs `scraper_worker.py` with the exam ID.
5. Worker scrapes results and POSTs batches to `/internal/ingest` (protected by `SCRAPER_SECRET`).
6. `app.py` saves each result to the DB.

> **Vercel constraint:** Vercel's serverless functions time out quickly. All scraping must be offloaded to GitHub Actions. Local background threading (`threading.Thread`) is only a fallback for local dev.

---

## Telegram Bot Integration

- **Notification on new exam discovery:** `/api/cron/check-exams` (called by cron or Vercel cron job) checks the DUCMC portal and sends Telegram alerts for new exams not yet in the DB.
- **Webhook:** `/api/telegram/webhook` handles:
  - `/check` command — manually check for new exams
  - Inline button `✅ Approve & Scrape` — triggers scraping for a specific exam
  - Inline button `❌ Ignore` — dismisses the Telegram notification
- **Setup:** `/api/telegram/setup` (protected by API key) registers the webhook with Telegram.

---

## Authentication

| Access Level | Mechanism |
|-------------|-----------|
| **Student** | Registration number looked up in `sample_registrations.txt`; stored in `session['student_reg']` |
| **Admin** | Username/password from env/config.ini; stored in `session['logged_in']` |
| **API/Cron** | `?key=<API_SECRET>` query param or `X-API-Key` header |
| **Scraper ingest** | `X-SCRAPER-SECRET` header must match `SCRAPER_SECRET` env var |

---

## GPA Calculation

The custom credit-weighted GPA formula uses `COURSES_DATA` dict (defined in `ducmc_result_scraper.py`):
- Maps course codes like `CSE-2101` → credit hours (e.g., `3.0`)
- If a course code isn't in `COURSES_DATA`, `positional_credit_fallback(idx)` is used:
  - idx 0–4 → 3.0 credits
  - idx 5 → 2.0 credits
  - idx 6–8 → 1.5 credits
  - idx 9+ → 0.75 credits

**Retake/Improvement merging:** When a retake exam is approved, `ResultService.merge_and_save_improvement()` compares the new grades with existing ones subject-by-subject and keeps whichever grade point is higher. The `improved: True` flag is set on upgraded subjects.

---

## Exam Naming

`utils.standardize_exam_name()` normalizes exam names to a consistent format:
- Input: `"B.Sc. in CSE 2nd year 1st Semester Examination of 2024"`
- Output: `"2nd Year 1st Semester"`
- Retake output: `"2nd Year 1st Semester - Retake/Improvement"`

Semester numbers (1–8) are derived from year+semester ordinals:
- 1st Year 1st Sem → Semester 1
- 1st Year 2nd Sem → Semester 2
- ... and so on up to 4th Year 2nd Sem → Semester 8

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
| `SCRAPER_SECRET` | Secret for the `/internal/ingest` endpoint |
| `GITHUB_REPOSITORY` | e.g. `Rafi-Sama/du-crack` — for Actions dispatch |
| `GITHUB_WORKFLOW_TOKEN` | GitHub PAT with `workflow` scope |
| `GITHUB_WORKFLOW_FILE` | Workflow filename (default: `scrape.yml`) |
| `GITHUB_WORKFLOW_REF` | Branch ref (default: `main`) |
| `INGEST_URL` | URL the scraper worker posts results to (used in GitHub Actions) |
| `VERCEL` | Set to `1` automatically by Vercel — disables local threading |

All variables can also be set in `config.ini` under `[SETTINGS]` as fallback.

---

## Frontend

- Jinja2 templates extending `base.html`
- Bootstrap 5 + FontAwesome icons
- Custom CSS in `static/css/`
- Vanilla JS for dynamic result loading, sorting, filtering, and modals
- Component macros in `templates/components/`:
  - `badges.html` — GPA/status badge rendering
  - `cards.html` — reusable card layout
  - `loader.html` — loading spinner

### Key Frontend Behavior
- Results are fetched via `POST /process_results` (triggers re-scrape or returns cache)
- Raw data is fetched via `GET /api/results/<exam_id>` (cached in `api_results_cache` dict)
- Student grades across all semesters are fetched via `GET /api/student_grades/<registration_no>`
- Table supports live search (by reg no, roll, name) and sort (by GPA, CGPA, reg no, class roll)

---

## GitHub Actions Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `scrape.yml` | `workflow_dispatch` with `exam_id` input | Runs `scraper_worker.py` for a specific exam |
| `discovery.yml` | Scheduled (cron) | Calls `/api/cron/check-exams` to find new exams |

---

## Known Issues & Gotchas

1. **`load_nonempty_lines` is cached with `@lru_cache`** — changes to `sample_registrations.txt` at runtime won't be picked up without a server restart.
2. **`api_results_cache` is in-memory** — cleared on each new exam add/delete and on ingest, but lost on server restart. Not suitable for multi-worker deployments.
3. **Vercel ephemeral `/tmp` DB** — When running on Vercel, the SQLite DB is copied to `/tmp/database.db` at startup, but writes are lost after the function instance terminates. Use PostgreSQL or Turso for persistent storage on Vercel.
4. **Duplicate scrape protection** — `result_repo.claim_scrape_job()` uses `INSERT OR IGNORE` to prevent two parallel scrapes of the same exam from running simultaneously.
5. **Config.ini contains secrets** — `config.ini` has real Telegram tokens, admin credentials, and secret keys committed in plain text. These should be moved to environment variables for production and `config.ini` should be in `.gitignore`.
6. **`positional_credit_fallback`** — Used when a course code isn't in `COURSES_DATA`. This may produce inaccurate GPAs for courses not in the hardcoded map.

---

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Run the Flask dev server
python app.py
# or
bash run.sh
```

The app runs at `http://localhost:5000`.

For testing scraper worker standalone:
```bash
SCRAPER_SECRET=test python scraper_worker.py \
  --exam-id 1563 \
  --ingest-url http://localhost:5000/internal/ingest
```

---

## Deployment (Vercel)

- `vercel.json` configures the Flask app as a serverless function.
- Set all environment variables in Vercel dashboard or via `vercel env`.
- Use PostgreSQL (e.g., Supabase, Neon) or Turso as the database.
- Enable the `discovery.yml` cron in GitHub Actions or use Vercel's cron jobs to call `/api/cron/check-exams`.
