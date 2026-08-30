from abc import ABC, abstractmethod
from typing import Any, Dict, List, Protocol


class LoggerPort(ABC):
    @abstractmethod
    def log_truncated(self, component: str, message: str, **kwargs) -> None:
        ...

    @abstractmethod
    def log_full(self, component: str, message: str, payload: Any = None) -> None:
        ...


class GameClientPort(ABC):
    @abstractmethod
    def login(self) -> Dict:
        ...

    @abstractmethod
    def execute_raw_action(self, events: List[Dict]) -> Dict:
        ...


class FarmRepositoryPort(ABC):
    @abstractmethod
    def load(self, user_id: str) -> Dict:
        ...

    @abstractmethod
    def save(self, user_id: str, state: Dict) -> None:
        ...

    @abstractmethod
    def load_state(self, raw: Dict) -> Any:
        ...