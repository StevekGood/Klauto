import json
import os
from farm_models import GameObject, House, Factory, Greenhouse, Animal, Storage, RemoteLocation

class FarmDataManager:
    """Central processing unit for local farm states with specialized tracking arrays."""
    
    def __init__(self, cache_file: str = "profile_data.json"):
        self.cache_file = cache_file
        
        # Core Player state values
        self.bank = {}
        self.level = 0
        self.game_money = 0
        self.cash_money = 0
        self.silver_money = 0
        self.energy = 0
        self.kerosene = 0
        self.collection_items = {}
        self.work_places = []
        self.partners = {}
        self.help_points = 0
        
        # Primary home base Storage entity class
        self.main_storage = Storage()
        
        # Segregated tracking lists for OOP manipulation
        self.all_game_objects = {}  # Dict keyed by active int IDs
        self.factories = []         # List containing Factory model objects
        self.greenhouses = []       # List containing Greenhouse model objects
        self.animals = []           # List containing Animal model objects
        self.houses = []            # List containing House model objects (Added tracker)
        
        # Remote mapped islands territories (keyed by locationId)
        self.locations = {}

    def _clean_name(self, name: str) -> str:
        if name and name.startswith("@"):
            return name[1:]
        return name

    def load_from_cache(self) -> bool:
        """Hydrates data maps using local JSON dump execution."""
        if not os.path.exists(self.cache_file):
            print(f"[DataManager ERROR]: Cache file '{self.cache_file}' missing.")
            return False
            
        with open(self.cache_file, "r", encoding="utf-8") as f:
            raw_json = json.load(f)
            
        self.parse_full_state(raw_json)
        return True

    def save_and_parse(self, fresh_json: dict):
        """Flushes an inline web payload directly into the pipeline parser."""
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(fresh_json, f, indent=4, ensure_ascii=False)
        self.parse_full_state(fresh_json)

    def parse_full_state(self, root_json: dict):
        """Builds specialized object schemas out of the primary runtime network tree."""
        print("[DataManager]: Launching full architecture data processing tree...")
        
        state = root_json.get("state", {})
        
        # Handle account profiles
        self.bank = state.get("bank", {})
        if "bonusItem" in self.bank:
            self.bank["bonusItem"]["item"] = self._clean_name(self.bank["bonusItem"].get("item", ""))
        if "lastBonusItem" in self.bank:
            self.bank["lastBonusItem"]["item"] = self._clean_name(self.bank["lastBonusItem"].get("item", ""))

        self.level = int(state.get("level", 0))
        self.game_money = int(state.get("gameMoney", 0))
        self.cash_money = int(state.get("cashMoney", 0))
        self.silver_money = int(state.get("silverMoney", 0))
        self.energy = int(state.get("energy", 0))
        self.kerosene = int(state.get("kerosene", 0))
        self.collection_items = state.get("collectionItems", {})
        self.work_places = state.get("workPlaces", [])
        self.partners = state.get("partners", {})
        self.help_points = int(state.get("help", 0))

        # Root navigational paths 
        params = root_json.get("params", {})
        event = params.get("event", {})
        main_location = event.get("location", {})
        
        # 1. Instantiate the dynamic base home Storage class
        self.main_storage = Storage(
            raw_items=main_location.get("storageItems", []),
            raw_objects=main_location.get("storageGameObjects", [])
        )

        # 2. Rebuild clean collections maps
        self.all_game_objects.clear()
        self.factories.clear()
        self.greenhouses.clear()
        self.animals.clear()
        self.houses.clear()

        for obj in event.get("gameObjects", []):
            obj_id = obj.get("id")
            if obj_id is not None:
                obj_id = int(obj_id)
                obj_type = obj.get("type")
                
                # STRICT STRUCTURAL FILTERING LOGIC
                if "greenhouse" in obj:
                    typed_obj = Greenhouse(obj)
                    self.greenhouses.append(typed_obj)
                elif obj_type == "factory":
                    typed_obj = Factory(obj)
                    self.factories.append(typed_obj)
                elif obj_type == "house":
                    typed_obj = House(obj)
                    self.houses.append(typed_obj)
                elif obj_type in ["plumed", "hoofed"]:
                    typed_obj = Animal(obj)
                    self.animals.append(typed_obj)
                else:
                    typed_obj = GameObject(obj)
                    
                self.all_game_objects[obj_id] = typed_obj

        # 3. Populate Remote Lands map locations
        self.locations.clear()
        for loc in event.get("locationInfos", []):
            loc_id = loc.get("locationId")
            if loc_id:
                self.locations[loc_id] = RemoteLocation(loc_id, loc)
                
        print(f"[DataManager SUCCESS]: Mapped {len(self.all_game_objects)} entities. "
              f"Factories: {len(self.factories)}, Greenhouses: {len(self.greenhouses)}, "
              f"Animals: {len(self.animals)}, Houses: {len(self.houses)}, Remote storage docks: {len(self.locations)}")

    def update_from_server_response(self, response: dict):
        """Applies explicit mutation updates directly into monitored runtime values."""
        events = response.get("events", [])
        for evt in events:
            evt_type = evt.get("type")
            evt_action = evt.get("action")
            
            if evt_type == "pickup" and evt_action == "add":
                for item in evt.get("pickups", []):
                    item_id = self._clean_name(item.get("id") or item.get("type", ""))
                    count = int(item.get("count", 0))
                    
                    if item_id == "xp":
                        self.level = int(item.get("level", self.level))
                        continue
                        
                    self.main_storage.items[item_id] = self.main_storage.items.get(item_id, 0) + count
            
            if "energy" in evt:
                self.energy = int(evt["energy"])
            if "gameMoney" in evt:
                self.game_money = int(evt["gameMoney"])
            if "cashMoney" in evt:
                self.cash_money = int(evt["cashMoney"])
                
        print(f"[DataManager UPDATE]: Live synchronized updates. Energy: {self.energy}")
