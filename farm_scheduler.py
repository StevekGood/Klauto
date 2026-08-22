import asyncio
import uuid
import time
from abc import ABC, abstractmethod
from farm_models import GreenhouseFactory
from farm_action_manager import FarmDataManager
from farm_action_manager import FarmActionManager
from klone_game_client import KlondikeGameClient

class SchedulerTask(ABC):
    def __init__(self, target_type: str = "all"):
        self.target_type = target_type

    @abstractmethod
    def execute(self, data: FarmDataManager, actions: FarmActionManager):
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
        self.repeat_on_pick = repeat_on_pick

    def execute(self, data: FarmDataManager, actions: FarmActionManager):
        factories = data.factories
        if self.target_type != "all":
            if self.target_type == "all-no-greenhouses":
                factories = [f for f in factories if not isinstance(f, GreenhouseFactory)]
            else:
                factories = [f for f in factories if self.target_type in f.item_proto.lower()]
        
        ready_factories = [f for f in factories if f.has_product_ready]
        if ready_factories: 
            actions.collect_from_factories_mass(ready_factories, repeat_on_pick=self.repeat_on_pick)


class CollectGreenhouseFactoriesTask(SchedulerTask):
    def __init__(self, target_type: str = "all", repeat_on_pick: bool = False, consumable_energy_item: dict = None):
            super().__init__(target_type)
            self.repeat_on_pick = repeat_on_pick
            self.consumable_energy_item = consumable_energy_item
    
    def execute(self, data: FarmDataManager, actions: FarmActionManager):
        greenhouse_factories = data.greenhouse_factories
        if self.target_type != "all":
            greenhouse_factories = [f for f in greenhouse_factories if self.target_type in f.item_proto.lower()]
        
        ready_greenhouse_factories = [f for f in greenhouse_factories if f.has_product_ready]
        if ready_greenhouse_factories: 
            if not self.repeat_on_pick:
                actions.collect_from_factories_mass(ready_greenhouse_factories, repeat_on_pick=False)
            else:
                ready_count = len(ready_greenhouse_factories)
                batch_index = 0
                while ready_count > 0:
                    batch_index += 1
                    if batch_index > 1:
                        time.sleep(3)
                    if self.consumable_energy_item and data.energy < ready_count and data.energy < data.max_energy:
                        actions.consume_energy_items(self.consumable_energy_item["item_id"], self.consumable_energy_item["energy_per_item"])
                    current_energy = data.energy
                    actions.collect_from_factories_mass(ready_greenhouse_factories[:current_energy], repeat_on_pick=True)
                    del ready_greenhouse_factories[:current_energy]
                    ready_count = len(ready_greenhouse_factories)
                    if batch_index > 20:
                        return
                    

class CraftFactoryTask(SchedulerTask):
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


class ConsumeEnergyItemsTask(SchedulerTask):
    def __init__(self, item_id: str, energy_per_item: int, amount_to_eat: int = None):
        super().__init__()
        self.item_id = item_id
        self.energy_per_item = energy_per_item
        self.amount_to_eat = amount_to_eat

    def execute(self, data: FarmDataManager, actions: FarmActionManager):
        actions.consume_energy_items(self.item_id, self.energy_per_item, self.amount_to_eat)


class FertilizeGreenhouseFactoriesTask(SchedulerTask):
    def __init__(self, target_type = "all", fertilizer_item_id: str = None):
        super().__init__(target_type)
        self.fertilizer_item_id = fertilizer_item_id

    def execute(self, data, actions):
        greenhouse_factories = data.greenhouse_factories
        if self.target_type != "all":
            greenhouse_factories = [f for f in greenhouse_factories if self.target_type in f.item_proto.lower()]
        
        not_fertilized_factories = [f for f in greenhouse_factories if not f.current_craft_fertilized]
        if not_fertilized_factories: 
            actions.fertilize_greenhouse_factories_mass(not_fertilized_factories, fertilize_item_id=self.fertilizer_item_id)
        

class AutomationPlan:
    def __init__(self, name: str):
        self.id = str(uuid.uuid4())[:8]
        self.name = name
        self.instructions: list[SchedulerTask] = []
        self.interval_seconds = 0
        self.is_active = False


class UserSession:
    def __init__(self, user_id: str, auth_key: str, vk_metadata: dict = None):
        self.user_id = user_id
        self.client = KlondikeGameClient(user_id, auth_key, vk_metadata)
        self.data = FarmDataManager()
        self.actions = FarmActionManager(self.client, self.data)
        self.plans: dict[str, AutomationPlan] = {}
        self.lock = asyncio.Lock()

    def create_plan(self, name: str) -> AutomationPlan:
        plan = AutomationPlan(name)
        self.plans[plan.id] = plan
        return plan


class FarmTaskScheduler:
    def __init__(self):
        self.sessions: dict[str, UserSession] = {}
        self.network_semaphore = asyncio.Semaphore(5)

    def register_user(self, user_id: str, auth_key: str, vk_metadata: dict = None) -> UserSession:
        if user_id not in self.sessions:
            self.sessions[user_id] = UserSession(user_id, auth_key, vk_metadata)
        else:
            self.sessions[user_id].client.auth_key = auth_key
        return self.sessions[user_id]

    async def start_plan_loop(self, user_id: str, plan_id: str, delay_seconds: int = 0):
        session = self.sessions.get(user_id)
        if not session: return
        
        plan = session.plans.get(plan_id)
        if not plan: return
        
        plan.is_active = True
        print("Scheduler", f"Plan '{plan.name}' armed for User {user_id}. Delay: {delay_seconds}s.")
        
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
            
        while plan.is_active:
            await self._execute_plan_safely(user_id, plan)
            
            if plan.interval_seconds > 0 and plan.is_active:
                await asyncio.sleep(plan.interval_seconds)
            else:
                plan.is_active = False

    async def _execute_plan_safely(self, user_id: str, plan: AutomationPlan):
        session = self.sessions.get(user_id)
        if not session: return

        async with session.lock:
            async with self.network_semaphore:
                print("Scheduler", f"Executing sequence for User {user_id} -> '{plan.name}'")
                loop = asyncio.get_event_loop()
                fresh_profile = await loop.run_in_executor(None, session.client.login)
                if "error" in fresh_profile:
                    print("Scheduler ERROR", f"Re-auth failed for User {user_id}.")
                    return
                    
                await loop.run_in_executor(None, session.data.save_and_parse, fresh_profile)
                for task in plan.instructions:
                    if not plan.is_active: break
                    await loop.run_in_executor(None, task.execute, session.data, session.actions)
                    await asyncio.sleep(3.0)