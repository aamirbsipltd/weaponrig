"""Weapon config schema — pure Python dataclasses, zero bpy dependency."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Constraint definition
# ---------------------------------------------------------------------------

VALID_CONSTRAINT_TYPES = {
    "LIMIT_ROTATION",
    "LIMIT_LOCATION",
    "COPY_ROTATION",
    "TRACK_TO",
    "STRETCH_TO",
}


@dataclass
class ConstraintDef:
    type: str
    # LIMIT_ROTATION / LIMIT_LOCATION axis flags & values
    min_x: float = 0.0
    max_x: float = 0.0
    min_y: float = 0.0
    max_y: float = 0.0
    min_z: float = 0.0
    max_z: float = 0.0
    use_limit_x: bool = False
    use_limit_y: bool = False
    use_limit_z: bool = False
    use_min_x: bool = False
    use_max_x: bool = False
    use_min_y: bool = False
    use_max_y: bool = False
    use_min_z: bool = False
    use_max_z: bool = False
    owner_space: str = "LOCAL"
    # COPY_ROTATION / TRACK_TO / STRETCH_TO
    target: Optional[str] = None
    subtarget: Optional[str] = None
    use_x: bool = True
    use_y: bool = True
    use_z: bool = True
    mix_mode: str = "REPLACE"
    target_space: str = "LOCAL"
    # TRACK_TO
    track_axis: str = "TRACK_NEGATIVE_Y"
    up_axis: str = "UP_Z"
    # STRETCH_TO
    rest_length: float = 0.0
    influence: float = 1.0

    @classmethod
    def from_dict(cls, d: dict) -> ConstraintDef:
        ctype = d.get("type")
        if ctype not in VALID_CONSTRAINT_TYPES:
            raise ValueError(f"Unknown constraint type: {ctype!r}")
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        kwargs = {k: v for k, v in d.items() if k in known_fields}
        return cls(**kwargs)


# ---------------------------------------------------------------------------
# Driver definitions
# ---------------------------------------------------------------------------

@dataclass
class CamCurveKeyframe:
    carrier_travel_pct: float
    bolt_rotation_pct: float

    @classmethod
    def from_dict(cls, d: dict) -> CamCurveKeyframe:
        return cls(
            carrier_travel_pct=d["carrier_travel_pct"],
            bolt_rotation_pct=d["bolt_rotation_pct"],
        )


@dataclass
class DriverDef:
    driven_property: str
    driver_bone: str
    driver_property: str
    expression: Optional[str] = None
    description: Optional[str] = None
    source: Optional[str] = None
    cam_curve_keyframes: list[CamCurveKeyframe] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> DriverDef:
        keyframes = [
            CamCurveKeyframe.from_dict(kf)
            for kf in d.get("cam_curve_keyframes", [])
        ]
        return cls(
            driven_property=d["driven_property"],
            driver_bone=d["driver_bone"],
            driver_property=d["driver_property"],
            expression=d.get("expression"),
            description=d.get("description"),
            source=d.get("source"),
            cam_curve_keyframes=keyframes,
        )


# ---------------------------------------------------------------------------
# Bone definition
# ---------------------------------------------------------------------------

VALID_PRESENCE = {"required", "expected", "optional"}
VALID_MOVEMENT_TYPES = {"static", "translate", "rotate", "scale"}


@dataclass
class BoneDef:
    name: str
    parent: Optional[str] = None
    presence: str = "required"
    movement_type: str = "static"
    axis: Optional[str] = None
    description: Optional[str] = None
    constraints: list[ConstraintDef] = field(default_factory=list)
    drivers: list[DriverDef] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> BoneDef:
        name = d.get("name")
        if not name:
            raise ValueError("Bone definition missing required 'name' field")

        presence = d.get("presence", "required")
        if presence not in VALID_PRESENCE:
            raise ValueError(
                f"Bone '{name}': invalid presence {presence!r}, "
                f"must be one of {VALID_PRESENCE}"
            )

        movement_type = d.get("movement_type", "static")
        if movement_type not in VALID_MOVEMENT_TYPES:
            raise ValueError(
                f"Bone '{name}': invalid movement_type {movement_type!r}, "
                f"must be one of {VALID_MOVEMENT_TYPES}"
            )

        constraints = [
            ConstraintDef.from_dict(c) for c in d.get("constraints", [])
        ]
        drivers = [DriverDef.from_dict(dr) for dr in d.get("drivers", [])]

        return cls(
            name=name,
            parent=d.get("parent"),
            presence=presence,
            movement_type=movement_type,
            axis=d.get("axis"),
            description=d.get("description"),
            constraints=constraints,
            drivers=drivers,
            parameters=d.get("parameters", {}),
        )


# ---------------------------------------------------------------------------
# Top-level weapon config
# ---------------------------------------------------------------------------

SUPPORTED_SCHEMA_VERSIONS = {"1.0"}


@dataclass
class WeaponConfig:
    schema_version: str
    operating_system: str
    display_name: str
    description: str = ""
    fire_modes: list[str] = field(default_factory=list)
    cyclic_rate_rpm: dict[str, Optional[float]] = field(default_factory=dict)
    bones: list[BoneDef] = field(default_factory=list)
    unified_skeleton_extra_bones: list[str] = field(default_factory=list)
    physics: dict[str, Any] = field(default_factory=dict)
    part_name_aliases: dict[str, list[str]] = field(default_factory=dict)

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_dict(cls, d: dict) -> WeaponConfig:
        version = d.get("schema_version", "")
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"Unsupported schema_version {version!r}. "
                f"Supported: {SUPPORTED_SCHEMA_VERSIONS}"
            )

        operating_system = d.get("operating_system")
        if not operating_system:
            raise ValueError("Config missing required 'operating_system' field")

        display_name = d.get("display_name", operating_system)

        bones = [BoneDef.from_dict(b) for b in d.get("bones", [])]

        # Validate parent references
        bone_names = {b.name for b in bones}
        for bone in bones:
            if bone.parent and bone.parent not in bone_names:
                raise ValueError(
                    f"Bone '{bone.name}' references unknown parent '{bone.parent}'"
                )

        # Check for circular parent references
        _check_circular_parents(bones)

        return cls(
            schema_version=version,
            operating_system=operating_system,
            display_name=display_name,
            description=d.get("description", ""),
            fire_modes=d.get("fire_modes", []),
            cyclic_rate_rpm=d.get("cyclic_rate_rpm", {}),
            bones=bones,
            unified_skeleton_extra_bones=d.get(
                "unified_skeleton_extra_bones", []
            ),
            physics=d.get("physics", {}),
            part_name_aliases=d.get("part_name_aliases", {}),
        )

    @classmethod
    def load(cls, path: str | Path) -> WeaponConfig:
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    # -- Queries ------------------------------------------------------------

    def get_bone(self, name: str) -> Optional[BoneDef]:
        for bone in self.bones:
            if bone.name == name:
                return bone
        return None

    def root_bones(self) -> list[BoneDef]:
        return [b for b in self.bones if b.parent is None]

    # -- Config discovery ---------------------------------------------------

    @staticmethod
    def configs_dir() -> Path:
        return Path(__file__).parent / "configs"

    @classmethod
    def list_configs(cls) -> list[tuple[str, str, str]]:
        """Return list of (identifier, display_name, description) for available configs."""
        configs = []
        for p in sorted(cls.configs_dir().glob("*.json")):
            if p.name.startswith("_"):
                continue
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                identifier = p.stem
                display_name = data.get("display_name", identifier)
                description = data.get("description", "")
                configs.append((identifier, display_name, description))
            except (json.JSONDecodeError, KeyError):
                continue
        return configs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_circular_parents(bones: list[BoneDef]) -> None:
    """Raise ValueError if the parent chain contains a cycle."""
    parent_map = {b.name: b.parent for b in bones}
    for bone in bones:
        visited: set[str] = set()
        current = bone.name
        while current is not None:
            if current in visited:
                raise ValueError(
                    f"Circular parent reference detected involving bone '{current}'"
                )
            visited.add(current)
            current = parent_map.get(current)
