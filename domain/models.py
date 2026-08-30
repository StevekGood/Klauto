from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Storage:
    items: Dict[str, int] = field(default_factory=dict)
    game_objects: Dict[str, int] = field(default_factory=dict)
    raw_items: Optional[List[Dict]] = None
    raw_objects: Optional[List[Dict]] = None

    def __post_init__(self):
        if self.raw_items:
            for row in self.raw_items:
                clean_name = self._clean_name(row.get("item", ""))
                self.items[clean_name] = int(row.get("count", 0))
        if self.raw_objects:
            for row in self.raw_objects:
                clean_name = self._clean_name(row.get("item", ""))
                self.game_objects[clean_name] = int(row.get("count", 0))

    @staticmethod
    def _clean_name(name: str) -> str:
        return name[1:] if name.startswith("@") else name

    def get_item_count(self, item_id: str) -> int:
        return self.items.get(item_id, 0)

    def get_object_count(self, obj_proto: str) -> int:
        return self.game_objects.get(obj_proto, 0)


@dataclass
class GameObject:
    id: int
    type: str
    item_proto: str
    x: int = 0
    y: int = 0
    rotate: int = 0
    level: int = 1

    @classmethod
    def from_dict(cls, raw: Dict) -> "GameObject":
        item_name = raw.get("item", "")
        item_proto = item_name[1:] if item_name.startswith("@") else item_name
        return cls(
            id=int(raw.get("id")),
            type=raw.get("type", ""),
            item_proto=item_proto,
            x=raw.get("x", 0),
            y=raw.get("y", 0),
            rotate=int(raw.get("rotate", 0)),
            level=raw.get("level", 1),
        )


@dataclass
class Manufacture(GameObject):
    materials: List[Dict] = field(default_factory=list)
    job_end_time: int = 0

    @classmethod
    def from_dict(cls, raw: Dict) -> "Manufacture":
        base = GameObject.from_dict(raw)
        return cls(
            id=base.id,
            type=base.type,
            item_proto=base.item_proto,
            x=base.x,
            y=base.y,
            rotate=base.rotate,
            level=base.level,
            materials=raw.get("materials", []),
            job_end_time=int(raw.get("jobEndTime", raw.get("digestionEndTime", 0))),
        )

    @property
    def has_product_ready(self) -> bool:
        return len(self.materials) > 0


@dataclass
class Factory(Manufacture):
    craft_no: int = 0
    repeat_recipe: Optional[str] = None
    workers: List[Any] = field(default_factory=list)
    require_workers: bool = True
    current_craft: Optional[Dict] = None
    pending_crafts: List[Dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: Dict) -> "Factory":
        base = Manufacture.from_dict(raw)
        current_craft = raw.get("currentCraft", {})
        if current_craft:
            item_name = current_craft.get("id", "")
            current_craft["id"] = item_name[1:] if item_name.startswith("@") else item_name
        return cls(
            id=base.id,
            type=base.type,
            item_proto=base.item_proto,
            x=base.x,
            y=base.y,
            rotate=base.rotate,
            level=base.level,
            materials=base.materials,
            job_end_time=base.job_end_time,
            craft_no=raw.get("craftNo", 0),
            repeat_recipe=raw.get("repeat"),
            workers=raw.get("workers", []),
            require_workers=raw.get("require_workers", True),
            current_craft=current_craft,
            pending_crafts=raw.get("pendingCrafts", []),
        )


@dataclass
class GreenhouseFactory(Factory):
    repeat_fertilizer: Optional[str] = None
    current_craft_fertilized: bool = False

    @classmethod
    def from_dict(cls, raw: Dict) -> "GreenhouseFactory":
        base = Factory.from_dict(raw)
        return cls(
            id=base.id,
            type=base.type,
            item_proto=base.item_proto,
            x=base.x,
            y=base.y,
            rotate=base.rotate,
            level=base.level,
            materials=base.materials,
            job_end_time=base.job_end_time,
            craft_no=base.craft_no,
            repeat_recipe=base.repeat_recipe,
            workers=base.workers,
            require_workers=base.require_workers,
            current_craft=base.current_craft,
            pending_crafts=base.pending_crafts,
            repeat_fertilizer=raw.get("repeatFertilizer"),
            current_craft_fertilized=raw.get("currentCraftFertilized", False),
        )


