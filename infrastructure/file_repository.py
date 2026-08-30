import json
import os
from typing import Dict, Any

from core.ports import FarmRepositoryPort
from domain.models import (
    FarmState,
    Storage,
    GameObject,
    Factory,
    GreenhouseFactory,
    Greenhouse,
    Animal,
    House,
    RemoteLocation,
)


class FileFarmRepository(FarmRepositoryPort):
    """Stores raw profile JSON on disk and parses it into FarmState."""

    def __init__(self, base_path: str = "data"):
        self.base_path = base_path
        os.makedirs(base_path, exist_ok=True)

    def _file_path(self, user_id: str) -> str:
        return os.path.join(self.base_path, f"{user_id}_profile.json")

    def load(self, user_id: str) -> Dict:
        path = self._file_path(user_id)
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, user_id: str, state: Dict) -> None:
        path = self._file_path(user_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=4, ensure_ascii=False)

    def load_state(self, raw: Dict) -> FarmState:
        """Parse raw profile JSON into a FarmState domain object."""
        state = FarmState()

        state_data = raw.get("state", {})
        params = raw.get("params", {})
        event = params.get("event", {})
        main_location = event.get("location", {})

        # Player fields
        state.bank = state_data.get("bank", {})
        if "bonusItem" in state.bank:
            state.bank["bonusItem"]["item"] = self._clean_name(state.bank["bonusItem"].get("item", ""))
        if "lastBonusItem" in state.bank:
            state.bank["lastBonusItem"]["item"] = self._clean_name(state.bank["lastBonusItem"].get("item", ""))

        state.level = int(state_data.get("level", 0))
        state.game_money = int(state_data.get("gameMoney", 0))
        state.cash_money = int(state_data.get("cashMoney", 0))
        state.silver_money = int(state_data.get("silverMoney", 0))
        state.energy = int(state_data.get("energy", 0))
        state.kerosene = int(state_data.get("kerosene", 0))
        state.collection_items = state_data.get("collectionItems", {})
        state.work_places = state_data.get("workPlaces", [])
        state.partners = state_data.get("partners", {})
        state.help_points = int(state_data.get("help", 0))

        # Main storage
        state.main_storage = Storage(
            raw_items=main_location.get("storageItems", []),
            raw_objects=main_location.get("storageGameObjects", []),
        )

        # Game objects
        for obj in event.get("gameObjects", []):
            obj_id = obj.get("id")
            if obj_id is None:
                continue
            obj_id = int(obj_id)
            obj_type = obj.get("type")

            if "greenhouse" in obj:
                typed_obj = Greenhouse.from_dict(obj)
                state.greenhouses.append(typed_obj)
                state.all_objects[obj_id] = typed_obj
            elif obj_type == "factory":
                if "tepl" in obj.get("item", "").lower():
                    typed_obj = GreenhouseFactory.from_dict(obj)
                    state.greenhouse_factories.append(typed_obj)
                    state.factories.append(typed_obj)  # also include in general factories list
                else:
                    typed_obj = Factory.from_dict(obj)
                    state.factories.append(typed_obj)
                state.all_objects[obj_id] = typed_obj
            elif obj_type == "house":
                typed_obj = House.from_dict(obj)
                state.houses.append(typed_obj)
                state.all_objects[obj_id] = typed_obj
            elif obj_type in ["plumed", "hoofed", "breed"]:
                typed_obj = Animal.from_dict(obj)
                state.animals.append(typed_obj)
                state.all_objects[obj_id] = typed_obj
            else:
                typed_obj = GameObject.from_dict(obj)
                state.all_objects[obj_id] = typed_obj

        # Remote locations
        for loc in event.get("locationInfos", []):
            loc_id = loc.get("locationId")
            if loc_id:
                state.locations[loc_id] = RemoteLocation.from_dict(loc_id, loc)

        return state

    @staticmethod
    def _clean_name(name: str) -> str:
        """Remove leading '@' from item names."""
        return name[1:] if name.startswith("@") else name