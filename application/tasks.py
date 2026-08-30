from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

from application.services import FarmService
from domain.models import GreenhouseFactory


class Task(ABC):
    """A single unit of automation."""

    @abstractmethod
    def execute(self, session) -> None:
        ...


class HarvestGreenhousesTask(Task):
    def execute(self, session) -> None:
        mature = [gh for gh in session.state.greenhouses if gh.is_ready_to_harvest]
        if mature:
            session.farm_service.harvest_greenhouses(
                session.game_client, session.state, mature
            )


class DigGreenhousesTask(Task):
    def execute(self, session) -> None:
        slag = [gh for gh in session.state.greenhouses if gh.needs_weeding]
        if slag:
            session.farm_service.dig_greenhouses(
                session.game_client, session.state, slag
            )


class PlantGreenhousesTask(Task):
    def __init__(self, crop_id: str):
        self.crop_id = crop_id

    def execute(self, session) -> None:
        empty = [gh for gh in session.state.greenhouses if gh.is_empty]
        if empty:
            available_energy = session.state.energy
            if available_energy < len(empty):
                empty = empty[:available_energy]
            if empty:
                session.farm_service.plant_greenhouses(
                    session.game_client, session.state, empty, self.crop_id
                )


class CollectFactoriesTask(Task):
    def __init__(self, target_type: str = "all", repeat_on_pick: bool = False):
        self.target_type = target_type
        self.repeat_on_pick = repeat_on_pick

    def execute(self, session) -> None:
        factories = session.state.factories
        if self.target_type != "all":
            if self.target_type == "all-no-greenhouses":
                factories = [f for f in factories if not isinstance(f, GreenhouseFactory)]
            else:
                factories = [f for f in factories if self.target_type in f.item_proto.lower()]
        ready = [f for f in factories if f.has_product_ready]
        if ready:
            session.farm_service.collect_from_factories(
                session.game_client, session.state, ready, repeat_on_pick=self.repeat_on_pick
            )


class CollectGreenhouseFactoriesTask(Task):
    def __init__(self, target_type: str = "all", repeat_on_pick: bool = False, consumable_energy_item: Optional[Dict] = None):
        self.target_type = target_type
        self.repeat_on_pick = repeat_on_pick
        self.consumable_energy_item = consumable_energy_item

    def execute(self, session) -> None:
        factories = session.state.greenhouse_factories
        if self.target_type != "all":
            factories = [f for f in factories if self.target_type in f.item_proto.lower()]
        ready = [f for f in factories if f.has_product_ready]
        if not ready:
            return
        if not self.repeat_on_pick:
            session.farm_service.collect_from_factories(
                session.game_client, session.state, ready, repeat_on_pick=False
            )
            return
        # Process in batches limited by energy
        remaining = list(ready)
        while remaining:
            if self.consumable_energy_item and session.state.energy < session.state.max_energy and session.state.energy < len(remaining):
                session.farm_service.consume_energy_items(
                    session.game_client, session.state,
                    self.consumable_energy_item["item_id"],
                    self.consumable_energy_item["energy_per_item"]
                )
            batch = remaining[:session.state.energy]
            if not batch:
                break
            session.farm_service.collect_from_factories(
                session.game_client, session.state, batch, repeat_on_pick=True
            )
            remaining = remaining[len(batch):]


class CraftFactoryTask(Task):
    def __init__(self, recipe_id: str, target_type: str = "all", specific_obj_id: Optional[int] = None):
        self.recipe_id = recipe_id
        self.target_type = target_type
        self.specific_obj_id = specific_obj_id

    def execute(self, session) -> None:
        factories = session.state.factories
        if self.specific_obj_id is not None:
            factories = [f for f in factories if f.id == self.specific_obj_id]
        elif self.target_type != "all":
            factories = [f for f in factories if self.target_type in f.item_proto.lower()]
        if factories:
            session.farm_service.start_craft_mass(
                session.game_client, session.state, factories, self.recipe_id
            )


class ConsumeEnergyItemsTask(Task):
    def __init__(self, item_id: str, energy_per_item: int, amount: Optional[int] = None):
        self.item_id = item_id
        self.energy_per_item = energy_per_item
        self.amount = amount

    def execute(self, session) -> None:
        session.farm_service.consume_energy_items(
            session.game_client, session.state,
            self.item_id, self.energy_per_item, self.amount
        )


class FertilizeGreenhouseFactoriesTask(Task):
    def __init__(self, target_type: str = "all", fertilizer_item_id: Optional[str] = None):
        self.target_type = target_type
        self.fertilizer_item_id = fertilizer_item_id

    def execute(self, session) -> None:
        factories = session.state.greenhouse_factories
        if self.target_type != "all":
            factories = [f for f in factories if self.target_type in f.item_proto.lower()]
        not_fertilized = [f for f in factories if not f.current_craft_fertilized]
        if not_fertilized:
            session.farm_service.fertilize_greenhouse_factories(
                session.game_client, session.state, not_fertilized, self.fertilizer_item_id
            )