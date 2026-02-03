#!/usr/bin/env python3
"""Business Logic Services"""
import configparser
from typing import List, Dict
from ducmc_result_scraper import DUCMCResultScraper
from models import ExamRepository, ResultRepository


class ConfigService:
    """Configuration file handler"""
    def __init__(self, config_path: str = 'config.ini'):
        self.config = configparser.ConfigParser()
        try:
            self.config.read(config_path)
        except Exception:
            pass
    
    def get(self, section: str, key: str, fallback: str = '') -> str:
        try:
            return self.config.get(section, key).strip()
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback


class RegistrationService:
    """Registration number handling"""
    @staticmethod
    def load_from_file(file_path: str = 'sample_registrations.txt') -> List[str]:
        try:
            with open(file_path, 'r') as f:
                return [line.strip() for line in f if line.strip()]
        except (FileNotFoundError, PermissionError):
            return []


class ResultService:
    """Result processing with caching"""
    def __init__(self, exam_repo: ExamRepository, result_repo: ResultRepository, config_service: ConfigService):
        self.exam_repo = exam_repo
        self.result_repo = result_repo
        self.config = config_service
    
    def process_exam_results(self, exam_id: str) -> Dict:
        if not exam_id or not exam_id.strip():
            return {'success': False, 'message': 'Invalid exam ID', 'from_cache': False}
        
        exam = self.exam_repo.get_by_exam_id(exam_id)
        if not exam:
            return {'success': False, 'message': 'Exam not found', 'from_cache': False}
        
        cached = self.result_repo.get_by_exam(exam_id)
        if cached:
            return {
                'success': True,
                'results': self.result_repo.format_for_display(cached),
                'from_cache': True,
            }
        
        reg_numbers = RegistrationService.load_from_file()
        if not reg_numbers:
            return {'success': False, 'message': 'No registration numbers found', 'from_cache': False}
        
        try:
            scraper = DUCMCResultScraper(headless=True)
            results = []
            for reg in reg_numbers:
                if not reg:
                    continue
                try:
                    data = scraper.get_result(
                        reg,
                        exam.get('program_id', '14'),
                        exam.get('exam_id', exam_id),
                        exam.get('session_id', '23')
                    )
                    if data and self.result_repo.save(exam_id, reg, data):
                        results.append(data)
                except Exception:
                    continue
            
            scraper.close()
            final = self.result_repo.get_by_exam(exam_id)
            return {
                'success': bool(results),
                'results': self.result_repo.format_for_display(final) if results else [],
                'from_cache': False,
                'message': f'{len(results)} results scraped successfully' if results else 'No results found'
            }
        except Exception as e:
            return {'success': False, 'message': f'Scraping error: {str(e)}', 'from_cache': False}
