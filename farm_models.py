import time

class Storage:
    def __init__(self, raw_items: list = None, raw_objects: list = None):
        self.items = {}
        self.game_objects = {}
        
        if raw_items:
            for row in raw_items:
                clean_name = self._clean_name(row.get("item", ""))
                self.items[clean_name] = int(row.get("count", 0))
                
        if raw_objects:
            for row in raw_objects:
                clean_name = self._clean_name(row.get("item", ""))
                self.game_objects[clean_name] = int(row.get("count", 0))

    def _clean_name(self, name: str) -> str:
        if name and name.startswith("@"):
            return name[1:]
        return name

    def get_item_count(self, item_id: str) -> int:
        return self.items.get(item_id, 0)

    def get_object_count(self, object_proto: str) -> int:
        return self.game_objects.get(object_proto, 0)


class GameObject:
    def __init__(self, raw_data: dict):
        self.id = int(raw_data.get("id"))
        self.type = raw_data.get("type")
        item_name = raw_data.get("item", "")
        self.item_proto = item_name[1:] if item_name.startswith("@") else item_name
        self.x = raw_data.get("x", 0)
        self.y = raw_data.get("y", 0)
        self.rotate = int(raw_data.get("rotate", 0))
        self.level = raw_data.get("level", 1)


class Manufacture(GameObject):
    """Abstract base class for all production assets sharing materials storage and timers."""
    def __init__(self, raw_data: dict):
        super().__init__(raw_data)
        self.materials = raw_data.get("materials", [])
        self.job_end_time = int(raw_data.get("jobEndTime", raw_data.get("digestionEndTime", 0)))

    @property
    def has_product_ready(self) -> bool:
        """Returns True if the internal materials storage contains completed items."""
        return len(self.materials) > 0


class House(GameObject):
    def __init__(self, raw_data: dict):
        super().__init__(raw_data)
        self.next_play_times = raw_data.get("nextPlayTimes", {})
        self.humans = raw_data.get("humans", {})

    @property
    def total_workers(self) -> int:
        return len(self.humans)

    @property
    def worker_ids(self) -> list:
        return list(self.humans.keys())


class Factory(Manufacture):
    """Represents production structures utilizing hired workforce setups."""
    def __init__(self, raw_data: dict):
        super().__init__(raw_data)
        self.craft_no = raw_data.get("craftNo", 0)
        self.repeat_recipe = raw_data.get("repeat")
        self.workers = raw_data.get("workers", [])
        
        self.current_craft = raw_data.get("currentCraft", {})
        if self.current_craft:
            item_name = self.current_craft.get("id", "")
            self.current_craft["id"] = item_name[1:] if item_name.startswith("@") else item_name

        self.pending_crafts = raw_data.get("pendingCrafts", [])


class Animal(Manufacture):
    """Represents farm livestock yielding raw resources."""
    def __init__(self, raw_data: dict):
        super().__init__(raw_data)
        self.output_count = raw_data.get("outputCount", 0)


class Greenhouse(GameObject):
    """Represents farm plots tracking crop operations via relative timestamp indices."""
    def __init__(self, raw_data: dict):
        super().__init__(raw_data)
        self.job_start_time = int(raw_data.get("jobStartTime", 0))
        self.job_finish_time = int(raw_data.get("jobFinishTime", 0))
        self.fertilized = bool(raw_data.get("fertilized", False))
        
        raw_crop = self.item_proto.upper()
        self.crop_proto = raw_crop[2:] if raw_crop.startswith("P_") else raw_crop
        
        gh_template = raw_data.get("greenhouse", "")
        self.greenhouse_proto = gh_template[1:] if gh_template.startswith("@") else gh_template

    @property
    def is_ready_to_harvest(self) -> bool:
        """Returns True if a plant exists and server marks finish clock negative/expired."""
        return self.type == "plant" and self.job_finish_time <= 0

    @property
    def is_empty(self) -> bool:
        """Returns True if the land grid contains no active crop types."""
        return self.type == "ground" and self.item_proto == "GROUND"
        
    @property
    def needs_weeding(self) -> bool:
        """Returns True if a plot state turned into waste or slag."""
        return self.type == "Slag" or self.item_proto == "SLAG"


class RemoteLocation:
    def __init__(self, location_id: str, raw_data: dict):
        self.id = location_id
        self.settled = bool(raw_data.get("settled", False))
        self.storage = Storage(
            raw_items=raw_data.get("storageItems", []),
            raw_objects=raw_data.get("storageGameObjects", [])
        )
