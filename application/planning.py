import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core.ports import GameClientPort, LoggerPort, FarmRepositoryPort
from domain.models import FarmState
from application.services import FarmService
from application.tasks import Task


@dataclass
class Plan:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    tasks: List[Task] = field(default_factory=list)
    interval_seconds: int = 0
    is_active: bool = False


@dataclass
class UserSession:
    user_id: str
    game_client: GameClientPort
    repository: FarmRepositoryPort
    logger: LoggerPort
    farm_service: FarmService
    state: FarmState = None          # will be populated after login
    plans: Dict[str, Plan] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def create_plan(self, name: str) -> Plan:
        plan = Plan(name=name)
        self.plans[plan.id] = plan
        return plan


class PlanRunner:
    """Schedules and runs plans for all users concurrently, with per‑user serialization."""

    def __init__(self, logger: LoggerPort, network_semaphore: asyncio.Semaphore):
        self.logger = logger
        self.network_semaphore = network_semaphore
        self.sessions: Dict[str, UserSession] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}

    def register_user(self, user_id: str, session: UserSession) -> None:
        self.sessions[user_id] = session

    async def start_plan(self, user_id: str, plan_id: str, delay_seconds: int = 0) -> None:
        session = self.sessions.get(user_id)
        if not session:
            return
        plan = session.plans.get(plan_id)
        if not plan or plan.is_active:
            return

        plan.is_active = True
        self.logger.log_truncated("PlanRunner", "plan_started", user=user_id, plan=plan.name)

        task = asyncio.create_task(self._run_loop(user_id, plan_id))
        self._running_tasks[plan_id] = task

    async def stop_plan(self, user_id: str, plan_id: str) -> None:
        session = self.sessions.get(user_id)
        if not session:
            return
        plan = session.plans.get(plan_id)
        if plan and plan.is_active:
            plan.is_active = False
            self.logger.log_truncated("PlanRunner", "plan_stopped", user=user_id, plan=plan.name)
            task = self._running_tasks.get(plan_id)
            if task:
                task.cancel()
                del self._running_tasks[plan_id]

    async def _run_loop(self, user_id: str, plan_id: str) -> None:
        session = self.sessions.get(user_id)
        plan = session.plans.get(plan_id)
        if not session or not plan:
            return

        while plan.is_active:
            await self._execute_plan_once(user_id, plan)
            if plan.interval_seconds > 0 and plan.is_active:
                await asyncio.sleep(plan.interval_seconds)
            else:
                break

        plan.is_active = False

    async def _execute_plan_once(self, user_id: str, plan: Plan) -> None:
        session = self.sessions.get(user_id)
        if not session:
            return

        async with session.lock:
            async with self.network_semaphore:
                self.logger.log_truncated("PlanRunner", "executing_plan", user=user_id, plan=plan.name)
                loop = asyncio.get_event_loop()

                # 1. Login and refresh state
                try:
                    profile = await loop.run_in_executor(None, session.game_client.login)
                except Exception as e:
                    self.logger.log_truncated("PlanRunner", "login_exception", user=user_id, error=str(e))
                    return

                if "error" in profile:
                    self.logger.log_truncated("PlanRunner", "login_failed", user=user_id)
                    return

                # 2. Save raw profile to disk
                try:
                    await loop.run_in_executor(None, session.repository.save, user_id, profile)
                except Exception as e:
                    self.logger.log_truncated("PlanRunner", "save_exception", user=user_id, error=str(e))
                    return

                # 3. Parse into domain state
                try:
                    session.state = session.repository.load_state(profile)
                except Exception as e:
                    self.logger.log_truncated("PlanRunner", "parse_exception", user=user_id, error=str(e))
                    return

                # 4. Execute tasks sequentially
                for task in plan.tasks:
                    if not plan.is_active:
                        break
                    try:
                        await loop.run_in_executor(None, task.execute, session)
                    except Exception as e:
                        self.logger.log_truncated("PlanRunner", "task_error", user=user_id, plan=plan.name, error=str(e))
                    await asyncio.sleep(3.0)