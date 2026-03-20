"""Tests for weapon config schema loading and validation."""

import pytest

from weaponrig.database.schema import (
    BoneDef,
    ConstraintDef,
    DriverDef,
    WeaponConfig,
)


# ---------------------------------------------------------------------------
# AR-15 config loading
# ---------------------------------------------------------------------------

class TestAR15Config:
    def test_loads_successfully(self, ar15_config):
        assert ar15_config.operating_system == "ar15_direct_impingement"
        assert ar15_config.display_name == "AR-15 Direct Impingement"
        assert ar15_config.schema_version == "1.0"

    def test_bone_count(self, ar15_config):
        assert len(ar15_config.bones) == 16

    def test_fire_modes(self, ar15_config):
        assert ar15_config.fire_modes == ["semi", "auto", "burst_3"]

    def test_cyclic_rate(self, ar15_config):
        assert ar15_config.cyclic_rate_rpm["auto"] == 700
        assert ar15_config.cyclic_rate_rpm["semi"] is None

    def test_bone_hierarchy_bolt_carrier(self, ar15_config):
        bc = ar15_config.get_bone("bolt_carrier")
        assert bc is not None
        assert bc.parent == "upper_receiver"
        assert bc.movement_type == "translate"
        assert bc.axis == "Y"

    def test_bone_hierarchy_bolt(self, ar15_config):
        bolt = ar15_config.get_bone("bolt")
        assert bolt is not None
        assert bolt.parent == "bolt_carrier"
        assert bolt.movement_type == "rotate"

    def test_root_bones(self, ar15_config):
        roots = ar15_config.root_bones()
        root_names = {b.name for b in roots}
        assert "weapon_root" in root_names
        assert "magazine" in root_names

    def test_bolt_carrier_constraint(self, ar15_config):
        bc = ar15_config.get_bone("bolt_carrier")
        assert len(bc.constraints) == 1
        c = bc.constraints[0]
        assert c.type == "LIMIT_LOCATION"
        assert c.max_y == -0.095
        assert c.use_max_y is True

    def test_bolt_driver(self, ar15_config):
        bolt = ar15_config.get_bone("bolt")
        assert len(bolt.drivers) == 1
        d = bolt.drivers[0]
        assert d.driven_property == "rotation_euler.y"
        assert d.driver_bone == "bolt_carrier"
        assert d.expression == "var * -3.8"

    def test_bolt_cam_curve(self, ar15_config):
        bolt = ar15_config.get_bone("bolt")
        d = bolt.drivers[0]
        assert len(d.cam_curve_keyframes) == 4
        assert d.cam_curve_keyframes[0].carrier_travel_pct == 0.0
        assert d.cam_curve_keyframes[2].bolt_rotation_pct == 1.0

    def test_buffer_spring_driver(self, ar15_config):
        bs = ar15_config.get_bone("buffer_spring")
        assert len(bs.drivers) == 1
        assert bs.drivers[0].driven_property == "scale.y"

    def test_unified_skeleton_extras(self, ar15_config):
        assert "ik_hand_root" in ar15_config.unified_skeleton_extra_bones
        assert len(ar15_config.unified_skeleton_extra_bones) == 4

    def test_part_name_aliases(self, ar15_config):
        assert "bcg" in ar15_config.part_name_aliases["bolt_carrier"]
        assert "mag" in ar15_config.part_name_aliases["magazine"]

    def test_physics(self, ar15_config):
        assert ar15_config.physics["bolt_carrier_mass_kg"] == 0.297

    def test_parameters(self, ar15_config):
        bolt = ar15_config.get_bone("bolt")
        assert bolt.parameters["rotation_degrees"] == 20.7
        assert bolt.parameters["lug_count"] == 7

    def test_presence_levels(self, ar15_config):
        root = ar15_config.get_bone("weapon_root")
        assert root.presence == "required"
        selector = ar15_config.get_bone("selector")
        assert selector.presence == "expected"
        dust_cover = ar15_config.get_bone("dust_cover")
        assert dust_cover.presence == "optional"


# ---------------------------------------------------------------------------
# Template config
# ---------------------------------------------------------------------------

class TestTemplateConfig:
    def test_loads_without_error(self, template_config_path):
        # Template has empty operating_system, so from_dict will reject it.
        # We just verify the file is valid JSON and has schema_version.
        import json
        with open(template_config_path) as f:
            data = json.load(f)
        assert data["schema_version"] == "1.0"


# ---------------------------------------------------------------------------
# Config discovery
# ---------------------------------------------------------------------------

class TestConfigDiscovery:
    def test_list_configs_finds_ar15(self):
        configs = WeaponConfig.list_configs()
        identifiers = [c[0] for c in configs]
        assert "ar15_di" in identifiers

    def test_list_configs_skips_template(self):
        configs = WeaponConfig.list_configs()
        identifiers = [c[0] for c in configs]
        assert "_template" not in identifiers
