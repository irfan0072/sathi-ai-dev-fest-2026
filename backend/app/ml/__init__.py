"""ML namespace providing aliases to app.models."""

from app.models.agent_model import AgentAnomalyDetector
from app.models.assisted_model import AssistedUserClassifier
from app.models.baselines import AgentAnomalyRuleBaseline, AssistedUserRuleBaseline
from app.models.features import extract_agent_features, extract_user_features

__all__ = [
    "AgentAnomalyDetector",
    "AgentAnomalyRuleBaseline",
    "AssistedUserClassifier",
    "AssistedUserRuleBaseline",
    "extract_agent_features",
    "extract_user_features",
]
