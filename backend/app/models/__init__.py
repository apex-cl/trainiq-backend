# Alle Models hier importieren damit SQLAlchemy sie registriert
from app.models.user import User
from app.models.training import UserGoal, TrainingPlan
from app.models.metrics import HealthMetric, DailyWellbeing, RecoveryScore
from app.models.nutrition import NutritionLog
from app.models.conversation import Conversation
from app.models.watch import WatchConnection
from app.models.ai_memory import AIMemory, PasswordResetToken

__all__ = [
    "User",
    "UserGoal",
    "HealthMetric",
    "DailyWellbeing",
    "RecoveryScore",
    "TrainingPlan",
    "NutritionLog",
    "Conversation",
    "WatchConnection",
    "AIMemory",
    "PasswordResetToken",
]
