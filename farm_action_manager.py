from klone_game_client import KlondikeGameClient
from farm_data_manager import FarmDataManager
from farm_models import Factory, Animal, Greenhouse, GreenhouseFactory

class FarmActionManager:
    """Executes mass game operations using arrays of high-level OOP farm models."""
    
    def __init__(self, client: KlondikeGameClient, data_manager: FarmDataManager):
        self.client = client
        self.data_manager = data_manager

    def _has_enough_materials_for_craft(self, craft_recipe: dict) -> bool:
        """Internal helper to verify if the main storage contains enough items to satisfy the recipe cost."""
        if not craft_recipe or "materials" not in craft_recipe:
            print(f"[ActionManager Resource Check]: No recipe or materials: {craft_recipe}")
            return False
            
        recipe_materials = craft_recipe.get("materials", [])
        for req in recipe_materials:
            raw_item = req.get("item", "")
            item_id = raw_item[1:] if raw_item.startswith("@") else raw_item

            required_count = int(req.get("count", 0))
            available_count = self.data_manager.main_storage.get_item_count(item_id) if not str.lower(item_id) == "energy" else self.data_manager.energy
            if available_count < required_count:
                print(f"[ActionManager Resource Check]: Insufficient items for {item_id}! Need: {required_count}, Has: {available_count}")
                return False
        return True

    def collect_from_factories_mass(self, factories_list: list[Factory], repeat_on_pick: bool = False) -> dict:
        """Collects ALL available items from factories and optionally restarts production based on current_craft validation."""
        if not factories_list: return {}
        events = []
        
        for factory in factories_list:
            for mat in factory.materials:
                raw_item = mat.get("item", "")
                item_id = raw_item[1:] if raw_item.startswith("@") else raw_item
                if item_id.startswith("U_"):
                    item_id = item_id[2:]
                    
                count = int(mat.get("count", 1))
                events.append({
                    "type": "item",
                    "action": "pick",
                    "objId": factory.id,
                    "itemId": item_id,
                    "count": count
                })
            
            if repeat_on_pick:
                if factory.require_workers and not factory.current_craft:
                    print(f"[ActionManager]: Auto-repeat skipped for factory ID {factory.id} - Factory is inactive.")
                    continue
                    
                if factory.current_craft and not self._has_enough_materials_for_craft(factory.current_craft):
                    print(f"[ActionManager]: Auto-repeat skipped for factory ID {factory.id} - Missing required ingredients on warehouse shelves.")
                    continue

                current_slots = 1 if factory.current_craft else 0
                current_slots += len(factory.pending_crafts)
                if current_slots >= 3:
                    print(f"[ActionManager]: Auto-repeat skipped for factory ID {factory.id} - Queue is full.")
                    continue

                recipe_id = factory.repeat_recipe
                if not recipe_id:
                    recipe_id = factory.current_craft.get("id", None)
                    if not recipe_id:
                        continue
                    
                events.append({
                    "type": "factory",
                    "action": "craft",
                    "objId": factory.id,
                    "itemId": recipe_id,
                    "workers": factory.workers
                })
                
        if not events: return {}
        print(f"[ActionManager]: Posting mass factories packet containing {len(events)} sub-events (repeat={repeat_on_pick})...")
        response = self.client.execute_raw_action(events)
        
        # IN-MEMORY MUTATION
        if response and response.get("cmd") != "ERR":
            for factory in factories_list:
                for mat in factory.materials:
                    raw_item = mat.get("item", "")
                    item_id = raw_item[1:] if raw_item.startswith("@") else raw_item
                    if item_id.startswith("U_"): item_id = item_id[2:]
                    count = int(mat.get("count", 1))
                    self.data_manager.main_storage.items[item_id] = self.data_manager.main_storage.items.get(item_id, 0) + count
                factory.materials = []
                
        self.data_manager.update_from_server_response(response)
        return response

    def start_craft_in_factories_mass(self, factories_list: list[Factory], recipe_id: str) -> dict:
        """Mass launches a craft recipe ONLY for working factories with available queue slots and verified storage stocks."""
        if not factories_list: return {}
        events = []
                
        for factory in factories_list:
            if factory.require_workers and not factory.current_craft:
                print(f"[ActionManager]: Skipping factory ID {factory.id} ({factory.item_proto}) - Factory is inactive (no active blueprint structure found)!")
                continue
                
            if factory.current_craft and not self._has_enough_materials_for_craft(factory.current_craft):
                print(f"[ActionManager]: Skipping factory ID {factory.id} ({factory.item_proto}) - Aborting craft due to missing resource ingredients inside warehouse slots!")
                continue
                
            current_active_slots = 1 if factory.current_craft else 0
            current_active_slots += len(factory.pending_crafts)
            if current_active_slots >= 3:
                print(f"[ActionManager]: Skipping factory ID {factory.id} ({factory.item_proto}) - Production queue is FULL ({current_active_slots}/3)!")
                continue

            events.append({
                "type": "factory",
                "action": "craft",
                "objId": factory.id,
                "itemId": recipe_id,
                "workers": factory.workers
            })
            
        if not events:
            print("[ActionManager]: Mass craft aborted - zero factories passed the safety validation checks.")
            return {}
            
        print(f"[ActionManager]: Posting mass manual craft '{recipe_id}' for {len(events)} valid factories...")
        response = self.client.execute_raw_action(events)
        self.data_manager.update_from_server_response(response)
        return response

    def harvest_greenhouses_mass(self, greenhouses_list: list[Greenhouse]) -> dict:
        """Mass harvests crops from grown plots and dynamically mutates them into slag state."""
        if not greenhouses_list:
            return {}
            
        events = []
        for gh in greenhouses_list:
            raw_name = gh.item_proto.upper()
            crop_name = raw_name[2:] if raw_name.startswith("P_") else raw_name
            crop_id = f"P_{crop_name}" if crop_name else None
            if not crop_id:
                return {}
            
            events.append({
                "type": "item",
                "action": "pick",
                "objId": gh.id,
                "msg": f"FarmWorldContainer.onCompositionGether {crop_id}"
            })
            
        print(f"[ActionManager]: Posting mass harvest for {len(events)} greenhouses...")
        if not events:
            return {}
            
        response = self.client.execute_raw_action(events)
        if response and response.get("cmd") != "ERR":
            for gh in greenhouses_list:
                gh.type = "Slag"
                gh.item_proto = "SLAG"
                if hasattr(gh, 'crop_proto'):
                    gh.crop_proto = ""
            print(f"[ActionManager]: In-memory mutation success. {len(greenhouses_list)} plots updated to 'Slag'.")

        self.data_manager.update_from_server_response(response)
        return response

    def dig_greenhouses_mass(self, greenhouses_list: list[Greenhouse]) -> dict:
        """Mass digs/weeds selected plots and dynamically mutates them into empty ground state."""
        if not greenhouses_list:
            return {}
            
        events = []
        for gh in greenhouses_list:
            events.append({
                "type": "item",
                "action": "dig",
                "objId": gh.id
            })
            
        print(f"[ActionManager]: Posting mass dig job for {len(greenhouses_list)} greenhouses...")
        if not events:
            return {}
            
        response = self.client.execute_raw_action(events)
        if response and response.get("cmd") != "ERR":
            for gh in greenhouses_list:
                gh.type = "ground"
                gh.item_proto = "GROUND"
            print(f"[ActionManager]: In-memory mutation success. {len(greenhouses_list)} plots updated to 'ground'.")

        self.data_manager.update_from_server_response(response)
        return response


    def plant_greenhouses_mass(self, greenhouses_list: list[Greenhouse], crop_id: str) -> dict:
        if not greenhouses_list: return {}
        events = []
        for gh in greenhouses_list:
            events.append({"type": "item", "action": "buy", "objId": gh.id, "itemId": crop_id, "x": gh.x, "y": gh.y})
            
        response = self.client.execute_raw_action(events)
        if response and response.get("cmd") != "ERR":
            clean_crop_name = crop_id[2:] if crop_id.startswith("P_") else crop_id
            for gh in greenhouses_list:
                gh.type = "plant"
                gh.item_proto = crop_id.upper()
                if hasattr(gh, 'crop_proto'):
                    gh.crop_proto = clean_crop_name.upper()
                gh.job_finish_time = 9999999
                self.data_manager.energy = max(0, self.data_manager.energy - 1)
                
            print(f"[ActionManager]: In-memory mutation success. Deducted {len(greenhouses_list)} energy units.")

        self.data_manager.update_from_server_response(response)
        return response

    def consume_energy_items(self, item_id: str, energy_per_item: int, amount_to_eat: int = None) -> dict:
        """Sends chained events to consume energy food items and mutates local energy capacity."""
        if amount_to_eat is None:
            potential_energy = self.data_manager.energy
            amount_to_eat = 0
            while potential_energy < self.data_manager.max_energy:
                amount_to_eat += 1
                potential_energy += energy_per_item
                if amount_to_eat > 100:
                    return {}

        amount_to_eat = min(amount_to_eat, self.data_manager.main_storage.get_item_count(item_id))
        events = []
        for _ in range(amount_to_eat):
            events.append({
                "type": "item",
                "action": "use",
                "itemId": item_id
            })

        if not events: 
            return {}
        print(f"[ActionManager]: Posting food request to eat {amount_to_eat}x '{item_id}'...")
        response = self.client.execute_raw_action(events)
        if response and response.get("cmd") != "ERR":
            added_energy = amount_to_eat * energy_per_item
            self.data_manager.energy += added_energy
            print(f"[ActionManager]: Restored +{added_energy} energy units in memory. Current: {self.data_manager.energy}")
            
        self.data_manager.update_from_server_response(response)
        return response

    def fertilize_greenhouse_factories_mass(self, factories_list: list[GreenhouseFactory], fertilize_item_id: str | None) -> dict:
        if not factories_list: return {}
        events = []

        used_fertilizers = dict()
        for factory in factories_list:
            if factory.current_craft and not factory.current_craft_fertilized:
                fertilizer = fertilize_item_id if fertilize_item_id is not None else factory.repeat_fertilizer
                if fertilizer and self.data_manager.main_storage.get_item_count(fertilizer) > 0:
                    used_fertilizers[fertilizer] = used_fertilizers.get(fertilizer, 0) + 1
                    events.append({
                        "type": "item",
                        "action": "fertilize",
                        "objId": factory.id,
                        "itemId": fertilizer,
                    })

        if not events: return {}
        print(f"[ActionManager]: Posting mass greenhouse factories packet containing {len(events)} sub-events (fertilizer={fertilize_item_id})...")
        response = self.client.execute_raw_action(events)
        if response and response.get("cmd") != "ERR":
            for key, value in used_fertilizers.items():
                self.data_manager.main_storage.items[key] = self.data_manager.main_storage.get_item_count(key) - value 
                
        self.data_manager.update_from_server_response(response)
        return response
        