@dataclass
class House(GameObject):
    next_play_times: Dict = field(default_factory=dict)
    humans: Dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Dict) -> "House":
        base = GameObject.from_dict(raw)
        return cls(
            id=base.id,
            type=base.type,
            item_proto=base.item_proto,
            x=base.x,
            y=base.y,
            rotate=base.rotate,
            level=base.level,
            next_play_times=raw.get("nextPlayTimes", {}),
            humans=raw.get("humans", {}),
        )

    @property
    def total_workers(self) -> int:
        return len(self.humans)

    @property
    def worker_ids(self) -> List[str]:
        return list(self.humans.keys())


@dataclass
class Animal(Manufacture):
    output_count: int = 0

    @classmethod
    def from_dict(cls, raw: Dict) -> "Animal":
        base = Manufacture.from_dict(raw)
        return cls(
            id=base.id,
            type=base.type,
            item_proto=base.item_proto,
            x=base.x,
            y=base.y,
            rotate=base.rotate,
            level=base.level,
            materials=base.materials,
            job_end_time=base.job_end_time,
            output_count=raw.get("outputCount", 0),
        )


@dataclass
class Greenhouse(GameObject):
    job_start_time: int = 0
    job_finish_time: int = 0
    fertilized: bool = False
    crop_proto: str = ""
    greenhouse_proto: str = ""

    @classmethod
    def from_dict(cls, raw: Dict) -> "Greenhouse":
        base = GameObject.from_dict(raw)
        raw_item_proto = base.item_proto.upper()
        crop_proto = raw_item_proto[2:] if raw_item_proto.startswith("P_") else raw_item_proto
        gh_template = raw.get("greenhouse", "")
        greenhouse_proto = gh_template[1:] if gh_template.startswith("@") else gh_template
        return cls(
            id=base.id,
            type=base.type,
            item_proto=base.item_proto,
            x=base.x,
            y=base.y,
            rotate=base.rotate,
            level=base.level,
            job_start_time=int(raw.get("jobStartTime", 0)),
            job_finish_time=int(raw.get("jobFinishTime", 0)),
            fertilized=bool(raw.get("fertilized", False)),
            crop_proto=crop_proto,
            greenhouse_proto=greenhouse_proto,
        )

    @property
    def is_ready_to_harvest(self) -> bool:
        return self.type == "plant" and self.job_finish_time <= 0

    @property
    def is_empty(self) -> bool:
        return self.type == "ground" and self.item_proto == "GROUND"

    @property
    def needs_weeding(self) -> bool:
        return self.type == "Slag" or self.item_proto == "SLAG"


@dataclass
class RemoteLocation:
    id: str
    settled: bool
    storage: Storage

    @classmethod
    def from_dict(cls, loc_id: str, raw: Dict) -> "RemoteLocation":
        return cls(
            id=loc_id,
            settled=bool(raw.get("settled", False)),
            storage=Storage(
                raw_items=raw.get("storageItems", []),
                raw_objects=raw.get("storageGameObjects", []),
            ),
        )


@dataclass
class FarmState:
    bank: Dict = field(default_factory=dict)
    level: int = 0
    game_money: int = 0
    cash_money: int = 0
    silver_money: int = 0
    max_energy: int = 42
    energy: int = 0
    kerosene: int = 0
    collection_items: Dict = field(default_factory=dict)
    work_places: List = field(default_factory=list)
    partners: Dict = field(default_factory=dict)
    help_points: int = 0
    main_storage: Storage = field(default_factory=Storage)
    all_objects: Dict[int, GameObject] = field(default_factory=dict)
    factories: List[Factory] = field(default_factory=list)
    greenhouse_factories: List[GreenhouseFactory] = field(default_factory=list)
    greenhouses: List[Greenhouse] = field(default_factory=list)
    animals: List[Animal] = field(default_factory=list)
    houses: List[House] = field(default_factory=list)
    locations: Dict[str, RemoteLocation] = field(default_factory=dict)