from app.models.models import Database, ExamRepository, ResultRepository, LoginLogRepository, MergeLogRepository, RetakeMappingRepository
from app.services.services import ResultService, ConfigService

db = Database()
db.initialize()

config_service = ConfigService()

exam_repo = ExamRepository(db)
result_repo = ResultRepository(db)
login_log_repo = LoginLogRepository(db)
merge_log_repo = MergeLogRepository(db)
retake_mapping_repo = RetakeMappingRepository(db)

result_service = ResultService(exam_repo, result_repo, config_service, merge_log_repo, retake_mapping_repo)

# Global cache for API results
api_results_cache = {}
