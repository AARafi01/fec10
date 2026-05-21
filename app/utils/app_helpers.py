from functools import lru_cache
import json
import re
from typing import Iterable, Optional

DEFAULT_PROGRAM_ID = '14'
DEFAULT_SESSION_ID = '23'
DEFAULT_EXAM_YEAR = '2024'

_NON_ALNUM_RE = re.compile(r'[^a-zA-Z0-9]')
_NON_DIGIT_RE = re.compile(r'[^0-9]')


def normalize_registration(value: str) -> str:
    return _NON_ALNUM_RE.sub('', value or '').upper()


def digits_only(value: str) -> str:
    return _NON_DIGIT_RE.sub('', value or '')


def format_registration_no(value: str) -> str:
    cleaned = digits_only(value)
    if len(cleaned) == 10:
        return f'{cleaned[:4]}-{cleaned[4:7]}-{cleaned[7:]}'
    return (value or '').strip()


@lru_cache(maxsize=1)
def load_nonempty_lines(file_path: str = 'sample_registrations.txt') -> tuple[str, ...]:
    try:
        with open(file_path, 'r') as handle:
            return tuple(line.strip() for line in handle if line.strip())
    except Exception:
        return tuple()


def resolve_registration_from_suffix(suffix: str, *candidate_groups: Iterable[str]) -> Optional[str]:
    suffix_clean = digits_only(suffix)
    if len(suffix_clean) != 3:
        return None

    seen = set()
    for group in candidate_groups:
        for candidate in group:
            candidate_clean = (candidate or '').strip()
            if not candidate_clean or candidate_clean in seen:
                continue
            seen.add(candidate_clean)
            normalized = normalize_registration(candidate_clean)
            if normalized.endswith(suffix_clean) or digits_only(candidate_clean) == suffix_clean:
                return candidate_clean
    return None


def build_regular_exam_name(semester: str) -> str:
    sem_num = int(semester)
    year_suffixes = {1: '1st', 2: '2nd', 3: '3rd', 4: '4th'}
    sem_suffixes = {1: '1st', 2: '2nd'}
    year = (sem_num - 1) // 2 + 1
    sem = (sem_num - 1) % 2 + 1
    return f"{year_suffixes[year]} Year {sem_suffixes[sem]} Semester"


def parse_subject_grades(result_data: dict) -> list[dict]:
    grades = []
    for subject in result_data.get('subjects', []):
        grade_value = 0.0
        point_value = subject.get('point')
        if point_value not in (None, ''):
            try:
                grade_value = float(point_value)
            except (ValueError, TypeError):
                grade_value = 0.0

        status = str(subject.get('status', '')).lower()
        if 'fail' in status or status == 'f':
            grade_value = 0.0

        grades.append({
            'code': subject.get('code', ''),
            'title': subject.get('title', ''),
            'grade': grade_value,
            'status': subject.get('status', ''),
        })
    return grades


def infer_session_id(registration_no: str, default_session: str = DEFAULT_SESSION_ID) -> str:
    if default_session == '23' and len(digits_only(registration_no)) == 3:
        return '22'
    return default_session


def safe_json_loads(raw_value: str) -> dict:
    if not raw_value:
        return {}
    try:
        return json.loads(raw_value)
    except Exception:
        return {}


def extract_exam_display_fields(result_data_json: str, created_at: str | None, default_exam_year: str = DEFAULT_EXAM_YEAR) -> tuple[str, str]:
    exam_year = default_exam_year
    pub_date = created_at.split(' ')[0] if created_at else 'N/A'

    if not result_data_json:
        return exam_year, pub_date

    try:
        data = json.loads(result_data_json)
    except Exception:
        return exam_year, pub_date

    info = data.get('student_info', {})
    exam_year_value = next((v for k, v in info.items() if k.lower().strip() == 'exam year'), None)
    pub_date_value = next((v for k, v in info.items() if k.lower().strip() == 'result publication date'), None)

    if exam_year_value:
        exam_year = exam_year_value
    if pub_date_value:
        pub_date = pub_date_value

    return exam_year, pub_date