"""MultiBot365 confirmation worker companion (human APPROVE/REJECT gate).

Never calls Place Bet / wager submit. Separate from phone coordinator DB.
"""

from .schema import DecisionStatus, ReadyState, DEFAULT_STALE_SECONDS
from .worker import ConfirmationWorker

__all__ = [
    "ConfirmationWorker",
    "DecisionStatus",
    "ReadyState",
    "DEFAULT_STALE_SECONDS",
]

__version__ = "0.1.0"
