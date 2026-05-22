import configparser
import os
import time
import random
import threading
from typing import List,Dict
import requests
from app.scraper.ducmc_result_scraper import DUCMCResultScraper
from app.models.models import ExamRepository,ResultRepository
from app.utils.app_helpers import infer_session_id, load_nonempty_lines, safe_json_loads, DEFAULT_PROGRAM_ID, DEFAULT_SESSION_ID
from app.utils.gpa_calc import calculate_gpa as _canonical_calculate_gpa

class ConfigService:
 def __init__(self,config_path:str='config.ini'):
  self.config=configparser.ConfigParser()
  try:self.config.read(config_path)
  except Exception:pass
 def get(self,section:str,key:str,fallback:str='')->str:
  try:return self.config.get(section,key).strip()
  except(configparser.NoSectionError,configparser.NoOptionError):return fallback

class RegistrationService:
 @staticmethod
 def load_from_file(file_path:str='sample_registrations.txt')->List[str]:
  return list(load_nonempty_lines(file_path))


class ResultService:
 def __init__(self,exam_repo:ExamRepository,result_repo:ResultRepository,config_service:ConfigService,merge_log_repo=None,retake_mapping_repo=None):
  self.exam_repo=exam_repo
  self.result_repo=result_repo
  self.config=config_service
  self.merge_log_repo=merge_log_repo
  self.retake_mapping_repo=retake_mapping_repo

 def _queue_scrape_workflow(self, exam_id: str) -> Dict:
  repo = os.environ.get('GITHUB_REPOSITORY') or self.config.get('SETTINGS', 'GITHUB_REPOSITORY', '').strip()
  token = os.environ.get('GITHUB_WORKFLOW_TOKEN') or self.config.get('SETTINGS', 'GITHUB_WORKFLOW_TOKEN', '').strip()
  workflow_file = os.environ.get('GITHUB_WORKFLOW_FILE', 'scrape.yml')
  workflow_ref = os.environ.get('GITHUB_WORKFLOW_REF', 'main')

  if not repo or not token:
   return {'queued': False, 'message': 'GitHub workflow dispatch is not configured'}

  url = f'https://api.github.com/repos/{repo}/actions/workflows/{workflow_file}/dispatches'
  headers = {
   'Authorization': f'Bearer {token}',
   'Accept': 'application/vnd.github+json',
   'X-GitHub-Api-Version': '2022-11-28',
  }
  payload = {'ref': workflow_ref, 'inputs': {'exam_id': str(exam_id)}}
  response = requests.post(url, json=payload, headers=headers, timeout=20)
  if response.status_code not in (201, 204):
   return {'queued': False, 'message': f'GitHub dispatch failed with status {response.status_code}', 'details': response.text[:200]}
  return {'queued': True, 'message': 'Scrape job dispatched to GitHub Actions'}

 def _calculate_gpa(self,subjects:List[Dict])->float:
  """Delegate to the canonical credit-weighted GPA calculation in gpa_calc."""
  return _canonical_calculate_gpa(subjects)

 def _background_process_results(self, exam_id: str, reg_numbers: List[str], exam_data: Dict):
    failed = False
    for reg in reg_numbers:
      if not reg:
        continue
      try:
        sess_id = infer_session_id(reg, exam_data.get('session_id', '23'))
        data = DUCMCResultScraper.get_result_requests(
          reg,
          exam_data.get('program_id', DEFAULT_PROGRAM_ID),
          exam_data.get('exam_id', exam_id),
          sess_id,
        )
        if data and 'error' not in data:
          gpa = self._calculate_gpa(data.get('subjects', []))
          data['calculated_gpa'] = gpa
          self.result_repo.save(exam_id, reg, data)
        time.sleep(random.uniform(0.2, 0.5))
      except Exception:
        failed = True
        continue
    self.result_repo.update_scrape_job_status(exam_id, 'failed' if failed else 'completed')

 def process_exam_results(self,exam_id:str)->Dict:
  if not exam_id or not exam_id.strip():return{'success':False,'message':'Invalid exam ID','from_cache':False}
  exam=self.exam_repo.get_by_exam_id(exam_id)
  if not exam:return{'success':False,'message':'Exam not found','from_cache':False}
  cached=self.result_repo.get_by_exam(exam_id)
  if cached:return{'success':True,'results':self.result_repo.format_for_display(cached),'from_cache':True,'message':f'Found {len(cached)} cached results'}
  reg_numbers=RegistrationService.load_from_file()
  if not reg_numbers:return{'success':False,'message':'No registration numbers found','from_cache':False}

  if not self.result_repo.claim_scrape_job(exam_id, 'processing'):
   return{'success':True,'results':[],'from_cache':False,'queued':False,'already_running':True,'message':'Scrape already in progress','total_students':len(reg_numbers)}

  dispatch = self._queue_scrape_workflow(exam_id)
  if dispatch.get('queued'):
   self.result_repo.update_scrape_job_status(exam_id, 'queued')
   return{
    'success': True,
    'results': [],
    'from_cache': False,
    'queued': True,
    'message': f"Queued scrape for {len(reg_numbers)} students",
    'total_students': len(reg_numbers),
   }

  # If GitHub dispatch is not configured and we're running on a serverless host
  # (like Vercel), falling back to local background threads will not complete.
  # Return a clear error so admin can configure workflow dispatch instead.
  running_on_vercel = os.environ.get('VERCEL') == '1'
  dispatch_msg = (dispatch.get('message') or '').lower()
  if running_on_vercel or 'not configured' in dispatch_msg:
    try:
      self.result_repo.update_scrape_job_status(exam_id, 'failed')
    except Exception:
      pass
    return {
      'success': False,
      'results': [],
      'from_cache': False,
      'queued': False,
      'message': 'GitHub workflow dispatch is not configured. Set GITHUB_REPOSITORY and GITHUB_WORKFLOW_TOKEN in environment to enable remote scraping.',
      'details': dispatch.get('message')
    }

  thread = threading.Thread(target=self._background_process_results, args=(exam_id, reg_numbers, exam))
  thread.daemon = True
  thread.start()

  self.result_repo.update_scrape_job_status(exam_id, 'processing')

  return{'success':True,'results':[],'from_cache':False,'queued':False,'message':f'Started local background processing for {len(reg_numbers)} students','total_students':len(reg_numbers),'processed_count':len(reg_numbers)}

 def _background_process_improvements(self, retake_exam_id: str, regular_exam_id: str, reg_numbers: List[str], triggered_by: str = 'unknown'):
  failed = False
  students_merged = 0
  students_improved = 0
  for reg in reg_numbers:
    if not reg:
      continue
    try:
      sess_id = infer_session_id(reg)
      new_data = DUCMCResultScraper.get_result_requests(reg, DEFAULT_PROGRAM_ID, retake_exam_id, sess_id)
      if new_data and 'error' not in new_data:
        merge_result = self.merge_and_save_improvement(regular_exam_id, reg, new_data)
        if merge_result.get('ok'):
          students_merged += 1
          if merge_result.get('improved'):
            students_improved += 1
      time.sleep(random.uniform(0.2, 0.5))
    except Exception:
      failed = True
      continue
  self.result_repo.mark_improvement_processed(retake_exam_id)
  self.result_repo.update_scrape_job_status(retake_exam_id, 'failed' if failed else 'completed')
  if self.merge_log_repo:
    try:
      self.merge_log_repo.log_merge(retake_exam_id, regular_exam_id, students_merged, students_improved, triggered_by)
    except Exception:
      pass

 def resolve_and_process_improvement(self, retake_exam_id: str, exam_name: str, session_id: str = DEFAULT_SESSION_ID, triggered_by: str = 'unknown') -> Dict:
  """Resolve the matching regular exam by semester+session, then kick off the improvement scrape.
  Returns the same dict as process_improvement_results, plus a 'regular_exam' key on success."""
  from app.utils.utils import parse_semester_from_name
  semester = parse_semester_from_name(exam_name)
  regular_exam = None
  if semester:
   regular_exam = self.exam_repo.get_by_semester_and_session(semester, session_id)
  if not regular_exam:
   return {
    'success': False,
    'message': f'No matching regular exam found for semester {semester} (session {session_id}). Add the regular exam first.',
    'regular_exam': None,
   }
  res = self.process_improvement_results(retake_exam_id, regular_exam['exam_id'], triggered_by=triggered_by)
  res['regular_exam'] = regular_exam
  return res

 def process_improvement_results(self,retake_exam_id:str,regular_exam_id:str,triggered_by:str='unknown')->Dict:
  if not retake_exam_id or not regular_exam_id:return{'success':False,'message':'Invalid exam IDs'}
  reg_numbers=RegistrationService.load_from_file()
  if not reg_numbers:return{'success':False,'message':'No registration numbers found'}

  # Persist the retake→regular mapping so /internal/ingest can find it later
  if self.retake_mapping_repo:
   try:
    self.retake_mapping_repo.set_mapping(retake_exam_id, regular_exam_id)
   except Exception:
    pass

  if not self.result_repo.claim_scrape_job(retake_exam_id, 'processing'):
   return{'success':True,'queued':False,'already_running':True,'message':'Scrape already in progress','total_students':len(reg_numbers)}

  dispatch = self._queue_scrape_workflow(retake_exam_id)
  if dispatch.get('queued'):
   self.result_repo.update_scrape_job_status(retake_exam_id, 'queued')
   return{
    'success': True,
    'queued': True,
    'message': f"Queued retake/improvement scrape for {len(reg_numbers)} students",
    'total_students': len(reg_numbers),
   }

  running_on_vercel = os.environ.get('VERCEL') == '1'
  dispatch_msg = (dispatch.get('message') or '').lower()
  if running_on_vercel or 'not configured' in dispatch_msg:
    try:
      self.result_repo.update_scrape_job_status(retake_exam_id, 'failed')
    except Exception:
      pass
    return {
      'success': False,
      'queued': False,
      'message': 'GitHub workflow dispatch is not configured. Set GITHUB_REPOSITORY and GITHUB_WORKFLOW_TOKEN in environment to enable remote scraping.',
      'details': dispatch.get('message')
    }

  thread = threading.Thread(target=self._background_process_improvements, args=(retake_exam_id, regular_exam_id, reg_numbers, triggered_by))
  thread.daemon = True
  thread.start()

  self.result_repo.update_scrape_job_status(retake_exam_id, 'processing')

  return{'success':True,'queued':False,'message':f'Started local background Retake/Improvement processing for {len(reg_numbers)} students','total_students':len(reg_numbers),'processed_count':len(reg_numbers)}

 def merge_and_save_improvement(self,regular_exam_id:str,reg_no:str,new_data:Dict)->Dict:
  """Merge retake results into the existing regular exam result. Returns {ok, improved}."""
  try:
    existing_results = self.result_repo.get_by_exam(regular_exam_id)
    existing_result_row = next((r for r in existing_results if r['registration_no'] == reg_no), None)
    if not existing_result_row or not existing_result_row.get('result_data'):
      ok = self.result_repo.save(regular_exam_id, reg_no, new_data)
      return {'ok': ok, 'improved': False}
    existing_data = safe_json_loads(existing_result_row['result_data'])
  except Exception:
    ok = self.result_repo.save(regular_exam_id, reg_no, new_data)
    return {'ok': ok, 'improved': False}
  existing_subjects = existing_data.get('subjects', [])
  new_subjects=new_data.get('subjects',[])
  updated_subjects=[]
  existing_by_code={s.get('code','').strip():s for s in existing_subjects}
  any_improved = False
  def get_float_point(val) -> float:
   try:
    return float(val)
   except (ValueError, TypeError):
    return 0.0
  for code,existing_sub in existing_by_code.items():
   matching_new=next((s for s in new_subjects if s.get('code','').strip()==code),None)
   if matching_new:
    try:
     new_point=get_float_point(matching_new.get('point','0'))
     exist_point=get_float_point(existing_sub.get('point','0'))
     if new_point>exist_point:
      existing_sub['grade']=matching_new.get('grade')
      existing_sub['point']=str(matching_new.get('point'))
      existing_sub['status']=matching_new.get('status','PASS')
      existing_sub['improved']=True
      any_improved = True
    except Exception:pass
   updated_subjects.append(existing_sub)
  for new_sub in new_subjects:
   code=new_sub.get('code','').strip()
   if code not in existing_by_code:updated_subjects.append(new_sub)
  existing_data['subjects']=updated_subjects
  new_gpa=self._calculate_gpa(updated_subjects)
  existing_data['calculated_gpa']=new_gpa
  has_fail=any(s.get('status')=='FAIL' or s.get('grade')=='F' for s in updated_subjects)
  existing_data['status']='FAIL' if has_fail else 'PASS'
  ok = self.result_repo.save(regular_exam_id,reg_no,existing_data)
  return {'ok': ok, 'improved': any_improved}
