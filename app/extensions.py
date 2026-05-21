from app.models.models import Database, ExamRepository, ResultRepository, LoginLogRepository
from app.services.services import ResultService, ConfigService

db = Database()
db.initialize()

config_service = ConfigService()

exam_repo = ExamRepository(db)
result_repo = ResultRepository(db)
login_log_repo = LoginLogRepository(db)

result_service = ResultService(exam_repo, result_repo, config_service)

# Global cache for API results
api_results_cache = {}
