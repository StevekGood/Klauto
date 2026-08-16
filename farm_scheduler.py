import asyncio
import uuid
from abc import ABC, abstractmethod
from farm_data_manager import FarmDataManager
from farm_action_manager import FarmActionManager

class SchedulerTask(ABC):
    """Abstract base class for all decoupled modular automation tasks."""
    def __init__(self, target_type: str = "all"):
        self.target_type = target_type  # "all", "smithy", "hoofed", etc.

    @abstractmethod
    def execute(self, data: FarmDataManager, actions: FarmActionManager):
        """Polymorphic execution entrypoint for individual strategic actions."""
        pass


class HarvestGreenhousesTask(SchedulerTask):
    def execute(self, data: FarmDataManager, actions: FarmActionManager):
        mature = [gh for gh in data.greenhouses if gh.is_ready_to_harvest]
        if mature: actions.harvest_greenhouses_mass(mature)

class DigGreenhousesTask(SchedulerTask):
    def execute(self, data: FarmDataManager, actions: FarmActionManager):
        slag = [gh for gh in data.greenhouses if gh.needs_weeding]
        if slag: actions.dig_greenhouses_mass(slag)

class PlantGreenhousesTask(SchedulerTask):
    def __init__(self, recipe_id: str):
        super().__init__()
        self.recipe_id = recipe_id

    def execute(self, data: FarmDataManager, actions: FarmActionManager):
        empty = [gh for gh in data.greenhouses if gh.is_empty]
        if empty:
            if data.energy < len(empty):
                empty = empty[:data.energy]
            if empty: actions.plant_greenhouses_mass(empty, self.recipe_id)


class CollectFactoriesTask(SchedulerTask):
    def __init__(self, target_type: str = "all", repeat_on_pick: bool = False):
        super().__init__(target_type)
        self.repeat_on_pick = repeat_on_pick  # If True, puts the resource back to craft automatically

    def execute(self, data: FarmDataManager, actions: FarmActionManager):
        factories = data.factories
        if self.target_type != "all":
            factories = [f for f in factories if self.target_type in f.item_proto.lower()]
        
        ready_factories = [f for f in factories if f.has_product_ready]
        if ready_factories: 
            actions.collect_from_factories_mass(ready_factories, repeat_on_pick=self.repeat_on_pick)


class CraftFactoryTask(SchedulerTask):
    """Explicitly launches production for either a specific factory instance ID or a group category."""
    def __init__(self, recipe_id: str, target_type: str = "all", specific_obj_id: int = None):
        super().__init__(target_type)
        self.recipe_id = recipe_id
        self.specific_obj_id = specific_obj_id

    def execute(self, data: FarmDataManager, actions: FarmActionManager):
        factories = data.factories
        if self.specific_obj_id is not None:
            factories = [f for f in factories if f.id == self.specific_obj_id]
        elif self.target_type != "all":
            factories = [f for f in factories if self.target_type in f.item_proto.lower()]
            
        if factories:
            actions.start_craft_in_factories_mass(factories, self.recipe_id)
            

class CollectAnimalsTask(SchedulerTask):
    def execute(self, data: FarmDataManager, actions: FarmActionManager):
        animals = data.animals
        if self.target_type != "all":
            animals = [a for a in animals if a.type == self.target_type]
            
        ready_animals = [a for a in animals if a.has_product_ready]
        if ready_animals: actions.collect_from_animals_mass(ready_animals)


class AutomationPlan:
    """A user-configured collection of tasks to repeat or run sequentially."""
    def __init__(self, name: str):
        self.id = str(uuid.uuid4())[:8]
        self.name = name
        self.instructions: list[SchedulerTask] = []
        self.interval_seconds = 0  # 0 = once, >0 = periodic loop interval
        self.is_active = False


class FarmTaskScheduler:
    def __init__(self, client, data_manager: FarmDataManager, action_manager: FarmActionManager):
        self.client = client
        self.data = data_manager
        self.actions = action_manager
        self.plans: dict[str, AutomationPlan] = {}
        self.execution_lock = asyncio.Lock()

    def create_plan(self, name: str) -> AutomationPlan:
        plan = AutomationPlan(name)
        self.plans[plan.id] = plan
        return plan

    def delete_plan(self, plan_id: str):
        if plan_id in self.plans:
            self.plans[plan_id].is_active = False
            del self.plans[plan_id]

    async def start_plan_loop(self, plan_id: str, delay_seconds: int = 0):
        plan = self.plans.get(plan_id)
        if not plan: return
        
        plan.is_active = True
        print(f"[Scheduler]: Plan '{plan.name}' armed. Initial delay: {delay_seconds}s.")
        
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
            
        while plan.is_active:
            await self._execute_plan_safely(plan)
            
            if plan.interval_seconds > 0 and plan.is_active:
                print(f"[Scheduler]: Plan '{plan.name}' sleeping for: {plan.interval_seconds}s.")
                await asyncio.sleep(plan.interval_seconds)
            else:
                plan.is_active = False

    async def _execute_plan_safely(self, plan: AutomationPlan):
        """Acquires lock, forces a fresh logging handshake refresh, and runs commands polymorphically."""
        async with self.execution_lock:
            print(f"\n[Scheduler MUTEX LOCK ACQUIRED]: Executing Plan Sequence -> '{plan.name}'")
            
            loop = asyncio.get_event_loop()
            print("[Scheduler]: Requesting fresh authentication snapshot for maximum session transparency...")
            fresh_profile = await loop.run_in_executor(None, self.client.login)
            if "error" in fresh_profile:
                print(f"[Scheduler ERROR]: Re-auth failed during plan iteration. Skipping execution.")
                return
                
            await loop.run_in_executor(None, self.data.save_and_parse, fresh_profile)
            print(f"[Scheduler Sync]: Current level: {self.data.level} | Fresh active energy: {self.data.energy}")
            
            for task in plan.instructions:
                if not plan.is_active:
                    print(f"[Scheduler]: Plan '{plan.name}' terminated prematurely.")
                    break
                    
                print(f"[Scheduler]: Dispatching Polymorphic Class Task -> {task.__class__.__name__}")
                await loop.run_in_executor(None, task.execute, self.data, self.actions)
                
                # Inter-transaction signature guard interval delay
                await asyncio.sleep(3.0)
                
            print(f"[Scheduler MUTEX LOCK RELEASED]: Plan Sequence completed -> '{plan.name}'\n")