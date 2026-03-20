"""Tests for config validation and error handling."""

import pytest

from weaponrig.database.schema import (
    BoneDef,
    ConstraintDef,
    DriverDef,
    WeaponConfig,
)


# ---------------------------------------------------------------------------
# Schema version validation
# ---------------------------------------------------------------------------

class TestSchemaVersion:
    def test_rejects_unsupported_version(self):
        with pytest.raises(ValueError, match="Unsupported schema_version"):
            WeaponConfig.from_dict({
                "schema_version": "99.0",
                "operating_system": "test",
            })

    def test_rejects_missing_version(self):
        with pytest.raises(ValueError, match="Unsupported schema_version"):
            WeaponConfig.from_dict({
                "operating_system": "test",
            })


# ---------------------------------------------------------------------------
# Operating system validation
# ---------------------------------------------------------------------------

class TestOperatingSystem:
    def test_rejects_missing_operating_system(self):
        with pytest.raises(ValueError, match="operating_system"):
            WeaponConfig.from_dict({
                "schema_version": "1.0",
            })

    def test_rejects_empty_operating_system(self):
        with pytest.raises(ValueError, match="operating_system"):
            WeaponConfig.from_dict({
                "schema_version": "1.0",
                "operating_system": "",
            })


# ---------------------------------------------------------------------------
# Bone validation
# ---------------------------------------------------------------------------

class TestBoneValidation:
    def test_rejects_missing_bone_name(self):
        with pytest.raises(ValueError, match="missing required 'name'"):
            BoneDef.from_dict({"parent": "root"})

    def test_rejects_empty_bone_name(self):
        with pytest.raises(ValueError, match="missing required 'name'"):
            BoneDef.from_dict({"name": ""})

    def test_rejects_invalid_presence(self):
        with pytest.raises(ValueError, match="invalid presence"):
            BoneDef.from_dict({"name": "test", "presence": "sometimes"})

    def test_rejects_invalid_movement_type(self):
        with pytest.raises(ValueError, match="invalid movement_type"):
            BoneDef.from_dict({"name": "test", "movement_type": "teleport"})

    def test_accepts_minimal_bone(self):
        bone = BoneDef.from_dict({"name": "test_bone"})
        assert bone.name == "test_bone"
        assert bone.parent is None
        assert bone.presence == "required"
        assert bone.movement_type == "static"

    def test_rejects_unknown_parent(self):
        with pytest.raises(ValueError, match="unknown parent"):
            WeaponConfig.from_dict({
                "schema_version": "1.0",
                "operating_system": "test",
                "bones": [
                    {"name": "child", "parent": "nonexistent"},
                ],
            })

    def test_rejects_circular_parents(self):
        with pytest.raises(ValueError, match="Circular parent"):
            WeaponConfig.from_dict({
                "schema_version": "1.0",
                "operating_system": "test",
                "bones": [
                    {"name": "a", "parent": "b"},
                    {"name": "b", "parent": "a"},
                ],
            })

    def test_rejects_self_parent(self):
        with pytest.raises(ValueError, match="Circular parent"):
            WeaponConfig.from_dict({
                "schema_version": "1.0",
                "operating_system": "test",
                "bones": [
                    {"name": "a", "parent": "a"},
                ],
            })


# ---------------------------------------------------------------------------
# Constraint validation
# ---------------------------------------------------------------------------

class TestConstraintValidation:
    def test_rejects_unknown_constraint_type(self):
        with pytest.raises(ValueError, match="Unknown constraint type"):
            ConstraintDef.from_dict({"type": "BANANA_CONSTRAINT"})

    def test_accepts_limit_rotation(self):
        c = ConstraintDef.from_dict({
            "type": "LIMIT_ROTATION",
            "min_x": 0.0,
            "max_x": 1.57,
            "use_limit_x": True,
        })
        assert c.type == "LIMIT_ROTATION"
        assert c.max_x == 1.57
        assert c.use_limit_x is True

    def test_ignores_unknown_fields(self):
        c = ConstraintDef.from_dict({
            "type": "LIMIT_LOCATION",
            "some_future_field": 42,
        })
        assert c.type == "LIMIT_LOCATION"


# ---------------------------------------------------------------------------
# Driver validation
# ---------------------------------------------------------------------------

class TestDriverValidation:
    def test_accepts_expression_driver(self):
        d = DriverDef.from_dict({
            "driven_property": "rotation_euler.y",
            "driver_bone": "bolt_carrier",
            "driver_property": "location.y",
            "expression": "var * -3.8",
        })
        assert d.expression == "var * -3.8"
        assert d.cam_curve_keyframes == []

    def test_accepts_cam_curve_driver(self):
        d = DriverDef.from_dict({
            "driven_property": "rotation_euler.y",
            "driver_bone": "bolt_carrier",
            "driver_property": "location.y",
            "cam_curve_keyframes": [
                {"carrier_travel_pct": 0.0, "bolt_rotation_pct": 0.0},
                {"carrier_travel_pct": 1.0, "bolt_rotation_pct": 1.0},
            ],
        })
        assert len(d.cam_curve_keyframes) == 2

    def test_rejects_missing_driven_property(self):
        with pytest.raises(KeyError):
            DriverDef.from_dict({
                "driver_bone": "bolt_carrier",
                "driver_property": "location.y",
            })


# ---------------------------------------------------------------------------
# Config with no bones
# ---------------------------------------------------------------------------

class TestEmptyConfig:
    def test_config_with_no_bones(self):
        cfg = WeaponConfig.from_dict({
            "schema_version": "1.0",
            "operating_system": "test_empty",
        })
        assert cfg.bones == []
        assert cfg.fire_modes == []

    def test_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            WeaponConfig.load("nonexistent_path.json")
