from typing import List, Optional, Dict, Any
import time
import json

from core.ports import GameClientPort, LoggerPort
from domain.models import (
    NeighborPlayer, FarmState, Factory, Greenhouse, GreenhouseFactory
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
            if "__energy__" in reserved_materials:
                state.energy = max(0, state.energy - reserved_materials["__energy__"])
                self.logger.log_truncated("FarmService", "energy_deducted", amount=reserved_materials["__energy__"], remaining=state.energy)
            for factory in factories:
                factory.materials = []
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
            if "__energy__" in reserved_materials:
                state.energy = max(0, state.energy - reserved_materials["__energy__"])
                self.logger.log_truncated("FarmService", "energy_deducted", amount=reserved_materials["__energy__"], remaining=state.energy)
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

    def _is_ping_event(self, evt: Dict) -> bool:
        return evt.get("type") == "evt" and "ping" in str(evt.get("action", "")).lower()

    def _wait_for_non_ping_response(self, client: GameClientPort, initial_response: Dict) -> Dict:
        response = initial_response
        max_retries = 10
        for _ in range(max_retries):
            if client.is_error_response(response):
                return response
            events = response.get("events", [])
            if not any(self._is_ping_event(evt) for evt in events):
                return response
            self.logger.log_truncated("FarmService", "player_info_pending")
            time.sleep(1)
            response = client.execute_raw_action(events=[])
        self.logger.log_truncated("FarmService", "ping_timeout")
        return response

    def change_location(self, client: GameClientPort, location_id: str, user_id: Optional[str] = None) -> Dict:
        """
        Change current location to main/port/neighbor.
        If user_id is None, move to own location (main or port).
        """
        event = {
            "type": "gameState",
            "action": "gameState",
            "locationId": location_id,
            "user": user_id if user_id else None
        }
        self.logger.log_truncated("FarmService", "changing_location", location=location_id, user=user_id)
        response = client.execute_raw_action([event])
        if client.is_error_response(response):
            self.logger.log_full("FarmService", "change_location_error", payload=response)
        else:
            response = self._wait_for_non_ping_response(client, response)
            self.logger.log_truncated("FarmService", "location_changed", location=location_id, user=user_id)
        return response

    def go_to_own_port(self, client: GameClientPort, state: FarmState) -> Dict:
        """Move from own main location to own port location."""
        if not state.sea_start_port:
            self.logger.log_truncated("FarmService", "sea_start_port_missing")
            return {}
        self.logger.log_truncated("FarmService", "jumping_to_own_port")
        jump_response = client.execute_raw_action([{
            "type": "item",
            "action": "jump",
            "objId": int(state.sea_start_port.id)
        }])
        if client.is_error_response(jump_response):
            self.logger.log_full("FarmService", "jump_to_port_error", payload=jump_response)
            return jump_response
        time.sleep(1)
        return self.change_location(client, "port")

    def go_to_own_main(self, client: GameClientPort) -> Dict:
        """Move from own port location to own main location."""
        self.logger.log_truncated("FarmService", "returning_to_own_main")
        response = client.execute_raw_action([{
            "type": "item",
            "action": "toMain"
        }])
        if client.is_error_response(response):
            self.logger.log_full("FarmService", "to_main_error", payload=response)
        else:
            self.logger.log_truncated("FarmService", "returned_to_main")
        return response

    def visit_neighbor(self, client: GameClientPort, location_type: str, user_id: str) -> Dict:
        """Visit a neighbor's main or port location."""
        return self.change_location(client, location_type, user_id=user_id)

    def get_eligible_neighbor_players(
        self,
        client: GameClientPort,
        friends: List[str],
        location_type: str = "main"
    ) -> List[NeighborPlayer]:
        """
        Fetch neighbor info, filter by haveTreasure (and optionally havePort),
        sort by level descending.
        """
        if not friends:
            self.logger.log_truncated("FarmService", "no_friends")
            return []

        all_players: List[NeighborPlayer] = []
        batch_size = 40

        for i in range(0, len(friends), batch_size):
            batch = friends[i:i + batch_size]
            self.logger.log_truncated("FarmService", "fetching_player_batch",
                                      batch_index=i // batch_size, count=len(batch))

            response = client.execute_raw_action(events=[{
                "type": "players",
                "action": "getInfo",
                "players": batch
            }])

            response = self._wait_for_non_ping_response(client, response)

            if client.is_error_response(response):
                self.logger.log_full("FarmService", "player_info_error", payload=response)
                continue

            for evt in response.get("events", []):
                if self._is_ping_event(evt):
                    continue
                if "id" in evt and "level" in evt:
                    lite = evt.get("liteGameState", {})
                    all_players.append(NeighborPlayer(
                        id=str(evt.get("id", "")),
                        level=int(evt.get("level", 0)),
                        have_treasure=lite.get("haveTreasure", False),
                        have_port=lite.get("havePort", False),
                        name=evt.get("name", ""),
                        profile_name=evt.get("profileName", "")
                    ))
                elif "players" in evt and isinstance(evt["players"], list):
                    for p in evt["players"]:
                        lite = p.get("liteGameState", {})
                        all_players.append(NeighborPlayer(
                            id=str(p.get("id", "")),
                            level=int(p.get("level", 0)),
                            have_treasure=lite.get("haveTreasure", False),
                            have_port=lite.get("havePort", False),
                            name=p.get("name", ""),
                            profile_name=p.get("profileName", "")
                        ))

        eligible = [p for p in all_players if p.have_treasure]
        if location_type.lower() == "port":
            eligible = [p for p in eligible if p.have_port]
        eligible.sort(key=lambda p: p.level, reverse=True)

        self.logger.log_truncated("FarmService", "neighbor_players_ready",
                                  total=len(all_players), eligible=len(eligible), location=location_type)
        return eligible

    def get_free_shovel_count(self, state: FarmState, user_id: str) -> int:
        """Return the number of free shovels available for a given neighbor."""
        for entry in state.remoteTreasure:
            if str(entry.get("user", "")) == str(user_id):
                return int(entry.get("count", 5))
        return 5

    def extract_game_objects_from_response(self, response: Dict) -> List[Dict]:
        """Extract gameObjects list from a server response."""
        objects = []
        for evt in response.get("events", []):
            if "gameObjects" in evt:
                objects.extend(evt.get("gameObjects", []))
        return objects

    def dig_neighbor_objects(
        self,
        client: GameClientPort,
        state: FarmState,
        user_id: str,
        objects: List[Dict],
        shovel_extra_id: str = "REMOTE_SHOVEL",
        use_gold_shovels: bool = False
    ) -> Dict:
        if not objects:
            return {}

        events = []
        used_remote = 0
        used_gold = 0
        for obj in objects:
            events.append({
                "type": "item",
                "extraId": shovel_extra_id,
                "action": "remoteDig",
                "objId": obj.get("id"),
                "x": obj.get("x", 0),
                "y": obj.get("y", 0)
            })
            if shovel_extra_id == "REMOTE_SHOVEL":
                used_remote += 1
            elif shovel_extra_id == "SHOVEL_EXTRA":
                used_gold += 1

        self.logger.log_truncated(
            "FarmService", "posting_dig_events",
            user=user_id, shovel=shovel_extra_id, count=len(events)
        )
        response = client.execute_raw_action(events)
        if client.is_error_response(response):
            self.logger.log_full("FarmService", "dig_neighbor_error", payload=response)
            return response

        response = self._wait_for_non_ping_response(client, response)
        if client.is_error_response(response):
            self.logger.log_full("FarmService", "dig_neighbor_error_after_ping", payload=response)
            return response

        treasure_objects = self._process_dig_response(
            response, state, user_id, used_remote, used_gold
        )
        self._apply_response_updates(state, response)

        # For each detected treasure, keep digging the same object
        for treasure_id in treasure_objects:
            obj = next((o for o in objects if int(o.get("id")) == treasure_id), None)
            if obj:
                self.dig_treasure_sequence(
                    client, state, user_id, obj, use_gold_shovels=use_gold_shovels
                )

        return response

    def _process_dig_response(
        self,
        response: Dict,
        state: FarmState,
        user_id: str,
        used_remote_shovels: int,
        used_gold_shovels: int
    ) -> List[int]:
        """Process a dig response: debit shovels, credit shovel refunds, return treasure object ids."""
        treasure_objects: List[int] = []
        alert_pending = False

        # Debit used shovels first
        if used_remote_shovels > 0:
            self._debit_free_shovels(state, user_id, used_remote_shovels)
        if used_gold_shovels > 0:
            current = state.main_storage.get_item_count("SHOVEL_EXTRA")
            state.main_storage.items["SHOVEL_EXTRA"] = max(0, current - used_gold_shovels)

        for evt in response.get("events", []):
            evt_type = evt.get("type", "")
            evt_str = json.dumps(evt, ensure_ascii=False)

            # Log each event for debugging
            self.logger.log_truncated(
                "FarmService", "dig_response_event",
                evt_type=evt_type,
                has_alert="SERVER_TREASURE_FOUND" in evt_str,
                obj_id=evt.get("objId")
            )

            # Detect alert event (very lenient: search the entire event text)
            if "SERVER_TREASURE_FOUND" in evt_str and evt_type == "alert":
                alert_pending = True
                self.logger.log_truncated("FarmService", "treasure_alert_detected")
                continue

            if evt_type == "pickup" and evt.get("action") == "add":
                # Credit shovel refunds
                for pickup in evt.get("pickups", []):
                    if pickup.get("type") == "shovel":
                        self._credit_free_shovels(state, user_id, 1)

                # If the previous event was an alert, this pickup is the treasure
                if alert_pending:
                    obj_id = evt.get("objId")
                    if obj_id is not None:
                        treasure_objects.append(int(obj_id))
                        self.logger.log_truncated(
                            "FarmService", "treasure_object_found",
                            obj_id=obj_id, total=len(treasure_objects)
                        )
                    alert_pending = False

        return treasure_objects

    def _debit_free_shovels(self, state: FarmState, user_id: str, count: int) -> None:
        """Reduce free shovel count for a user."""
        for entry in state.remoteTreasure:
            if str(entry.get("user", "")) == str(user_id):
                entry["count"] = max(0, int(entry.get("count", 5)) - count)
                return
        # Not found, add new entry
        state.remoteTreasure.append({
            "user": user_id,
            "count": max(0, 5 - count),
            "date": "0"
        })

    def _credit_free_shovels(self, state: FarmState, user_id: str, count: int) -> None:
        """Increase free shovel count for a user."""
        for entry in state.remoteTreasure:
            if str(entry.get("user", "")) == str(user_id):
                entry["count"] = int(entry.get("count", 5)) + count
                return
        # Not found, add with base 5 plus credit
        state.remoteTreasure.append({
            "user": user_id,
            "count": 5 + count,
            "date": "0"
        })

    def dig_treasure_sequence(
        self,
        client: GameClientPort,
        state: FarmState,
        user_id: str,
        treasure_object: Dict,
        use_gold_shovels: bool = False,
        max_digs: int = 10
    ) -> Dict:
        """Repeatedly dig the same treasure object until no treasure is found or max_digs reached."""
        last_response: Dict = {}
        treasure_id = int(treasure_object.get("id"))

        for attempt in range(max_digs):
            free_shovels = self.get_free_shovel_count(state, user_id)
            shovel_extra_id = None
            used_remote = 0
            used_gold = 0

            if free_shovels > 0:
                shovel_extra_id = "REMOTE_SHOVEL"
                used_remote = 1
            elif use_gold_shovels and state.main_storage.get_item_count("SHOVEL_EXTRA") > 0:
                shovel_extra_id = "SHOVEL_EXTRA"
                used_gold = 1
            else:
                self.logger.log_truncated(
                    "FarmService", "treasure_sequence_stop_no_shovels",
                    obj_id=treasure_id, attempt=attempt, free=free_shovels
                )
                break

            event = {
                "type": "item",
                "extraId": shovel_extra_id,
                "action": "remoteDig",
                "objId": treasure_object.get("id"),
                "x": treasure_object.get("x", 0),
                "y": treasure_object.get("y", 0)
            }
            self.logger.log_truncated(
                "FarmService", "treasure_sequence_dig",
                obj_id=treasure_id, attempt=attempt, shovel=shovel_extra_id
            )

            response = client.execute_raw_action([event])
            if client.is_error_response(response):
                self.logger.log_full("FarmService", "treasure_sequence_error", payload=response)
                break

            response = self._wait_for_non_ping_response(client, response)
            if client.is_error_response(response):
                self.logger.log_full("FarmService", "treasure_sequence_error_after_ping", payload=response)
                break

            found = self._process_dig_response(response, state, user_id, used_remote, used_gold)
            self._apply_response_updates(state, response)
            last_response = response

            # Continue only if the SAME object was flagged as treasure again
            if treasure_id not in found:
                self.logger.log_truncated(
                    "FarmService", "treasure_sequence_done",
                    obj_id=treasure_id, attempt=attempt
                )
                break

        return last_response