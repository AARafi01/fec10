import configparser
import time
import random
import re
import threading
from typing import List,Dict
from ducmc_result_scraper import DUCMCResultScraper, COURSES_DATA
from models import ExamRepository,ResultRepository
from utils import positional_credit_fallback

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
  try:
   with open(file_path,'r')as f:return[line.strip()for line in f if line.strip()]
  except(FileNotFoundError,PermissionError):return[]


class ResultService:
 def __init__(self,exam_repo:ExamRepository,result_repo:ResultRepository,config_service:ConfigService):
  self.exam_repo=exam_repo
  self.result_repo=result_repo
  self.config=config_service
 def _calculate_gpa(self,subjects:List[Dict])->float:
  total_weighted=0.0
  total_credits=0.0
  for idx,subject in enumerate(subjects):
   code=subject.get('code','').strip()
   grade=subject.get('grade','').strip()
   point_str=subject.get('point','0').strip()
   if grade.upper()=='F' or point_str.upper()=='F' or 'FAIL' in grade.upper():
    point=0.0
   else:
    try:point=float(point_str)
    except(ValueError,TypeError):point=0.0
   credit=COURSES_DATA.get(code)
   if credit is None:
    credit = positional_credit_fallback(idx)
   total_weighted+=credit*point
   total_credits+=credit
  return round(total_weighted/total_credits,2)if total_credits>0 else 0.0

 def _background_process_results(self, exam_id: str, reg_numbers: List[str], exam_data: Dict):
  for reg in reg_numbers:
   if not reg:continue
   try:
    reg_clean = re.sub(r'[^0-9]', '', reg)
    sess_id = exam_data.get('session_id', '23')
    if sess_id == '23' and len(reg_clean) == 3:
     sess_id = '22'
    data=DUCMCResultScraper.get_result_requests(reg,exam_data.get('program_id','14'),exam_data.get('exam_id',exam_id),sess_id)
    if data and 'error' not in data:
     gpa = self._calculate_gpa(data.get('subjects', []))
     data['calculated_gpa'] = gpa
     self.result_repo.save(exam_id,reg,data)
    time.sleep(random.uniform(0.2, 0.5))
   except Exception:continue

 def process_exam_results(self,exam_id:str)->Dict:
  if not exam_id or not exam_id.strip():return{'success':False,'message':'Invalid exam ID','from_cache':False}
  exam=self.exam_repo.get_by_exam_id(exam_id)
  if not exam:return{'success':False,'message':'Exam not found','from_cache':False}
  cached=self.result_repo.get_by_exam(exam_id)
  if cached:return{'success':True,'results':self.result_repo.format_for_display(cached),'from_cache':True,'message':f'Found {len(cached)} cached results'}
  reg_numbers=RegistrationService.load_from_file()
  if not reg_numbers:return{'success':False,'message':'No registration numbers found','from_cache':False}
  
  thread = threading.Thread(target=self._background_process_results, args=(exam_id, reg_numbers, exam))
  thread.daemon = True
  thread.start()
  
  return{'success':True,'results':[],'from_cache':False,'message':f'Started background processing for {len(reg_numbers)} students','total_students':len(reg_numbers),'processed_count':len(reg_numbers)}

 def _background_process_improvements(self, retake_exam_id: str, regular_exam_id: str, reg_numbers: List[str]):
  for reg in reg_numbers:
   if not reg:continue
   try:
    reg_clean = re.sub(r'[^0-9]', '', reg)
    sess_id = '22' if len(reg_clean) == 3 else '23'
    new_data=DUCMCResultScraper.get_result_requests(reg,'14',retake_exam_id,sess_id)
    if new_data and'error'not in new_data:
     self.merge_and_save_improvement(regular_exam_id,reg,new_data)
    time.sleep(random.uniform(0.2, 0.5))
   except Exception:continue
  self.result_repo.mark_improvement_processed(retake_exam_id)

 def process_improvement_results(self,retake_exam_id:str,regular_exam_id:str)->Dict:
  if not retake_exam_id or not regular_exam_id:return{'success':False,'message':'Invalid exam IDs'}
  reg_numbers=RegistrationService.load_from_file()
  if not reg_numbers:return{'success':False,'message':'No registration numbers found'}
  
  thread = threading.Thread(target=self._background_process_improvements, args=(retake_exam_id, regular_exam_id, reg_numbers))
  thread.daemon = True
  thread.start()
  
  return{'success':True,'message':f'Started background Retake/Improvement processing for {len(reg_numbers)} students','total_students':len(reg_numbers),'processed_count':len(reg_numbers)}

 def merge_and_save_improvement(self,regular_exam_id:str,reg_no:str,new_data:Dict)->bool:
  import json
  try:
   existing_results = self.result_repo.get_by_exam(regular_exam_id)
   existing_result_row = next((r for r in existing_results if r['registration_no'] == reg_no), None)
   if not existing_result_row or not existing_result_row.get('result_data'):
    return self.result_repo.save(regular_exam_id,reg_no,new_data)
   existing_data=json.loads(existing_result_row['result_data'])
  except Exception:
   return self.result_repo.save(regular_exam_id,reg_no,new_data)
  existing_subjects=existing_data.get('subjects',[])
  new_subjects=new_data.get('subjects',[])
  updated_subjects=[]
  existing_by_code={s.get('code','').strip():s for s in existing_subjects}
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
  return self.result_repo.save(regular_exam_id,reg_no,existing_data)
