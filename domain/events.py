from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class GameAction:
    """Represents a low-level event to send."""
    data: Dict


@dataclass
class ActionBatch:
    events: List[Dict]