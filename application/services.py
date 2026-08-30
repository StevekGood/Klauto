from typing import List, Optional, Dict, Any

from core.ports import GameClientPort, LoggerPort
from domain.models import (
    FarmState, Factory, Greenhouse, GreenhouseFactory
)


class FarmService:
    """Business logic for farm operations. Depends only on ports."""

    def __init__(self, logger: LoggerPort):
        self.logger = logger

    def _clean_name(self, name: str) -> str:
        return name[1:] if name.startswith("@") else name

    def _check_materials_available(
        self,
        state: FarmState,
        recipe: Dict,
        reserved: Dict[str, int],
        multiplier: int = 1
    ) -> bool:
        if not recipe or "materials" not in recipe:
            return False
        for req in recipe.get("materials", []):
            raw = req.get("item", "")
            item_id = self._clean_name(raw)
            needed = int(req.get("count", 0)) * multiplier
            if item_id.lower() == "energy":
                available = state.energy - reserved.get("__energy__", 0)
            else:
                available = state.main_storage.get_item_count(item_id) - reserved.get(item_id, 0)
            if available < needed:
                self.logger.log_truncated(
                    "FarmService",
                    "insufficient_materials",
                    item=item_id,
                    needed=needed,
                    available=available
                )
                return False
        return True

    def _reserve_materials(
        self,
        recipe: Dict,
        reserved: Dict[str, int],
        multiplier: int = 1
    ) -> None:
        for req in recipe.get("materials", []):
            raw = req.get("item", "")
            item_id = self._clean_name(raw)
            needed = int(req.get("count", 0)) * multiplier
            if item_id.lower() == "energy":
                reserved["__energy__"] = reserved.get("__energy__", 0) + needed
            else:
                reserved[item_id] = reserved.get(item_id, 0) + needed

    def _apply_response_updates(self, state: FarmState, response: Dict) -> None:
        events = response.get("events", [])
        for evt in events:
            evt_type = evt.get("type")
            evt_action = evt.get("action")
            if evt_type == "pickup" and evt_action == "add":
                for item in evt.get("pickups", []):
                    item_id = self._clean_name(item.get("id") or item.get("type", ""))
                    count = int(item.get("count", 0))
                    if item_id == "xp":
                        state.level = int(item.get("level", state.level))
                        continue
                    state.main_storage.items[item_id] = state.main_storage.items.get(item_id, 0) + count
            if "energy" in evt:
                state.energy = int(evt["energy"])
            if "gameMoney" in evt:
                state.game_money = int(evt["gameMoney"])
            if "cashMoney" in evt:
                state.cash_money = int(evt["cashMoney"])

    def collect_from_factories(
        self,
        client: GameClientPort,
        state: FarmState,
        factories: List[Factory],
        repeat_on_pick: bool = False
    ) -> Dict:
        if not factories:
            return {}

        events = []
        reserved_materials: Dict[str, int] = {}

        for factory in factories:
            # Add pick events for each material (do not aggregate)
            material_count = 0
            for mat in factory.materials:
                if not mat:
                    continue
                raw = mat.get("item", "")
                item_id = self._clean_name(raw)
                count = int(mat.get("count", 1))
                events.append({
                    "type": "item",
                    "action": "pick",
                    "objId": factory.id,
                    "itemId": item_id,
                    "count": count
                })
                material_count += 1

            # Re‑craft if requested
            if repeat_on_pick and material_count > 0:
                if factory.require_workers and not factory.current_craft:
                    self.logger.log_truncated("FarmService", "skip_repeat_inactive_factory", factory_id=factory.id)
                    continue

                if not factory.current_craft:
                    self.logger.log_truncated("FarmService", "skip_repeat_no_recipe", factory_id=factory.id)
                    continue

                # Calculate available slots for crafts
                current_slots = (1 if factory.current_craft else 0) + len(factory.pending_crafts)
                available_slots = max(0, 3 - current_slots)
                if available_slots == 0:
                    self.logger.log_truncated("FarmService", "skip_repeat_queue_full", factory_id=factory.id)
                    continue

                # Number of crafts we can add = min(materials collected, available slots)
                num_crafts = min(material_count, available_slots)

                # Check materials for num_crafts
                if not self._check_materials_available(
                    state, factory.current_craft, reserved_materials, multiplier=num_crafts
                ):
                    self.logger.log_truncated("FarmService", "skip_repeat_missing_resources", factory_id=factory.id)
                    continue

                # Reserve materials for num_crafts
                self._reserve_materials(factory.current_craft, reserved_materials, multiplier=num_crafts)

                recipe_id = factory.repeat_recipe or factory.current_craft.get("id")
                if not recipe_id:
                    continue

                # Add exactly num_crafts craft events
                for _ in range(num_crafts):
                    events.append({
                        "type": "factory",
                        "action": "craft",
                        "objId": factory.id,
                        "itemId": recipe_id,
                        "workers": factory.workers
                    })

        if not events:
            return {}

        self.logger.log_truncated("FarmService", "posting_factory_collection", events_count=len(events))
        response = client.execute_raw_action(events)

        if client.is_error_response(response):
            self.logger.log_full("FarmService", "factory_collection_error", payload=response)
        else:
            for factory in factories:
                factory.materials = []   # collected
            self._apply_response_updates(state, response)
        return response

    def start_craft_mass(
        self,
        client: GameClientPort,
        state: FarmState,
        factories: List[Factory],
        recipe_id: str
    ) -> Dict:
        if not factories:
            return {}

        events = []
        reserved_materials: Dict[str, int] = {}

        for factory in factories:
            if factory.require_workers and not factory.current_craft:
                self.logger.log_truncated("FarmService", "skip_craft_inactive", factory_id=factory.id)
                continue

            if factory.current_craft and not self._check_materials_available(state, factory.current_craft, reserved_materials):
                self.logger.log_truncated("FarmService", "skip_craft_missing_resources", factory_id=factory.id)
                continue

            current_active_slots = 1 if factory.current_craft else 0
            current_active_slots += len(factory.pending_crafts)
            if current_active_slots >= 3:
                self.logger.log_truncated("FarmService", "skip_craft_queue_full", factory_id=factory.id)
                continue

            # Reserve materials after all checks passed
            self._reserve_materials(factory.current_craft, reserved_materials)

            events.append({
                "type": "factory",
                "action": "craft",
                "objId": factory.id,
                "itemId": recipe_id,
                "workers": factory.workers
            })

        if not events:
            self.logger.log_truncated("FarmService", "no_factories_for_craft", recipe=recipe_id)
            return {}

        self.logger.log_truncated("FarmService", "posting_craft_mass", recipe=recipe_id, count=len(events))
        response = client.execute_raw_action(events)
        if client.is_error_response(response):
            self.logger.log_full("FarmService", "craft_mass_error", payload=response)
        else:
            self._apply_response_updates(state, response)
        return response

    def harvest_greenhouses(self, client: GameClientPort, state: FarmState, greenhouses: List[Greenhouse]) -> Dict:
        if not greenhouses:
            return {}
        events = []
        for gh in greenhouses:
            crop_id = gh.item_proto.upper()
            if not crop_id:
                continue
            events.append({
                "type": "item",
                "action": "pick",
                "objId": gh.id,
                "msg": f"FarmWorldContainer.onCompositionGether {crop_id}"
            })
        if not events:
            return {}
        self.logger.log_truncated("FarmService", "posting_harvest", count=len(events))
        response = client.execute_raw_action(events)
        if not client.is_error_response(response):
            for gh in greenhouses:
                gh.type = "Slag"
                gh.item_proto = "SLAG"
                gh.crop_proto = ""
            self._apply_response_updates(state, response)
        else:
            self.logger.log_full("FarmService", "harvest_error", payload=response)
        return response

    def dig_greenhouses(self, client: GameClientPort, state: FarmState, greenhouses: List[Greenhouse]) -> Dict:
        if not greenhouses:
            return {}
        events = [{"type": "item", "action": "dig", "objId": gh.id} for gh in greenhouses]
        self.logger.log_truncated("FarmService", "posting_dig", count=len(events))
        response = client.execute_raw_action(events)
        if not client.is_error_response(response):
            for gh in greenhouses:
                gh.type = "ground"
                gh.item_proto = "GROUND"
            self._apply_response_updates(state, response)
        else:
            self.logger.log_full("FarmService", "dig_error", payload=response)
        return response

    def plant_greenhouses(self, client: GameClientPort, state: FarmState, greenhouses: List[Greenhouse], crop_id: str) -> Dict:
        if not greenhouses:
            return {}
        events = []
        for gh in greenhouses:
            events.append({
                "type": "item",
                "action": "buy",
                "objId": gh.id,
                "itemId": crop_id,
                "x": gh.x,
                "y": gh.y
            })
        self.logger.log_truncated("FarmService", "posting_plant", crop=crop_id, count=len(events))
        response = client.execute_raw_action(events)
        if not client.is_error_response(response):
            for gh in greenhouses:
                gh.type = "plant"
                gh.item_proto = crop_id.upper()
                gh.job_finish_time = 9999999
                state.energy = max(0, state.energy - 1)
            self._apply_response_updates(state, response)
        else:
            self.logger.log_full("FarmService", "plant_error", payload=response)
        return response

    def consume_energy_items(self, client: GameClientPort, state: FarmState, item_id: str, energy_per_item: int, amount: Optional[int] = None) -> Dict:
        if amount is None:
            energy_needed = state.max_energy - state.energy
            if energy_needed <= 0:
                return {}
            amount = (energy_needed + energy_per_item - 1) // energy_per_item
        amount = min(amount, state.main_storage.get_item_count(item_id))
        if amount <= 0:
            return {}
        events = [{"type": "item", "action": "use", "itemId": item_id} for _ in range(amount)]
        self.logger.log_truncated("FarmService", "posting_energy_consumption", item=item_id, count=amount)
        response = client.execute_raw_action(events)
        if not client.is_error_response(response):
            state.energy += amount * energy_per_item
            self._apply_response_updates(state, response)
        else:
            self.logger.log_full("FarmService", "energy_consumption_error", payload=response)
        return response

    def fertilize_greenhouse_factories(self, client: GameClientPort, state: FarmState, factories: List[GreenhouseFactory], fertilize_item_id: Optional[str]) -> Dict:
        if not factories:
            return {}
        events = []
        used = {}
        for factory in factories:
            if factory.current_craft and not factory.current_craft_fertilized:
                fertilizer = fertilize_item_id or factory.repeat_fertilizer
                if fertilizer and state.main_storage.get_item_count(fertilizer) > 0:
                    used[fertilizer] = used.get(fertilizer, 0) + 1
                    events.append({
                        "type": "item",
                        "action": "fertilize",
                        "objId": factory.id,
                        "itemId": fertilizer
                    })
        if not events:
            return {}
        self.logger.log_truncated("FarmService", "posting_fertilization", count=len(events))
        response = client.execute_raw_action(events)
        if not client.is_error_response(response):
            for fert, count in used.items():
                state.main_storage.items[fert] = state.main_storage.items.get(fert, 0) - count
            self._apply_response_updates(state, response)
        else:
            self.logger.log_full("FarmService", "fertilization_error", payload=response)
        return response