"""WeaponRig — Guided weapon rigging assistant for FPS games. Single-file addon."""

bl_info = {
    "name": "WeaponRig",
    "author": "Aamir Farrukh",
    "version": (0, 6, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > WeaponRig",
    "description": "Guided weapon rigging assistant for FPS games",
    "category": "Rigging",
}

import fnmatch
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import bpy
import gpu
from bpy_extras.io_utils import ImportHelper
from gpu_extras.batch import batch_for_shader
from mathutils import Vector, kdtree


# ===================================================================
# CONFIG DATABASE (embedded)
# ===================================================================

WEAPON_CONFIGS = {
    "ar15_di": {
        "schema_version": "1.0",
        "operating_system": "ar15_direct_impingement",
        "display_name": "AR-15 Direct Impingement",
        "description": "Stoner gas system with rotating bolt",
        "fire_modes": ["semi", "auto", "burst_3"],
        "cyclic_rate_rpm": {"semi": None, "auto": 700, "burst_3": 900},
        "bones": [
            {
                "name": "Weapon Root",
                "parent": None,
                "presence": "required",
                "movement_type": "static",
                "description": "Lower receiver - root of all weapon bones",
                "placement": "Place at the base of the lower receiver, where the grip meets the frame",
            },
            {
                "name": "Upper Receiver",
                "parent": "Weapon Root",
                "presence": "required",
                "movement_type": "static",
                "description": "Upper receiver - static relative to lower",
                "placement": "Place at the front takedown pin, where upper meets lower receiver",
            },
            {
                "name": "Bolt Carrier",
                "parent": "Upper Receiver",
                "presence": "required",
                "movement_type": "translate",
                "axis": "Y",
                "constraints": [
                    {
                        "type": "LIMIT_LOCATION",
                        "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                        "min_y": -0.095, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                        "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "parameters": {
                    "carrier_travel_m": 0.095,
                    "dwell_before_unlock_m": 0.003,
                    "carrier_mass_kg": 0.297,
                    "buffer_spring_rate_n_per_m": 3500,
                },
                "description": "Bolt carrier group slides rearward under gas pressure, compresses buffer spring, then returns forward to chamber next round",
                "placement": "Place at the rear of the bolt carrier group, centered in the upper receiver channel",
            },
            {
                "name": "Bolt",
                "parent": "Bolt Carrier",
                "presence": "required",
                "movement_type": "rotate",
                "axis": "Y",
                "constraints": [
                    {
                        "type": "LIMIT_ROTATION",
                        "min_y": 0.0,
                        "max_y": 0.361,
                        "use_limit_x": True,
                        "use_limit_y": True,
                        "use_limit_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "drivers": [
                    {
                        "driven_property": "rotation_euler.y",
                        "driver_bone": "Bolt Carrier",
                        "driver_property": "location.y",
                        "expression": "var * -3.8",
                        "description": "Bolt rotates 20.7 degrees as carrier travels back",
                        "cam_curve_keyframes": [
                            {"carrier_travel_pct": 0.0, "bolt_rotation_pct": 0.0},
                            {"carrier_travel_pct": 0.032, "bolt_rotation_pct": 0.0},
                            {"carrier_travel_pct": 0.089, "bolt_rotation_pct": 1.0},
                            {"carrier_travel_pct": 1.0, "bolt_rotation_pct": 1.0},
                        ],
                    }
                ],
                "parameters": {
                    "rotation_degrees": 20.7,
                    "lug_count": 7,
                },
                "description": "Bolt head rotates to lock/unlock from barrel extension. 7 lugs engage at 20.7 degrees rotation",
                "placement": "Place at the bolt face, centered on the bore axis",
            },
            {
                "name": "Trigger",
                "parent": "Weapon Root",
                "presence": "required",
                "movement_type": "rotate",
                "axis": "X",
                "constraints": [
                    {
                        "type": "LIMIT_ROTATION",
                        "min_x": -0.262,
                        "max_x": 0.0,
                        "use_limit_x": True,
                        "use_limit_y": True,
                        "use_limit_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "parameters": {"rotation_degrees": 15.0},
                "description": "Trigger rotates ~15 degrees around the trigger pin. Releases hammer when pulled",
                "placement": "Place at the trigger pin hole center in the lower receiver",
            },
            {
                "name": "Selector",
                "parent": "Weapon Root",
                "presence": "expected",
                "movement_type": "rotate",
                "axis": "Z",
                "constraints": [
                    {
                        "type": "LIMIT_ROTATION",
                        "use_limit_x": True,
                        "use_limit_y": True,
                        "use_limit_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "parameters": {
                    "positions": [
                        {"name": "safe", "angle_degrees": 0},
                        {"name": "semi", "angle_degrees": 90},
                        {"name": "auto", "angle_degrees": 180},
                    ],
                },
                "description": "Fire selector switch. Rotates between Safe (0), Semi (90), and Auto (180) positions",
                "placement": "Place at the selector lever pivot on the left side of the lower receiver, above the grip",
            },
            {
                "name": "Charging Handle",
                "parent": "Upper Receiver",
                "presence": "expected",
                "movement_type": "translate",
                "axis": "Y",
                "constraints": [
                    {
                        "type": "LIMIT_LOCATION",
                        "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                        "min_y": -0.076, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                        "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "description": "Slides rearward 76mm to manually cycle the bolt carrier",
                "placement": "Place at the rear of the upper receiver, centered on top where the charging handle sits",
            },
            {
                "name": "Magazine",
                "parent": None,
                "presence": "required",
                "movement_type": "translate",
                "axis": "Z",
                "description": "Detachable box magazine. Unparented when released for reload animation",
                "placement": "Place at the top of the magazine, where it meets the magazine well",
            },
            {
                "name": "Magazine Release",
                "parent": "Weapon Root",
                "presence": "expected",
                "movement_type": "translate",
                "axis": "X",
                "constraints": [
                    {
                        "type": "LIMIT_LOCATION",
                        "min_x": 0.0, "max_x": 0.003, "use_min_x": True, "use_max_x": True,
                        "min_y": 0.0, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                        "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "description": "Button that releases magazine catch. Pressed inward ~3mm",
                "placement": "Place at the magazine release button on the right side of the lower receiver",
            },
            {
                "name": "Dust Cover",
                "parent": "Upper Receiver",
                "presence": "optional",
                "movement_type": "rotate",
                "axis": "X",
                "constraints": [
                    {
                        "type": "LIMIT_ROTATION",
                        "min_x": 0.0, "max_x": 1.309,
                        "use_limit_x": True, "use_limit_y": True, "use_limit_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "parameters": {"rotation_degrees": 75.0},
                "description": "Ejection port dust cover. Springs open ~75 degrees when bolt cycles",
                "placement": "Place at the dust cover hinge pin on the right side of the upper receiver",
            },
            {
                "name": "Forward Assist",
                "parent": "Upper Receiver",
                "presence": "optional",
                "movement_type": "translate",
                "axis": "Y",
                "constraints": [
                    {
                        "type": "LIMIT_LOCATION",
                        "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                        "min_y": -0.006, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                        "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "description": "Pushes bolt carrier forward to ensure full lockup",
                "placement": "Place at the forward assist button on the right side of the upper receiver",
            },
            {
                "name": "Bolt Catch",
                "parent": "Weapon Root",
                "presence": "optional",
                "movement_type": "rotate",
                "axis": "X",
                "constraints": [
                    {
                        "type": "LIMIT_ROTATION",
                        "min_x": 0.0, "max_x": 0.175,
                        "use_limit_x": True, "use_limit_y": True, "use_limit_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "description": "Holds bolt carrier open after last round",
                "placement": "Place at the bolt catch pivot pin on the left side of the lower receiver",
            },
            {
                "name": "Hammer",
                "parent": "Weapon Root",
                "presence": "optional",
                "movement_type": "rotate",
                "axis": "X",
                "constraints": [
                    {
                        "type": "LIMIT_ROTATION",
                        "min_x": -0.611, "max_x": 0.0,
                        "use_limit_x": True, "use_limit_y": True, "use_limit_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "parameters": {"rotation_degrees": 35.0},
                "description": "Rotates ~35 degrees under spring tension to strike firing pin",
                "placement": "Place at the hammer pin hole center in the lower receiver, behind the trigger",
            },
            {
                "name": "Buffer Spring",
                "parent": "Bolt Carrier",
                "presence": "optional",
                "movement_type": "scale",
                "axis": "Y",
                "drivers": [
                    {
                        "driven_property": "scale.y",
                        "driver_bone": "Bolt Carrier",
                        "driver_property": "location.y",
                        "expression": "1.0 + (var / 0.095) * 0.3",
                        "description": "Buffer spring compresses as carrier moves back",
                    }
                ],
                "description": "Buffer spring in receiver extension. Absorbs carrier energy and returns it forward",
                "placement": "Place inside the buffer tube, at the front of the spring",
            },
            {
                "name": "Cam Pin",
                "parent": "Bolt",
                "presence": "optional",
                "movement_type": "rotate",
                "axis": "Y",
                "description": "Rides in carrier cam track to force bolt rotation",
                "placement": "Place at the cam pin hole in the bolt, perpendicular to the bore axis",
            },
            {
                "name": "Extractor",
                "parent": "Bolt",
                "presence": "optional",
                "movement_type": "rotate",
                "axis": "X",
                "constraints": [
                    {
                        "type": "LIMIT_ROTATION",
                        "min_x": 0.0, "max_x": 0.087,
                        "use_limit_x": True, "use_limit_y": True, "use_limit_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "description": "Spring-loaded claw that grips cartridge rim. Pivots ~5 degrees",
                "placement": "Place at the extractor pivot point on the bolt face",
            },
        ],
        "physics": {
            "gas_impulse_duration_ms": 1.2,
            "carrier_peak_velocity_m_per_s": 5.8,
            "buffer_mass_kg": 0.091,
            "buffer_spring_rate_n_per_m": 3500,
            "return_spring_preload_n": 8.0,
            "bolt_carrier_mass_kg": 0.297,
        },
        "part_name_aliases": {
            "Bolt Carrier": ["*bcg*", "*bolt_carrier*", "*bolt*carrier*", "*carrier*"],
            "Bolt": ["*bolt*head*", "*bolt*face*", "*bolt*"],
            "Trigger": ["*trigger*", "*trig*"],
            "Charging Handle": ["*charging*", "*charge*handle*", "*ch_*", "*cocking*"],
            "Magazine": ["*mag*", "*magazine*", "*clip*"],
            "Selector": ["*selector*", "*safety*", "*fire*select*"],
            "Dust Cover": ["*dust*cover*", "*ejection*cover*", "*port*cover*"],
            "Forward Assist": ["*fwd*assist*", "*forward*assist*"],
            "Hammer": ["*hammer*"],
            "Buffer Spring": ["*buffer*spring*", "*recoil*spring*"],
            "Bolt Catch": ["*bolt*catch*", "*bolt*release*"],
            "Cam Pin": ["*cam*pin*"],
            "Extractor": ["*extractor*"],
            "Magazine Release": ["*mag*release*", "*mag*button*"],
            "Upper Receiver": ["*upper*", "*upper*receiver*"],
            "Weapon Root": ["*lower*", "*lower*receiver*", "*receiver*", "*body*", "*frame*"],
        },
    },
    "ak47_long_stroke": {
        "schema_version": "1.0",
        "operating_system": "ak47_long_stroke_piston",
        "display_name": "AK-47 Long-Stroke Piston",
        "description": "Kalashnikov long-stroke gas piston with rotating bolt",
        "fire_modes": ["semi", "auto"],
        "cyclic_rate_rpm": {"semi": None, "auto": 600},
        "bones": [
            {"name": "Receiver", "parent": None, "presence": "required", "movement_type": "static",
             "description": "Stamped/milled receiver - root of all bones", "placement": "Place at rear trunnion"},
            {"name": "Bolt Carrier", "parent": "Receiver", "presence": "required", "movement_type": "translate", "axis": "Y",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                              "min_y": -0.125, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "parameters": {"carrier_travel_m": 0.125, "carrier_mass_kg": 0.460, "buffer_spring_rate_n_per_m": 2800},
             "description": "Piston and carrier are one piece. Gas drives entire assembly rearward ~125mm",
             "placement": "Place at rear of bolt carrier, centered in receiver channel"},
            {"name": "Bolt", "parent": "Bolt Carrier", "presence": "required", "movement_type": "rotate", "axis": "Y",
             "constraints": [{"type": "LIMIT_ROTATION", "min_y": 0.0, "max_y": 0.611, "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "parameters": {"rotation_degrees": 35.0, "lug_count": 2},
             "description": "Two-lug rotating bolt. Rotates 35 degrees to lock/unlock",
             "placement": "Place at bolt face, centered on bore axis"},
            {"name": "Gas Piston", "parent": "Bolt Carrier", "presence": "required", "movement_type": "static",
             "description": "Integral with bolt carrier (long-stroke). Moves as one unit",
             "placement": "Place at front of gas piston, above barrel at gas block"},
            {"name": "Trigger", "parent": "Receiver", "presence": "required", "movement_type": "rotate", "axis": "X",
             "constraints": [{"type": "LIMIT_ROTATION", "min_x": -0.262, "max_x": 0.0, "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "parameters": {"rotation_degrees": 15.0},
             "description": "Trigger rotates ~15 degrees. Releases hammer",
             "placement": "Place at trigger pin hole in receiver"},
            {"name": "Hammer", "parent": "Receiver", "presence": "required", "movement_type": "rotate", "axis": "X",
             "constraints": [{"type": "LIMIT_ROTATION", "min_x": -0.785, "max_x": 0.0, "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "parameters": {"rotation_degrees": 45.0},
             "description": "Hammer rotates ~45 degrees under spring tension to strike firing pin",
             "placement": "Place at hammer pin hole, behind trigger"},
            {"name": "Safety Selector", "parent": "Receiver", "presence": "required", "movement_type": "rotate", "axis": "Z",
             "constraints": [{"type": "LIMIT_ROTATION", "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "parameters": {"positions": [{"name": "safe", "angle_degrees": 0}, {"name": "auto", "angle_degrees": 90}, {"name": "semi", "angle_degrees": 180}]},
             "description": "Large right-side lever. Up=safe (blocks carrier), middle=auto, down=semi",
             "placement": "Place at selector pivot on right side of receiver"},
            {"name": "Dust Cover", "parent": "Bolt Carrier", "presence": "expected", "movement_type": "static",
             "description": "Reciprocates with bolt carrier via a tab. Covers ejection port",
             "placement": "Place at top of receiver, on dust cover"},
            {"name": "Charging Handle", "parent": "Bolt Carrier", "presence": "expected", "movement_type": "static",
             "description": "Integral with bolt carrier on right side. Reciprocates during firing",
             "placement": "Place at charging handle on right side of bolt carrier"},
            {"name": "Magazine", "parent": None, "presence": "required", "movement_type": "translate", "axis": "Z",
             "description": "Curved 30-round magazine. Rock-and-lock insertion",
             "placement": "Place at top of magazine where it meets magazine well"},
            {"name": "Recoil Spring", "parent": "Bolt Carrier", "presence": "optional", "movement_type": "scale", "axis": "Y",
             "drivers": [{"driven_property": "scale.y", "driver_bone": "Bolt Carrier", "driver_property": "location.y",
                          "expression": "1.0 + (var / 0.125) * 0.35", "description": "Spring compresses as carrier moves back"}],
             "description": "Recoil spring on guide rod inside receiver/stock",
             "placement": "Place at front of recoil spring guide rod"},
        ],
        "physics": {"carrier_mass_kg": 0.460, "buffer_spring_rate_n_per_m": 2800, "gas_impulse_duration_ms": 1.5,
                    "carrier_peak_velocity_m_per_s": 5.2, "bolt_carrier_mass_kg": 0.460},
        "part_name_aliases": {"Bolt Carrier": ["*carrier*", "*bcg*"], "Bolt": ["*bolt*"], "Trigger": ["*trigger*"],
                              "Safety Selector": ["*safety*", "*selector*"], "Magazine": ["*mag*"],
                              "Receiver": ["*receiver*", "*body*"]},
    },
    "glock17_short_recoil": {
        "schema_version": "1.0",
        "operating_system": "glock17_short_recoil",
        "display_name": "Glock 17 Short Recoil",
        "description": "Browning cam-lug short recoil with tilting barrel",
        "fire_modes": ["semi"],
        "cyclic_rate_rpm": {"semi": None},
        "bones": [
            {"name": "Frame", "parent": None, "presence": "required", "movement_type": "static",
             "description": "Polymer frame - root bone. Contains trigger mechanism",
             "placement": "Place at the frame rail, below the barrel"},
            {"name": "Slide", "parent": "Frame", "presence": "required", "movement_type": "translate", "axis": "Y",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                              "min_y": -0.064, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "parameters": {"carrier_travel_m": 0.064, "carrier_mass_kg": 0.130, "buffer_spring_rate_n_per_m": 2200},
             "description": "Slide travels rearward ~64mm. Houses barrel, extractor, striker",
             "placement": "Place at rear of slide"},
            {"name": "Barrel", "parent": "Slide", "presence": "required", "movement_type": "rotate", "axis": "X",
             "constraints": [{"type": "LIMIT_ROTATION", "min_x": -0.070, "max_x": 0.0, "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "parameters": {"rotation_degrees": 4.0},
             "description": "Barrel tilts ~4 degrees down at breech as cam lug rides off frame crosspin",
             "placement": "Place at barrel chamber end, where it locks into slide"},
            {"name": "Trigger", "parent": "Frame", "presence": "required", "movement_type": "rotate", "axis": "X",
             "constraints": [{"type": "LIMIT_ROTATION", "min_x": -0.175, "max_x": 0.0, "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "parameters": {"rotation_degrees": 10.0},
             "description": "Safe Action trigger with center blade safety. ~10 degree pull",
             "placement": "Place at trigger pin in frame"},
            {"name": "Trigger Safety", "parent": "Trigger", "presence": "optional", "movement_type": "rotate", "axis": "X",
             "description": "Center blade that must be depressed before trigger can move",
             "placement": "Place at center of trigger face"},
            {"name": "Striker", "parent": "Slide", "presence": "optional", "movement_type": "translate", "axis": "Y",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                              "min_y": -0.008, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "description": "Partially pre-cocked striker. Trigger completes cocking and releases",
             "placement": "Place at rear of striker channel in slide"},
            {"name": "Slide Stop", "parent": "Frame", "presence": "expected", "movement_type": "rotate", "axis": "X",
             "constraints": [{"type": "LIMIT_ROTATION", "min_x": 0.0, "max_x": 0.175, "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "description": "Holds slide open after last round",
             "placement": "Place at slide stop pivot on left side of frame"},
            {"name": "Magazine", "parent": None, "presence": "required", "movement_type": "translate", "axis": "Z",
             "description": "Double-stack 17-round magazine",
             "placement": "Place at top of magazine where it meets the grip"},
            {"name": "Magazine Release", "parent": "Frame", "presence": "expected", "movement_type": "translate", "axis": "X",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.003, "use_min_x": True, "use_max_x": True,
                              "min_y": 0.0, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "description": "Reversible magazine release button",
             "placement": "Place at magazine release on trigger guard area"},
            {"name": "Extractor", "parent": "Slide", "presence": "optional", "movement_type": "rotate", "axis": "X",
             "constraints": [{"type": "LIMIT_ROTATION", "min_x": 0.0, "max_x": 0.087, "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "description": "Spring-loaded extractor on right side of slide",
             "placement": "Place at extractor claw on slide"},
        ],
        "physics": {"carrier_mass_kg": 0.130, "buffer_spring_rate_n_per_m": 2200, "gas_impulse_duration_ms": 0.8,
                    "carrier_peak_velocity_m_per_s": 7.0, "bolt_carrier_mass_kg": 0.130},
        "part_name_aliases": {"Slide": ["*slide*"], "Barrel": ["*barrel*"], "Frame": ["*frame*", "*lower*", "*grip*"],
                              "Trigger": ["*trigger*"], "Magazine": ["*mag*"], "Striker": ["*striker*", "*firing*pin*"]},
    },
    "mp5_roller_delayed": {
        "schema_version": "1.0",
        "operating_system": "mp5_roller_delayed_blowback",
        "display_name": "MP5 Roller-Delayed Blowback",
        "description": "HK roller-delayed blowback with fluted chamber",
        "fire_modes": ["semi", "auto", "burst_3"],
        "cyclic_rate_rpm": {"semi": None, "auto": 800, "burst_3": 800},
        "bones": [
            {"name": "Receiver", "parent": None, "presence": "required", "movement_type": "static",
             "description": "Stamped steel receiver - root bone",
             "placement": "Place at rear of receiver where stock attaches"},
            {"name": "Bolt Carrier", "parent": "Receiver", "presence": "required", "movement_type": "translate", "axis": "Y",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                              "min_y": -0.105, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "parameters": {"carrier_travel_m": 0.105, "carrier_mass_kg": 0.350, "buffer_spring_rate_n_per_m": 3000},
             "description": "Bolt carrier with locking piece wedge. Moves rearward ~105mm",
             "placement": "Place at rear of bolt carrier assembly"},
            {"name": "Bolt Head", "parent": "Bolt Carrier", "presence": "required", "movement_type": "translate", "axis": "Y",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                              "min_y": -0.004, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "description": "Bolt head moves 4mm before carrier — this is the delay. 4:1 mechanical disadvantage",
             "placement": "Place at bolt face"},
            {"name": "Roller Left", "parent": "Bolt Head", "presence": "optional", "movement_type": "translate", "axis": "X",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": -0.003, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                              "min_y": 0.0, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "description": "Left locking roller. Cammed outward to lock, inward to unlock",
             "placement": "Place at left roller recess in barrel extension"},
            {"name": "Roller Right", "parent": "Bolt Head", "presence": "optional", "movement_type": "translate", "axis": "X",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.003, "use_min_x": True, "use_max_x": True,
                              "min_y": 0.0, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "description": "Right locking roller",
             "placement": "Place at right roller recess"},
            {"name": "Trigger", "parent": "Receiver", "presence": "required", "movement_type": "rotate", "axis": "X",
             "constraints": [{"type": "LIMIT_ROTATION", "min_x": -0.262, "max_x": 0.0, "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "description": "Trigger housed in modular grip/trigger group",
             "placement": "Place at trigger pin in grip frame"},
            {"name": "Cocking Handle", "parent": "Receiver", "presence": "expected", "movement_type": "translate", "axis": "Y",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                              "min_y": -0.080, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "description": "Non-reciprocating cocking handle. Does NOT move during firing",
             "placement": "Place at cocking handle tube on top/left of receiver"},
            {"name": "Selector", "parent": "Receiver", "presence": "expected", "movement_type": "rotate", "axis": "Z",
             "constraints": [{"type": "LIMIT_ROTATION", "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "description": "Fire selector: safe/semi/burst/auto depending on trigger pack",
             "placement": "Place at selector on left side of grip frame"},
            {"name": "Magazine", "parent": None, "presence": "required", "movement_type": "translate", "axis": "Z",
             "description": "Curved 30-round magazine",
             "placement": "Place at top of magazine"},
        ],
        "physics": {"carrier_mass_kg": 0.350, "buffer_spring_rate_n_per_m": 3000, "gas_impulse_duration_ms": 0.0,
                    "carrier_peak_velocity_m_per_s": 4.5, "bolt_carrier_mass_kg": 0.350},
        "part_name_aliases": {"Bolt Carrier": ["*carrier*", "*bolt*"], "Bolt Head": ["*bolt*head*"],
                              "Receiver": ["*receiver*", "*body*"], "Trigger": ["*trigger*"],
                              "Magazine": ["*mag*"], "Cocking Handle": ["*charging*", "*cocking*"]},
    },
    "m1911_short_recoil": {
        "schema_version": "1.0",
        "operating_system": "m1911_short_recoil_link",
        "display_name": "M1911 Short Recoil (Barrel Link)",
        "description": "Browning barrel-link short recoil with exposed hammer",
        "fire_modes": ["semi"],
        "cyclic_rate_rpm": {"semi": None},
        "bones": [
            {"name": "Frame", "parent": None, "presence": "required", "movement_type": "static",
             "description": "Steel frame - root bone",
             "placement": "Place at frame below barrel, at slide stop pin"},
            {"name": "Slide", "parent": "Frame", "presence": "required", "movement_type": "translate", "axis": "Y",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                              "min_y": -0.077, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "parameters": {"carrier_travel_m": 0.077, "carrier_mass_kg": 0.280, "buffer_spring_rate_n_per_m": 2600},
             "description": "Slide travels ~77mm rearward",
             "placement": "Place at rear of slide"},
            {"name": "Barrel", "parent": "Slide", "presence": "required", "movement_type": "rotate", "axis": "X",
             "constraints": [{"type": "LIMIT_ROTATION", "min_x": -0.087, "max_x": 0.0, "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "parameters": {"rotation_degrees": 5.0},
             "description": "Barrel tilts ~5 degrees via barrel link. Steeper than Glock cam-lug",
             "placement": "Place at barrel chamber end"},
            {"name": "Barrel Link", "parent": "Barrel", "presence": "optional", "movement_type": "rotate", "axis": "X",
             "constraints": [{"type": "LIMIT_ROTATION", "min_x": -0.524, "max_x": 0.0, "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "parameters": {"rotation_degrees": 30.0},
             "description": "Swinging arm link (~12mm). Pulls barrel breech down as slide recoils",
             "placement": "Place at barrel link pin under barrel lug"},
            {"name": "Hammer", "parent": "Frame", "presence": "required", "movement_type": "rotate", "axis": "X",
             "constraints": [{"type": "LIMIT_ROTATION", "min_x": -1.047, "max_x": 0.0, "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "parameters": {"rotation_degrees": 60.0},
             "description": "Exposed hammer. Rotates ~60 degrees forward to strike firing pin",
             "placement": "Place at hammer pin in frame"},
            {"name": "Trigger", "parent": "Frame", "presence": "required", "movement_type": "translate", "axis": "Y",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                              "min_y": -0.006, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "description": "Trigger slides straight back ~6mm. Pivoting stirrup releases sear",
             "placement": "Place at trigger bow in frame"},
            {"name": "Grip Safety", "parent": "Frame", "presence": "expected", "movement_type": "rotate", "axis": "X",
             "constraints": [{"type": "LIMIT_ROTATION", "min_x": -0.122, "max_x": 0.0, "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "parameters": {"rotation_degrees": 7.0},
             "description": "Backstrap lever. Must be squeezed ~7 degrees to allow trigger movement",
             "placement": "Place at grip safety pivot at rear of frame"},
            {"name": "Thumb Safety", "parent": "Frame", "presence": "expected", "movement_type": "rotate", "axis": "Z",
             "constraints": [{"type": "LIMIT_ROTATION", "min_z": 0.0, "max_z": 0.785, "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "parameters": {"rotation_degrees": 45.0},
             "description": "Left-side thumb safety. Up=safe (locks sear), down=fire",
             "placement": "Place at thumb safety pivot on left side of frame"},
            {"name": "Slide Stop", "parent": "Frame", "presence": "expected", "movement_type": "rotate", "axis": "X",
             "constraints": [{"type": "LIMIT_ROTATION", "min_x": 0.0, "max_x": 0.175, "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "description": "Holds slide open. Also serves as barrel link pivot pin",
             "placement": "Place at slide stop pin on left side of frame"},
            {"name": "Magazine", "parent": None, "presence": "required", "movement_type": "translate", "axis": "Z",
             "description": "Single-stack 7-round magazine",
             "placement": "Place at top of magazine"},
            {"name": "Magazine Release", "parent": "Frame", "presence": "expected", "movement_type": "translate", "axis": "X",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.003, "use_min_x": True, "use_max_x": True,
                              "min_y": 0.0, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "description": "Button behind trigger guard",
             "placement": "Place at magazine release button"},
        ],
        "physics": {"carrier_mass_kg": 0.280, "buffer_spring_rate_n_per_m": 2600, "gas_impulse_duration_ms": 0.8,
                    "carrier_peak_velocity_m_per_s": 6.5, "bolt_carrier_mass_kg": 0.280},
        "part_name_aliases": {"Slide": ["*slide*"], "Barrel": ["*barrel*"], "Frame": ["*frame*", "*receiver*"],
                              "Trigger": ["*trigger*"], "Hammer": ["*hammer*"], "Magazine": ["*mag*"]},
    },
    "g11_rotary_breech": {
        "schema_version": "1.0",
        "operating_system": "g11_rotary_breech",
        "display_name": "HK G11 Rotary Breech (Caseless)",
        "description": "Rotary breech with Geneva drive, caseless ammo. Most complex infantry weapon ever produced.",
        "fire_modes": ["semi", "auto", "burst_3"],
        "cyclic_rate_rpm": {"semi": None, "auto": 460, "burst_3": 2100},
        "bones": [
            {"name": "Outer Shell", "parent": None, "presence": "required", "movement_type": "static",
             "description": "Outer polymer housing — what the shooter holds. All internal mechanisms float inside",
             "placement": "Place at the center of the outer housing, near the pistol grip"},
            {"name": "Floating Assembly", "parent": "Outer Shell", "presence": "required", "movement_type": "translate", "axis": "Y",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                              "min_y": -0.045, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "parameters": {"assembly_travel_m": 0.045, "assembly_mass_kg": 1.8},
             "description": "Barrel + breech + feed mech slide backward inside shell. In burst mode, fires 3 rounds before hitting buffer — shooter feels recoil only after 3rd round",
             "placement": "Place at the front of the internal mechanism, centered in the outer shell"},
            {"name": "Barrel", "parent": "Floating Assembly", "presence": "required", "movement_type": "static",
             "description": "Fixed relative to floating assembly. Moves with it during recoil",
             "placement": "Place at the chamber end of the barrel"},
            {"name": "Breech Cylinder", "parent": "Floating Assembly", "presence": "required", "movement_type": "rotate", "axis": "Y",
             "constraints": [{"type": "LIMIT_ROTATION", "min_y": 0.0, "max_y": 6.283,
                              "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "parameters": {"mechanism_type": "geneva_drive", "slot_count": 4, "rotation_per_step_degrees": 90, "motion_profile": "snap_dwell"},
             "description": "Rotating cylinder with chamber bored through. Rotates exactly 90 deg per step via 4-slot Geneva mechanism. Positions: feed(0), fire(90), extract(180), clear(270)",
             "placement": "Place at the center of the breech cylinder, on the rotation axis"},
            {"name": "Chamber Insert", "parent": "Breech Cylinder", "presence": "optional", "movement_type": "static",
             "description": "Replaceable chamber piece inside breech cylinder. Rotates with it",
             "placement": "Place inside the breech cylinder bore"},
            {"name": "Gas Piston", "parent": "Floating Assembly", "presence": "required", "movement_type": "translate", "axis": "Y",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                              "min_y": -0.04, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "parameters": {"piston_stroke_m": 0.04},
             "description": "Gas piston driven rearward. Linear stroke converted to breech rotation through gear train (connecting rod > spur gear > actuating gear)",
             "placement": "Place at the gas piston head, above the barrel"},
            {"name": "Connecting Rod", "parent": "Gas Piston", "presence": "expected", "movement_type": "rotate", "axis": "X",
             "constraints": [{"type": "LIMIT_ROTATION", "min_x": -0.524, "max_x": 0.524,
                              "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "description": "Links piston linear motion to spur gear. Pivots ~30 deg each direction",
             "placement": "Place at the pivot connecting piston to spur gear"},
            {"name": "Spur Gear", "parent": "Floating Assembly", "presence": "expected", "movement_type": "rotate", "axis": "X",
             "drivers": [{"driven_property": "rotation_euler.x", "driver_bone": "Gas Piston",
                          "driver_property": "location.y", "expression": "var * -15.0",
                          "description": "Spur gear rotates as gas piston reciprocates"}],
             "description": "Intermediate gear converting connecting rod oscillation to rotation. Meshes with actuating gear",
             "placement": "Place at the spur gear axle"},
            {"name": "Actuating Gear", "parent": "Floating Assembly", "presence": "expected", "movement_type": "rotate", "axis": "X",
             "description": "Final gear meshing with breech cylinder base. Drives Geneva mechanism for 90-deg snap rotations",
             "placement": "Place at the actuating gear axle, adjacent to breech cylinder base"},
            {"name": "Striker", "parent": "Floating Assembly", "presence": "required", "movement_type": "translate", "axis": "Y",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                              "min_y": -0.008, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "description": "Fires the caseless round when breech cylinder aligns with barrel at 90-deg position",
             "placement": "Place at the rear of the breech, on bore axis"},
            {"name": "Cocking Handle", "parent": "Outer Shell", "presence": "expected", "movement_type": "rotate", "axis": "Y",
             "constraints": [{"type": "LIMIT_ROTATION", "min_y": -6.283, "max_y": 0.0,
                              "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "parameters": {"rotation_degrees": 360, "direction": "counterclockwise"},
             "description": "Unique rotary cocking handle — 360 deg counterclockwise rotation to charge. Unlike any other firearm",
             "placement": "Place at the cocking handle axle on the outer shell"},
            {"name": "Toothed Wheel", "parent": "Cocking Handle", "presence": "optional", "movement_type": "rotate", "axis": "Y",
             "description": "Gear wheel driven by cocking handle rotation",
             "placement": "Place on the same axle as cocking handle, inside housing"},
            {"name": "Magazine Follower", "parent": "Floating Assembly", "presence": "optional", "movement_type": "translate", "axis": "Z",
             "description": "Pushes caseless rounds from top-mounted magazine down into breech cylinder feed position",
             "placement": "Place at the top of the magazine feed area"},
            {"name": "Trigger", "parent": "Outer Shell", "presence": "required", "movement_type": "rotate", "axis": "X",
             "constraints": [{"type": "LIMIT_ROTATION", "min_x": -0.262, "max_x": 0.0,
                              "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "description": "Standard trigger — connected to outer shell so feel is consistent regardless of floating assembly position",
             "placement": "Place at the trigger pin in the pistol grip area"},
            {"name": "Selector", "parent": "Outer Shell", "presence": "expected", "movement_type": "rotate", "axis": "Z",
             "constraints": [{"type": "LIMIT_ROTATION", "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "parameters": {"positions": [{"name": "safe", "angle_degrees": 0}, {"name": "semi", "angle_degrees": 90},
                                          {"name": "burst", "angle_degrees": 180}, {"name": "auto", "angle_degrees": 270}]},
             "description": "4-position: Safe, Semi, 3-round Burst (2100 RPM!), Full Auto (460 RPM). Burst fires 3 rounds before shooter feels recoil",
             "placement": "Place at the selector lever on the left side"},
        ],
        "physics": {"gas_impulse_duration_ms": 0.8, "carrier_mass_kg": 1.8, "carrier_peak_velocity_m_per_s": 3.0,
                    "buffer_spring_rate_n_per_m": 5000, "bolt_carrier_mass_kg": 1.8,
                    "burst_rounds_before_buffer": 3, "burst_assembly_travel_m": 0.045},
        "part_name_aliases": {"Outer Shell": ["*housing*", "*shell*", "*body*"], "Floating Assembly": ["*inner*", "*assembly*"],
                              "Breech Cylinder": ["*breech*", "*cylinder*", "*rotary*"], "Gas Piston": ["*piston*"],
                              "Striker": ["*striker*", "*firing*pin*"], "Cocking Handle": ["*cocking*", "*charging*"],
                              "Trigger": ["*trigger*"], "Selector": ["*selector*", "*fire*select*"]},
    },
    "rm277_bullpup": {
        "schema_version": "1.0",
        "operating_system": "rm277_bullpup_sria",
        "display_name": "RM277 Bullpup (SRIA)",
        "description": "General Dynamics / True Velocity bullpup with Short Recoil Impulse Averaging. 75% recoil reduction. Patent US8794121B2.",
        "fire_modes": ["semi", "auto"],
        "cyclic_rate_rpm": {"semi": None, "auto": 550},
        "bones": [
            {"name": "Outer Receiver", "parent": None, "presence": "required", "movement_type": "static",
             "description": "Outer receiver housing — fixed frame the shooter holds. All internal mechanisms float inside on guide rails",
             "placement": "Place at the pistol grip area, center of the outer receiver"},
            {"name": "Barrel Assembly", "parent": "Outer Receiver", "presence": "required", "movement_type": "translate", "axis": "Y",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                              "min_y": -0.014, "max_y": 0.014, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "parameters": {"sria_stroke_m": 0.0137, "barrel_length_mm": 472, "recoil_reduction_percent": 75},
             "description": "Barrel + barrel extension float inside outer receiver. SRIA stroke ±13.7mm. Drive spring pre-loads forward momentum — when round fires, assembly is already moving forward, drastically reducing net rearward impulse",
             "placement": "Place at the barrel extension, where barrel meets the action"},
            {"name": "Barrel", "parent": "Barrel Assembly", "presence": "required", "movement_type": "static",
             "parameters": {"barrel_length_in": 18.6, "caliber": "6.8x51mm TVCM"},
             "description": "18.6 inch barrel with quick-release helical locking lugs. 6.8 TVCM polymer-cased ammo at 65,000 PSI",
             "placement": "Place at the muzzle end of the barrel"},
            {"name": "Gas Accelerator", "parent": "Barrel Assembly", "presence": "required", "movement_type": "translate", "axis": "Y",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                              "min_y": -0.02, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "description": "External poppet-valve gas accelerator — self-cleaning, no gas enters receiver. Simultaneously pushes op-rod rearward AND barrel assembly forward. This dual action is key to SRIA recoil averaging",
             "placement": "Place at the gas port on the barrel"},
            {"name": "Op Rod", "parent": "Barrel Assembly", "presence": "required", "movement_type": "translate", "axis": "Y",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                              "min_y": -0.14, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "parameters": {"stroke_m": 0.14, "stroke_calibers": "19-21"},
             "description": "Operating rod — 140mm stroke. Op-rod cam presses lock block down to unlock bolt. At 3/4 lock block travel, releases firing pin hold cam",
             "placement": "Place at the op-rod head, connected to gas accelerator"},
            {"name": "Lock Block", "parent": "Barrel Assembly", "presence": "required", "movement_type": "translate", "axis": "Z",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                              "min_y": 0.0, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                              "min_z": -0.008, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "drivers": [{"driven_property": "location.z", "driver_bone": "Op Rod", "driver_property": "location.y",
                          "expression": "max(var * 0.4, -0.008)",
                          "description": "Lock block cams downward as op-rod moves rearward. Disengages from barrel extension hold-up cams"}],
             "description": "Vertically-moving lock block with cam shaft. NOT a rotating bolt — tilting/dropping lock block system (patent US8794121B2). Op-rod cam presses it down to unlock",
             "placement": "Place at the lock block between bolt and barrel extension"},
            {"name": "Bolt", "parent": "Barrel Assembly", "presence": "required", "movement_type": "translate", "axis": "Y",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                              "min_y": -0.11, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "parameters": {"stroke_m": 0.11, "stroke_calibers": "15-17"},
             "description": "Bolt translates 110mm rearward after lock block disengages. No rotation. Closed-bolt (semi) / open-bolt (auto) dual-mode firing",
             "placement": "Place at the bolt face, on bore axis behind barrel extension"},
            {"name": "Extractor", "parent": "Bolt", "presence": "optional", "movement_type": "rotate", "axis": "X",
             "constraints": [{"type": "LIMIT_ROTATION", "min_x": 0.0, "max_x": 0.087,
                              "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "description": "Spring-loaded extractor claw on bolt face",
             "placement": "Place at the extractor pivot on the bolt face"},
            {"name": "Firing Pin", "parent": "Bolt", "presence": "optional", "movement_type": "translate", "axis": "Y",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                              "min_y": 0.0, "max_y": 0.004, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "description": "Released by op-rod cam — driven by op-rod momentum, not a hammer. Eliminates need for conventional sear/hammer and bullpup trigger linkage bar",
             "placement": "Place at the firing pin tip, centered on bolt face bore axis"},
            {"name": "Hydraulic Buffer", "parent": "Barrel Assembly", "presence": "expected", "movement_type": "scale", "axis": "Y",
             "drivers": [{"driven_property": "scale.y", "driver_bone": "Barrel Assembly", "driver_property": "location.y",
                          "expression": "1.0 - abs(var) / 0.014 * 0.2",
                          "description": "Hydraulic buffer compresses as barrel assembly moves. Velocity-dependent damping"}],
             "description": "Hydraulic buffer with centering spring and piston. Velocity-dependent resistance — higher speed = more resistance. Key to SRIA impulse averaging",
             "placement": "Place at the buffer piston, between barrel extension and outer receiver"},
            {"name": "Trigger", "parent": "Outer Receiver", "presence": "required", "movement_type": "rotate", "axis": "X",
             "constraints": [{"type": "LIMIT_ROTATION", "min_x": -0.262, "max_x": 0.0,
                              "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "description": "No transfer bar needed — op-rod cam system handles firing pin release, giving cleaner trigger pull than typical bullpups",
             "placement": "Place at the trigger pin in the pistol grip area"},
            {"name": "Selector", "parent": "Outer Receiver", "presence": "expected", "movement_type": "rotate", "axis": "Z",
             "constraints": [{"type": "LIMIT_ROTATION", "use_limit_x": True, "use_limit_y": True, "use_limit_z": True, "owner_space": "LOCAL"}],
             "parameters": {"positions": [{"name": "safe", "angle_degrees": 0}, {"name": "semi", "angle_degrees": 90}, {"name": "auto", "angle_degrees": 180}],
                            "dual_mode": "Closed bolt (semi) / Open bolt (auto)"},
             "description": "Ambidextrous selector. Semi fires from closed bolt (accuracy). Auto fires from open bolt (prevents cook-off). AR-15 compatible grip",
             "placement": "Place at the selector lever above the pistol grip"},
            {"name": "Charging Handle", "parent": "Outer Receiver", "presence": "expected", "movement_type": "translate", "axis": "Y",
             "constraints": [{"type": "LIMIT_LOCATION", "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                              "min_y": -0.11, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                              "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True, "owner_space": "LOCAL"}],
             "description": "Non-reciprocating, switchable to either side. Does not move during firing",
             "placement": "Place at the charging handle, above the barrel"},
            {"name": "Magazine", "parent": None, "presence": "required", "movement_type": "translate", "axis": "Z",
             "description": "Rear-mounted (bullpup). 20-round Lancer mag. 6.8 TVCM polymer-cased ammo — 30-40% lighter than brass",
             "placement": "Place at the top of the magazine, where it seats behind the grip"},
        ],
        "physics": {"carrier_mass_kg": 0.25, "buffer_spring_rate_n_per_m": 4000, "gas_impulse_duration_ms": 1.0,
                    "carrier_peak_velocity_m_per_s": 5.0, "bolt_carrier_mass_kg": 0.25,
                    "sria_barrel_stroke_m": 0.0137, "sria_recoil_reduction": 0.75},
        "part_name_aliases": {"Outer Receiver": ["*receiver*", "*housing*", "*frame*"], "Barrel Assembly": ["*barrel*assembly*", "*inner*"],
                              "Gas Accelerator": ["*gas*", "*poppet*"], "Op Rod": ["*op*rod*", "*operating*rod*"],
                              "Lock Block": ["*lock*block*", "*locking*"], "Bolt": ["*bolt*"],
                              "Charging Handle": ["*charging*", "*ch*"], "Magazine": ["*mag*"]},
    },
}


# ===================================================================
# SCHEMA
# ===================================================================

VALID_CONSTRAINT_TYPES = {
    "LIMIT_ROTATION", "LIMIT_LOCATION", "COPY_ROTATION", "TRACK_TO", "STRETCH_TO",
}


@dataclass
class ConstraintDef:
    type: str
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
    target: Optional[str] = None
    subtarget: Optional[str] = None
    use_x: bool = True
    use_y: bool = True
    use_z: bool = True
    mix_mode: str = "REPLACE"
    target_space: str = "LOCAL"
    track_axis: str = "TRACK_NEGATIVE_Y"
    up_axis: str = "UP_Z"
    rest_length: float = 0.0
    influence: float = 1.0

    @classmethod
    def from_dict(cls, d: dict) -> "ConstraintDef":
        if d.get("type") not in VALID_CONSTRAINT_TYPES:
            raise ValueError(f"Unknown constraint type: {d.get('type')!r}")
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class CamCurveKeyframe:
    carrier_travel_pct: float
    bolt_rotation_pct: float

    @classmethod
    def from_dict(cls, d: dict) -> "CamCurveKeyframe":
        return cls(d["carrier_travel_pct"], d["bolt_rotation_pct"])


@dataclass
class DriverDef:
    driven_property: str
    driver_bone: str
    driver_property: str
    expression: Optional[str] = None
    description: Optional[str] = None
    source: Optional[str] = None
    cam_curve_keyframes: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "DriverDef":
        kfs = [CamCurveKeyframe.from_dict(kf) for kf in d.get("cam_curve_keyframes", [])]
        return cls(
            driven_property=d["driven_property"],
            driver_bone=d["driver_bone"],
            driver_property=d["driver_property"],
            expression=d.get("expression"),
            description=d.get("description"),
            source=d.get("source"),
            cam_curve_keyframes=kfs,
        )


@dataclass
class BoneDef:
    name: str
    parent: Optional[str] = None
    presence: str = "required"
    movement_type: str = "static"
    axis: Optional[str] = None
    description: Optional[str] = None
    placement: Optional[str] = None
    constraints: list = field(default_factory=list)
    drivers: list = field(default_factory=list)
    parameters: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "BoneDef":
        name = d.get("name")
        if not name:
            raise ValueError("Bone missing 'name'")
        return cls(
            name=name,
            parent=d.get("parent"),
            presence=d.get("presence", "required"),
            movement_type=d.get("movement_type", "static"),
            axis=d.get("axis"),
            description=d.get("description"),
            placement=d.get("placement"),
            constraints=[ConstraintDef.from_dict(c) for c in d.get("constraints", [])],
            drivers=[DriverDef.from_dict(dr) for dr in d.get("drivers", [])],
            parameters=d.get("parameters", {}),
        )


@dataclass
class WeaponConfig:
    schema_version: str
    operating_system: str
    display_name: str
    description: str = ""
    fire_modes: list = field(default_factory=list)
    cyclic_rate_rpm: dict = field(default_factory=dict)
    bones: list = field(default_factory=list)
    physics: dict = field(default_factory=dict)
    part_name_aliases: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "WeaponConfig":
        bones = [BoneDef.from_dict(b) for b in d.get("bones", [])]
        return cls(
            schema_version=d.get("schema_version", "1.0"),
            operating_system=d["operating_system"],
            display_name=d.get("display_name", d["operating_system"]),
            description=d.get("description", ""),
            fire_modes=d.get("fire_modes", []),
            cyclic_rate_rpm=d.get("cyclic_rate_rpm", {}),
            bones=bones,
            physics=d.get("physics", {}),
            part_name_aliases=d.get("part_name_aliases", {}),
        )

    def get_bone(self, name: str) -> Optional[BoneDef]:
        for b in self.bones:
            if b.name == name:
                return b
        return None


# ===================================================================
# WIDGET SHAPES (custom bone display)
# ===================================================================

_WGT_COLLECTION_NAME = "WGT_WeaponRig"


def _get_widget_collection():
    """Get or create hidden collection for widget meshes."""
    col = bpy.data.collections.get(_WGT_COLLECTION_NAME)
    if col is None:
        col = bpy.data.collections.new(_WGT_COLLECTION_NAME)
        bpy.context.scene.collection.children.link(col)
    col.hide_viewport = True
    col.hide_render = True
    return col


def _create_arrow_widget():
    """Arrow shape for translation bones."""
    name = "WGT_arrow"
    if name in bpy.data.objects:
        return bpy.data.objects[name]
    import bmesh
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    # Shaft
    v1 = bm.verts.new((-0.015, 0.0, 0.0))
    v2 = bm.verts.new((0.015, 0.0, 0.0))
    v3 = bm.verts.new((0.015, 0.8, 0.0))
    v4 = bm.verts.new((-0.015, 0.8, 0.0))
    bm.faces.new((v1, v2, v3, v4))
    # Arrowhead
    v5 = bm.verts.new((-0.04, 0.8, 0.0))
    v6 = bm.verts.new((0.04, 0.8, 0.0))
    v7 = bm.verts.new((0.0, 1.0, 0.0))
    bm.faces.new((v5, v6, v7))
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    _get_widget_collection().objects.link(obj)
    return obj


def _create_arc_widget():
    """Arc shape for rotation bones."""
    name = "WGT_arc"
    if name in bpy.data.objects:
        return bpy.data.objects[name]
    import bmesh
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    segments = 16
    radius = 0.5
    angle = math.radians(90)
    verts = []
    for i in range(segments + 1):
        t = -angle / 2 + angle * i / segments
        x = math.cos(t) * radius
        y = math.sin(t) * radius
        verts.append(bm.verts.new((x, y, 0)))
    for i in range(segments):
        bm.edges.new((verts[i], verts[i + 1]))
    # Arrowhead at tip
    tip = verts[-1]
    t_end = -angle / 2 + angle
    dx = -math.sin(t_end) * 0.08
    dy = math.cos(t_end) * 0.08
    a1 = bm.verts.new((tip.co.x + dx + dy * 0.3, tip.co.y + dy - dx * 0.3, 0))
    a2 = bm.verts.new((tip.co.x + dx - dy * 0.3, tip.co.y + dy + dx * 0.3, 0))
    bm.edges.new((tip, a1))
    bm.edges.new((tip, a2))
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    _get_widget_collection().objects.link(obj)
    return obj


def _create_cube_widget():
    """Cube wireframe for static bones."""
    name = "WGT_cube"
    if name in bpy.data.objects:
        return bpy.data.objects[name]
    import bmesh
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    s = 0.3
    verts = [
        bm.verts.new((-s, -s, -s)), bm.verts.new((s, -s, -s)),
        bm.verts.new((s, s, -s)), bm.verts.new((-s, s, -s)),
        bm.verts.new((-s, -s, s)), bm.verts.new((s, -s, s)),
        bm.verts.new((s, s, s)), bm.verts.new((-s, s, s)),
    ]
    edges = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
    for a, b in edges:
        bm.edges.new((verts[a], verts[b]))
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    _get_widget_collection().objects.link(obj)
    return obj


def _assign_bone_shape(armature_obj, bone_def, context=None):
    """Assign custom shape to a pose bone based on its movement type."""
    convention = context.scene.get("weaponrig_naming", "TITLE") if context else "TITLE"
    display_name = _format_bone_name(bone_def.name, convention)
    pose_bone = armature_obj.pose.bones.get(display_name)
    if pose_bone is None:
        return
    if bone_def.movement_type == "translate":
        pose_bone.custom_shape = _create_arrow_widget()
    elif bone_def.movement_type in ("rotate", "scale"):
        pose_bone.custom_shape = _create_arc_widget()
    elif bone_def.movement_type == "static":
        pose_bone.custom_shape = _create_cube_widget()
    if pose_bone.custom_shape:
        pose_bone.custom_shape_scale_xyz = (3.0, 3.0, 3.0)
        pose_bone.use_custom_shape_bone_size = True


# ===================================================================
# SKELETON BUILDER
# ===================================================================

AXIS_VECTORS = {
    "X": Vector((0.05, 0, 0)),
    "Y": Vector((0, 0.05, 0)),
    "Z": Vector((0, 0, 0.05)),
    "-X": Vector((-0.05, 0, 0)),
    "-Y": Vector((0, -0.05, 0)),
    "-Z": Vector((0, 0, -0.05)),
}
DEFAULT_TAIL = Vector((0, 0.05, 0))


def _orient_bone(eb, bone_def):
    """Orient bone based on its movement type so LOCAL-space constraints work correctly.

    - translate: Y-axis along travel direction, Z-up
    - rotate/scale: Y-axis along rotation axis, Z-up
    - static: default Y-up, Z toward world Z
    """
    _axis_map = {
        "X": Vector((1, 0, 0)), "Y": Vector((0, 1, 0)), "Z": Vector((0, 0, 1)),
        "-X": Vector((-1, 0, 0)), "-Y": Vector((0, -1, 0)), "-Z": Vector((0, 0, -1)),
    }
    axis_vec = _axis_map.get(bone_def.axis, Vector((0, 1, 0)))
    length = 0.05

    if bone_def.movement_type == "translate":
        eb.tail = eb.head + axis_vec.normalized() * length
    elif bone_def.movement_type in ("rotate", "scale"):
        eb.tail = eb.head + axis_vec.normalized() * length
    else:
        eb.tail = eb.head + Vector((0, 0.05, 0))

    # Set roll so Z-axis points up (or closest to up given the bone direction)
    up = Vector((0, 0, 1))
    bone_y = (eb.tail - eb.head).normalized()
    if abs(bone_y.dot(up)) > 0.99:
        up = Vector((0, 1, 0))
    eb.align_roll(up)


def _format_bone_name(name, convention="TITLE"):
    """Convert Title Case bone name to the selected naming convention."""
    words = name.split()
    if convention == "SNAKE":
        return "_".join(w.lower() for w in words)
    elif convention == "PASCAL":
        return "".join(w.capitalize() for w in words)
    elif convention == "UPPER_SNAKE":
        return "_".join(w.upper() for w in words)
    return name  # TITLE = as-is


def get_or_create_armature(context):
    """Return the active WeaponRig armature, or create one."""
    active = context.active_object
    if active and active.type == "ARMATURE" and active.get("weaponrig"):
        return active

    for obj in context.scene.objects:
        if obj.type == "ARMATURE" and obj.get("weaponrig"):
            return obj

    arm_data = bpy.data.armatures.new("WeaponRig")
    arm_obj = bpy.data.objects.new("WeaponRig", arm_data)
    context.collection.objects.link(arm_obj)
    arm_obj["weaponrig"] = True
    # Auto In Front so bones are visible through mesh
    arm_obj.show_in_front = True
    arm_data.display_type = "STICK"
    return arm_obj


def add_single_bone(config, bone_name, armature_obj, position, context):
    """Add one bone to the armature at the given position."""
    bone_def = config.get_bone(bone_name)
    if bone_def is None:
        return {"error": f"No bone '{bone_name}' in config"}

    if bone_name in [b.name for b in armature_obj.data.bones]:
        return {"error": f"Bone '{bone_name}' already exists"}

    if context.object and context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    context.view_layer.objects.active = armature_obj
    armature_obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    # Apply naming convention
    display_name = _format_bone_name(bone_def.name, context.scene.get("weaponrig_naming", "TITLE"))
    eb = armature_obj.data.edit_bones.new(display_name)
    eb.head = position.copy()

    # Orient bone based on movement type (critical for LOCAL-space constraints)
    _orient_bone(eb, bone_def)

    if bone_def.parent:
        parent_name = _format_bone_name(bone_def.parent, context.scene.get("weaponrig_naming", "TITLE"))
        parent_eb = armature_obj.data.edit_bones.get(parent_name)
        if parent_eb:
            eb.parent = parent_eb
            eb.use_connect = False

    bpy.ops.object.mode_set(mode="OBJECT")

    info = {
        "name": display_name,
        "parent": bone_def.parent,
        "movement": bone_def.movement_type,
        "axis": bone_def.axis,
        "constraints_added": 0,
        "drivers_added": 0,
        "description": bone_def.description or "",
    }

    info["constraints_added"] = _apply_bone_constraints(armature_obj, bone_def, context)
    info["drivers_added"] = _apply_bone_drivers(armature_obj, bone_def, context)
    _assign_bone_shape(armature_obj, bone_def, context)

    # Force depsgraph to recognize new constraints/drivers
    armature_obj.update_tag()
    context.view_layer.update()

    return info


# ===================================================================
# CONSTRAINT BUILDER
# ===================================================================

def _apply_bone_constraints(arm_obj, bone_def, context=None):
    if not bone_def.constraints:
        return 0
    convention = context.scene.get("weaponrig_naming", "TITLE") if context else "TITLE"
    display_name = _format_bone_name(bone_def.name, convention)
    pose_bone = arm_obj.pose.bones.get(display_name)
    if pose_bone is None:
        return 0
    count = 0
    for cdef in bone_def.constraints:
        con = pose_bone.constraints.new(type=cdef.type)

        if cdef.type == "LIMIT_ROTATION":
            con.owner_space = cdef.owner_space
            con.use_limit_x = cdef.use_limit_x
            con.use_limit_y = cdef.use_limit_y
            con.use_limit_z = cdef.use_limit_z
            if cdef.use_limit_x:
                con.min_x = min(cdef.min_x, cdef.max_x)
                con.max_x = max(cdef.min_x, cdef.max_x)
            if cdef.use_limit_y:
                con.min_y = min(cdef.min_y, cdef.max_y)
                con.max_y = max(cdef.min_y, cdef.max_y)
            if cdef.use_limit_z:
                con.min_z = min(cdef.min_z, cdef.max_z)
                con.max_z = max(cdef.min_z, cdef.max_z)

        elif cdef.type == "LIMIT_LOCATION":
            con.owner_space = cdef.owner_space
            con.use_min_x = cdef.use_min_x
            con.use_max_x = cdef.use_max_x
            con.use_min_y = cdef.use_min_y
            con.use_max_y = cdef.use_max_y
            con.use_min_z = cdef.use_min_z
            con.use_max_z = cdef.use_max_z
            con.min_x = min(cdef.min_x, cdef.max_x)
            con.max_x = max(cdef.min_x, cdef.max_x)
            con.min_y = min(cdef.min_y, cdef.max_y)
            con.max_y = max(cdef.min_y, cdef.max_y)
            con.min_z = min(cdef.min_z, cdef.max_z)
            con.max_z = max(cdef.min_z, cdef.max_z)

        elif cdef.type == "COPY_ROTATION":
            con.target = arm_obj
            if cdef.subtarget:
                con.subtarget = cdef.subtarget
            con.use_x = cdef.use_x
            con.use_y = cdef.use_y
            con.use_z = cdef.use_z
            con.mix_mode = cdef.mix_mode
            con.target_space = cdef.target_space
            con.owner_space = cdef.owner_space

        elif cdef.type == "TRACK_TO":
            con.target = arm_obj
            if cdef.subtarget:
                con.subtarget = cdef.subtarget
            con.track_axis = cdef.track_axis
            con.up_axis = cdef.up_axis

        elif cdef.type == "STRETCH_TO":
            con.target = arm_obj
            if cdef.subtarget:
                con.subtarget = cdef.subtarget
            con.rest_length = cdef.rest_length

        con.influence = cdef.influence
        count += 1
    return count


# ===================================================================
# DRIVER BUILDER
# ===================================================================

_PROPERTY_TO_TRANSFORM = {
    "location.x": "LOC_X", "location.y": "LOC_Y", "location.z": "LOC_Z",
    "rotation_euler.x": "ROT_X", "rotation_euler.y": "ROT_Y", "rotation_euler.z": "ROT_Z",
    "scale.x": "SCALE_X", "scale.y": "SCALE_Y", "scale.z": "SCALE_Z",
}
_AXIS_INDEX = {"x": 0, "y": 1, "z": 2, "w": 3}


def _parse_prop(prop):
    parts = prop.rsplit(".", 1)
    return parts[0], _AXIS_INDEX[parts[1]]


def _apply_bone_drivers(arm_obj, bone_def, context=None):
    if not bone_def.drivers:
        return 0
    convention = context.scene.get("weaponrig_naming", "TITLE") if context else "TITLE"
    display_name = _format_bone_name(bone_def.name, convention)
    pose_bone = arm_obj.pose.bones.get(display_name)
    if pose_bone is None:
        return 0
    count = 0
    for ddef in bone_def.drivers:
        # Check driver bone exists before creating driver
        driver_display = _format_bone_name(ddef.driver_bone, convention)
        if driver_display not in arm_obj.pose.bones:
            continue  # Skip driver if target bone missing

        data_path, axis_idx = _parse_prop(ddef.driven_property)
        fcurve = pose_bone.driver_add(data_path, axis_idx)
        driver = fcurve.driver
        driver.type = "SCRIPTED"

        var = driver.variables.new()
        var.name = "var"
        var.type = "TRANSFORMS"
        tgt = var.targets[0]
        tgt.id = arm_obj
        tgt.bone_target = driver_display
        tgt.transform_type = _PROPERTY_TO_TRANSFORM[ddef.driver_property]
        tgt.transform_space = "LOCAL_SPACE"

        if ddef.cam_curve_keyframes:
            driver.expression = "var"
            travel = bone_def.parameters.get("carrier_travel_m", 1.0)
            rot_deg = bone_def.parameters.get("rotation_degrees", 1.0)
            rot_rad = math.radians(rot_deg)
            sorted_kfs = sorted(ddef.cam_curve_keyframes, key=lambda k: k.carrier_travel_pct)
            while fcurve.keyframe_points:
                fcurve.keyframe_points.remove(fcurve.keyframe_points[0])
            for kf in sorted_kfs:
                pt = fcurve.keyframe_points.insert(kf.carrier_travel_pct * travel, kf.bolt_rotation_pct * rot_rad)
                pt.interpolation = "LINEAR"
        else:
            driver.expression = ddef.expression or "var"

        count += 1
    return count


# ===================================================================
# FIRING CYCLE SLIDER
# ===================================================================

def _update_cycle_progress(self, context):
    """Drive all bone transforms based on cycle progress slider."""
    arm_obj = None
    for obj in context.scene.objects:
        if obj.type == "ARMATURE" and obj.get("weaponrig"):
            arm_obj = obj
            break
    if arm_obj is None:
        return

    weapon_type = context.scene.weaponrig_weapon_type
    if weapon_type not in WEAPON_CONFIGS:
        return
    config = WeaponConfig.from_dict(WEAPON_CONFIGS[weapon_type])
    progress = self.cycle_progress
    added = set(_get_added_list(context))

    for bone_def in config.bones:
        if bone_def.name not in added:
            continue
        pose_bone = arm_obj.pose.bones.get(bone_def.name)
        if pose_bone is None:
            continue

        axis_idx = _AXIS_INDEX.get(bone_def.axis.lower(), 1) if bone_def.axis else 1

        if bone_def.movement_type == "translate" and bone_def.constraints:
            for cdef in bone_def.constraints:
                if cdef.type == "LIMIT_LOCATION":
                    travel_min = getattr(cdef, f"min_{bone_def.axis.lower()}", 0.0)
                    travel_max = getattr(cdef, f"max_{bone_def.axis.lower()}", 0.0)
                    travel = min(travel_min, travel_max)  # negative = rearward
                    loc = [0.0, 0.0, 0.0]
                    loc[axis_idx] = travel * progress
                    pose_bone.location = Vector(loc)
                    break

        elif bone_def.movement_type == "rotate" and bone_def.constraints:
            for cdef in bone_def.constraints:
                if cdef.type == "LIMIT_ROTATION":
                    rot_min = getattr(cdef, f"min_{bone_def.axis.lower()}", 0.0)
                    rot_max = getattr(cdef, f"max_{bone_def.axis.lower()}", 0.0)
                    rot_range = rot_max - rot_min if abs(rot_max - rot_min) > 0.001 else rot_min
                    rot = [0.0, 0.0, 0.0]
                    rot[axis_idx] = rot_range * progress
                    pose_bone.rotation_mode = "XYZ"
                    pose_bone.rotation_euler = rot
                    break

        elif bone_def.movement_type == "scale" and bone_def.drivers:
            for ddef in bone_def.drivers:
                if "scale" in ddef.driven_property:
                    # Evaluate expression with var = simulated driver input
                    driver_bone_def = config.get_bone(ddef.driver_bone)
                    if driver_bone_def and driver_bone_def.constraints:
                        for dc in driver_bone_def.constraints:
                            if dc.type == "LIMIT_LOCATION":
                                axis_l = driver_bone_def.axis.lower() if driver_bone_def.axis else "y"
                                travel = min(getattr(dc, f"min_{axis_l}", 0), getattr(dc, f"max_{axis_l}", 0))
                                var = travel * progress
                                try:
                                    scale_val = eval(ddef.expression, {"var": var, "abs": abs, "math": math})
                                except Exception:
                                    scale_val = 1.0
                                s_idx = _AXIS_INDEX.get(ddef.driven_property.rsplit(".", 1)[1], 1)
                                scale = [1.0, 1.0, 1.0]
                                scale[s_idx] = scale_val
                                pose_bone.scale = Vector(scale)
                                break

    context.view_layer.update()
    for area in context.screen.areas:
        if area.type == "VIEW_3D":
            area.tag_redraw()


class WeaponRigProperties(bpy.types.PropertyGroup):
    cycle_progress: bpy.props.FloatProperty(
        name="Cycle Progress",
        description="Simulate the weapon firing cycle (0% = rest, 100% = full travel)",
        min=0.0, max=1.0,
        default=0.0,
        subtype="FACTOR",
        update=_update_cycle_progress,
    )


# ===================================================================
# CONSTRAINT RANGE VISUALIZATION (GPU overlay)
# ===================================================================

_draw_handler = None


def _draw_constraint_ranges():
    """Draw travel lines and rotation arcs for weapon bones."""
    context = bpy.context
    obj = context.active_object
    if not obj or obj.type != "ARMATURE" or not obj.get("weaponrig"):
        return
    if obj.mode != "POSE":
        return

    weapon_type = context.scene.weaponrig_weapon_type
    if weapon_type not in WEAPON_CONFIGS:
        return
    config = WeaponConfig.from_dict(WEAPON_CONFIGS[weapon_type])
    added = set(_get_added_list(context))

    all_coords = []
    all_colors = []

    for bone_def in config.bones:
        if bone_def.name not in added or not bone_def.constraints:
            continue
        pose_bone = obj.pose.bones.get(bone_def.name)
        if pose_bone is None:
            continue

        bone_mat = obj.matrix_world @ pose_bone.matrix
        head_world = bone_mat.translation

        for cdef in bone_def.constraints:
            if cdef.type == "LIMIT_LOCATION" and bone_def.axis:
                axis_l = bone_def.axis.lower()
                travel_min = min(getattr(cdef, f"min_{axis_l}", 0), getattr(cdef, f"max_{axis_l}", 0))
                travel_max = max(getattr(cdef, f"min_{axis_l}", 0), getattr(cdef, f"max_{axis_l}", 0))

                axis_vec = bone_mat.to_3x3() @ Vector(
                    (1 if bone_def.axis == "X" else 0,
                     1 if bone_def.axis == "Y" else 0,
                     1 if bone_def.axis == "Z" else 0)
                )

                start = head_world + axis_vec * travel_min
                end = head_world + axis_vec * travel_max

                all_coords.extend([start, end])
                all_colors.extend([
                    (0.0, 1.0, 0.3, 0.8),  # green at rest
                    (1.0, 0.2, 0.1, 0.8),  # red at limit
                ])

            elif cdef.type == "LIMIT_ROTATION" and bone_def.axis:
                axis_l = bone_def.axis.lower()
                rot_min = min(getattr(cdef, f"min_{axis_l}", 0), getattr(cdef, f"max_{axis_l}", 0))
                rot_max = max(getattr(cdef, f"min_{axis_l}", 0), getattr(cdef, f"max_{axis_l}", 0))

                if abs(rot_max - rot_min) < 0.001:
                    continue

                # Draw arc segments
                segments = 12
                radius = 0.03
                bone_rot = bone_mat.to_3x3()

                if bone_def.axis == "X":
                    fwd = bone_rot @ Vector((0, 1, 0))
                    up = bone_rot @ Vector((0, 0, 1))
                elif bone_def.axis == "Y":
                    fwd = bone_rot @ Vector((1, 0, 0))
                    up = bone_rot @ Vector((0, 0, 1))
                else:
                    fwd = bone_rot @ Vector((1, 0, 0))
                    up = bone_rot @ Vector((0, 1, 0))

                for i in range(segments):
                    t0 = rot_min + (rot_max - rot_min) * i / segments
                    t1 = rot_min + (rot_max - rot_min) * (i + 1) / segments
                    p0 = head_world + (fwd * math.cos(t0) + up * math.sin(t0)) * radius
                    p1 = head_world + (fwd * math.cos(t1) + up * math.sin(t1)) * radius
                    all_coords.extend([p0, p1])
                    frac = i / segments
                    c = (frac, 1.0 - frac, 0.2, 0.8)
                    all_colors.extend([c, c])

    if not all_coords:
        return

    try:
        shader = gpu.shader.from_builtin("SMOOTH_COLOR")
    except Exception:
        shader = gpu.shader.from_builtin("POLYLINE_SMOOTH_COLOR")

    batch = batch_for_shader(shader, "LINES", {"pos": all_coords, "color": all_colors})
    gpu.state.blend_set("ALPHA")
    gpu.state.line_width_set(2.0)
    shader.bind()
    batch.draw(shader)
    gpu.state.blend_set("NONE")
    gpu.state.line_width_set(1.0)


# ===================================================================
# AUTO-DETECT MESH PARTS
# ===================================================================

def _find_mesh_matches(config):
    """Match scene mesh objects to config bone names. Returns dict {bone_name: obj}."""
    mesh_objects = [o for o in bpy.data.objects if o.type == "MESH"]
    matches = {}

    for bone_def in config.bones:
        # Try exact name match first
        for obj in mesh_objects:
            obj_lower = obj.name.lower().replace(" ", "_").replace("-", "_")
            bone_lower = bone_def.name.lower().replace(" ", "_")
            if obj_lower == bone_lower:
                matches[bone_def.name] = obj
                break
        else:
            # Try alias patterns
            aliases = config.part_name_aliases.get(bone_def.name, [])
            for pattern in aliases:
                for obj in mesh_objects:
                    if fnmatch.fnmatch(obj.name.lower(), pattern.lower()):
                        if bone_def.name not in matches:
                            matches[bone_def.name] = obj
                            break
                if bone_def.name in matches:
                    break

    return matches


def _obj_centroid(obj):
    """Get world-space centroid of a mesh object."""
    bb = obj.bound_box
    local_center = sum((Vector(corner) for corner in bb), Vector()) / 8
    return obj.matrix_world @ local_center


# ===================================================================
# OPERATORS
# ===================================================================

class WEAPONRIG_OT_add_bone(bpy.types.Operator):
    """Add the next weapon bone at the 3D cursor position"""
    bl_idname = "weaponrig.add_bone"
    bl_label = "Add Bone"
    bl_options = {"REGISTER", "UNDO"}

    bone_name: bpy.props.StringProperty(name="Bone Name")
    use_selection: bpy.props.BoolProperty(name="Use Selection", default=False)

    def execute(self, context):
        weapon_type = context.scene.weaponrig_weapon_type
        if weapon_type not in WEAPON_CONFIGS:
            self.report({"ERROR"}, f"Unknown weapon type: {weapon_type}")
            return {"CANCELLED"}

        config = WeaponConfig.from_dict(WEAPON_CONFIGS[weapon_type])

        bone_name = self.bone_name
        if not bone_name:
            added = set(_get_added_list(context))
            for b in config.bones:
                if b.name not in added:
                    bone_name = b.name
                    break
            if not bone_name:
                self.report({"INFO"}, "All bones have been added")
                return {"CANCELLED"}

        if self.use_selection:
            position = _selection_centroid(context)
            if position is None:
                self.report({"WARNING"}, "No selection found, using 3D cursor")
                position = context.scene.cursor.location.copy()
        else:
            position = context.scene.cursor.location.copy()

        arm_obj = get_or_create_armature(context)
        info = add_single_bone(config, bone_name, arm_obj, position, context)

        if "error" in info:
            self.report({"ERROR"}, info["error"])
            return {"CANCELLED"}

        added = _get_added_list(context)
        if bone_name not in added:
            added.append(bone_name)
            context.scene.weaponrig_added_bones = json.dumps(added)

        msg = f"Added: {info['name']}"
        if info.get("constraints_added"):
            msg += f" ({info['constraints_added']} constraints)"
        if info.get("drivers_added"):
            msg += f" ({info['drivers_added']} drivers)"
        self.report({"INFO"}, msg)

        context.view_layer.objects.active = arm_obj
        arm_obj.select_set(True)
        return {"FINISHED"}


class WEAPONRIG_OT_select_bone(bpy.types.Operator):
    """Select a bone in the armature"""
    bl_idname = "weaponrig.select_bone"
    bl_label = "Select Bone"

    bone_name: bpy.props.StringProperty(name="Bone Name")

    def execute(self, context):
        arm_obj = None
        for obj in context.scene.objects:
            if obj.type == "ARMATURE" and obj.get("weaponrig"):
                arm_obj = obj
                break
        if arm_obj is None:
            self.report({"WARNING"}, "No WeaponRig armature found")
            return {"CANCELLED"}

        context.view_layer.objects.active = arm_obj
        arm_obj.select_set(True)
        bpy.ops.object.mode_set(mode="POSE")
        for pb in arm_obj.pose.bones:
            pb.bone.select = pb.name == self.bone_name
        return {"FINISHED"}


class WEAPONRIG_OT_add_all_bones(bpy.types.Operator):
    """Add all remaining bones in one fast batch (minimal mode switches)"""
    bl_idname = "weaponrig.add_all_bones"
    bl_label = "Add All Remaining Bones"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        weapon_type = context.scene.weaponrig_weapon_type
        if weapon_type not in WEAPON_CONFIGS:
            self.report({"ERROR"}, f"Unknown weapon type: {weapon_type}")
            return {"CANCELLED"}

        config = WeaponConfig.from_dict(WEAPON_CONFIGS[weapon_type])
        added = set(_get_added_list(context))
        skipped = set(_get_skipped_list(context))
        position = context.scene.cursor.location.copy()

        bones_to_add = [b for b in config.bones if b.name not in added and b.name not in skipped]
        if not bones_to_add:
            self.report({"INFO"}, "All bones already added or skipped")
            return {"CANCELLED"}

        arm_obj = get_or_create_armature(context)
        convention = context.scene.get("weaponrig_naming", "TITLE")

        if context.object and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        context.view_layer.objects.active = arm_obj
        arm_obj.select_set(True)

        # PHASE 1: Create ALL bones in one EDIT session
        bpy.ops.object.mode_set(mode="EDIT")
        for bone_def in bones_to_add:
            display_name = _format_bone_name(bone_def.name, convention)
            eb = arm_obj.data.edit_bones.new(display_name)
            eb.head = position.copy()
            _orient_bone(eb, bone_def)
            if bone_def.parent:
                parent_name = _format_bone_name(bone_def.parent, convention)
                parent_eb = arm_obj.data.edit_bones.get(parent_name)
                if parent_eb:
                    eb.parent = parent_eb
                    eb.use_connect = False
        bpy.ops.object.mode_set(mode="OBJECT")

        # PHASE 2: Apply ALL constraints, drivers, shapes in one pass
        created = 0
        for bone_def in bones_to_add:
            _apply_bone_constraints(arm_obj, bone_def, context)
            _apply_bone_drivers(arm_obj, bone_def, context)
            _assign_bone_shape(arm_obj, bone_def, context)
            created += 1

        # ONE depsgraph update for everything
        arm_obj.update_tag()
        context.view_layer.update()

        # Track added bones
        added_list = _get_added_list(context)
        for bone_def in bones_to_add:
            if bone_def.name not in added_list:
                added_list.append(bone_def.name)
        context.scene.weaponrig_added_bones = json.dumps(added_list)

        self.report({"INFO"}, f"Batch added {created} bones (2 mode switches total)")
        return {"FINISHED"}


class WEAPONRIG_OT_skip_bone(bpy.types.Operator):
    """Skip a bone — mark it as not present on this model"""
    bl_idname = "weaponrig.skip_bone"
    bl_label = "Skip Bone"
    bl_options = {"REGISTER", "UNDO"}

    bone_name: bpy.props.StringProperty(name="Bone Name")

    def execute(self, context):
        skipped = _get_skipped_list(context)
        if self.bone_name not in skipped:
            skipped.append(self.bone_name)
            context.scene.weaponrig_skipped_bones = json.dumps(skipped)
        self.report({"INFO"}, f"Skipped: {self.bone_name}")
        return {"FINISHED"}


class WEAPONRIG_OT_auto_detect(bpy.types.Operator):
    """Auto-detect mesh parts and place bones at their centers"""
    bl_idname = "weaponrig.auto_detect"
    bl_label = "Auto-Detect & Place"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        weapon_type = context.scene.weaponrig_weapon_type
        if weapon_type not in WEAPON_CONFIGS:
            self.report({"ERROR"}, f"Unknown weapon type: {weapon_type}")
            return {"CANCELLED"}

        config = WeaponConfig.from_dict(WEAPON_CONFIGS[weapon_type])
        matches = _find_mesh_matches(config)

        if not matches:
            self.report({"WARNING"}, "No mesh parts matched config bone names")
            return {"CANCELLED"}

        arm_obj = get_or_create_armature(context)
        added = _get_added_list(context)
        placed = 0

        for bone_name, mesh_obj in matches.items():
            if bone_name in added:
                continue
            position = _obj_centroid(mesh_obj)
            info = add_single_bone(config, bone_name, arm_obj, position, context)
            if "error" not in info:
                added.append(bone_name)
                placed += 1

        context.scene.weaponrig_added_bones = json.dumps(added)
        self.report({"INFO"}, f"Auto-placed {placed} bones from {len(matches)} matched mesh parts")

        context.view_layer.objects.active = arm_obj
        arm_obj.select_set(True)
        return {"FINISHED"}


class WEAPONRIG_OT_assign_weights(bpy.types.Operator):
    """Assign each vertex to its nearest bone with weight 1.0 (rigid body)"""
    bl_idname = "weaponrig.assign_weights"
    bl_label = "Assign Mesh to Bones"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arm_obj = None
        for obj in context.scene.objects:
            if obj.type == "ARMATURE" and obj.get("weaponrig"):
                arm_obj = obj
                break
        if arm_obj is None:
            self.report({"ERROR"}, "No WeaponRig armature found")
            return {"CANCELLED"}

        # Collect target meshes
        mesh_objects = [o for o in context.selected_objects if o.type == "MESH"]
        if not mesh_objects:
            mesh_objects = [o for o in context.scene.objects if o.type == "MESH"]
        if not mesh_objects:
            self.report({"ERROR"}, "No mesh objects found")
            return {"CANCELLED"}

        if context.object and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        # Build KDTree from bone head positions
        bones = arm_obj.pose.bones
        bone_count = len(bones)
        if bone_count == 0:
            self.report({"ERROR"}, "No bones in armature")
            return {"CANCELLED"}

        kd = kdtree.KDTree(bone_count)
        bone_names = []
        for i, pb in enumerate(bones):
            world_pos = arm_obj.matrix_world @ pb.head
            kd.insert(world_pos, i)
            bone_names.append(pb.name)
        kd.balance()

        total_assigned = 0
        for mesh_obj in mesh_objects:
            # Clear existing vertex groups
            mesh_obj.vertex_groups.clear()

            # Create vertex group for each bone
            vg_map = {}
            for bname in bone_names:
                vg = mesh_obj.vertex_groups.new(name=bname)
                vg_map[bname] = vg

            # Assign each vertex to nearest bone
            mesh = mesh_obj.data
            for vert in mesh.vertices:
                world_co = mesh_obj.matrix_world @ vert.co
                co, idx, dist = kd.find(world_co)
                nearest_bone = bone_names[idx]
                vg_map[nearest_bone].add([vert.index], 1.0, "REPLACE")
                total_assigned += 1

            # Add armature modifier if not present
            has_mod = any(m.type == "ARMATURE" for m in mesh_obj.modifiers)
            if not has_mod:
                mod = mesh_obj.modifiers.new(name="WeaponRig", type="ARMATURE")
                mod.object = arm_obj

        self.report({"INFO"}, f"Assigned {total_assigned} vertices across {len(mesh_objects)} mesh(es)")
        return {"FINISHED"}


class WEAPONRIG_OT_import_mesh(bpy.types.Operator, ImportHelper):
    """Import a weapon mesh file"""
    bl_idname = "weaponrig.import_mesh"
    bl_label = "Import Weapon Mesh"
    bl_options = {"REGISTER", "UNDO"}
    filter_glob: bpy.props.StringProperty(default="*.fbx;*.obj;*.gltf;*.glb", options={"HIDDEN"})

    def execute(self, context):
        fp = Path(self.filepath)
        ext = fp.suffix.lower()
        try:
            if ext == ".fbx":
                bpy.ops.import_scene.fbx(filepath=str(fp))
            elif ext == ".obj":
                bpy.ops.wm.obj_import(filepath=str(fp))
            elif ext in (".gltf", ".glb"):
                bpy.ops.import_scene.gltf(filepath=str(fp))
            else:
                self.report({"ERROR"}, f"Unsupported: {ext}")
                return {"CANCELLED"}
        except Exception as e:
            self.report({"ERROR"}, f"Import failed: {e}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Imported: {fp.name}")
        return {"FINISHED"}


# ===================================================================
# HELPERS
# ===================================================================

def _get_added_list(context):
    raw = context.scene.weaponrig_added_bones
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def _get_skipped_list(context):
    raw = context.scene.get("weaponrig_skipped_bones", "")
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def _selection_centroid(context):
    obj = context.active_object
    if obj and obj.type == "MESH" and obj.mode == "EDIT":
        import bmesh
        bm = bmesh.from_edit_mesh(obj.data)
        selected_verts = [v for v in bm.verts if v.select]
        if selected_verts:
            centroid = sum((v.co for v in selected_verts), Vector()) / len(selected_verts)
            return obj.matrix_world @ centroid

    selected = [o for o in context.selected_objects if o.type == "MESH"]
    if selected:
        centroid = sum((o.location for o in selected), Vector()) / len(selected)
        return centroid
    return None


def _wrap_text(layout, text, width=40):
    col = layout.column(align=True)
    words = text.split()
    line = ""
    for word in words:
        if len(line) + len(word) + 1 > width:
            col.label(text=line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    if line:
        col.label(text=line)


# ===================================================================
# UI PANELS
# ===================================================================

class WEAPONRIG_PT_main(bpy.types.Panel):
    """WeaponRig guided rigging panel"""
    bl_label = "WeaponRig"
    bl_idname = "WEAPONRIG_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "WeaponRig"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Driver auto-run warning
        if hasattr(bpy.context.preferences.filepaths, "autorun_disabled"):
            if bpy.context.preferences.filepaths.autorun_disabled:
                box = layout.box()
                box.alert = True
                box.label(text="Auto Run Scripts DISABLED", icon="ERROR")
                box.label(text="Drivers won't work. Enable in:")
                box.label(text="Prefs > Save & Load > Auto Run")

        # Weapon type + naming convention
        box = layout.box()
        box.label(text="Weapon Type", icon="PREFERENCES")
        box.prop(scene, "weaponrig_weapon_type", text="")
        box.prop(scene, "weaponrig_naming", text="Naming")

        weapon_type = scene.weaponrig_weapon_type
        if weapon_type not in WEAPON_CONFIGS:
            layout.label(text="No config loaded", icon="ERROR")
            return

        config = WeaponConfig.from_dict(WEAPON_CONFIGS[weapon_type])
        added = set(_get_added_list(context))
        skipped = set(_get_skipped_list(context))

        # Auto-detect button
        mesh_count = sum(1 for o in bpy.data.objects if o.type == "MESH")
        if mesh_count > 0:
            box = layout.box()
            box.label(text=f"Scene Meshes: {mesh_count}", icon="MESH_DATA")
            box.operator("weaponrig.auto_detect", text="Auto-Detect & Place Bones", icon="VIEWZOOM")

        # Batch add button
        remaining = sum(1 for b in config.bones if b.name not in added and b.name not in skipped)
        if remaining > 0:
            box = layout.box()
            box.operator("weaponrig.add_all_bones", text=f"Add All {remaining} Bones at Cursor", icon="ADD")

        # Bone checklist
        box = layout.box()
        box.label(text="Bone Checklist", icon="ARMATURE_DATA")

        required_total = 0
        required_done = 0
        optional_total = 0
        optional_done = 0
        next_bone = None

        for bone_def in config.bones:
            is_added = bone_def.name in added
            is_skipped = bone_def.name in skipped
            is_required = bone_def.presence in ("required", "expected")

            if is_required:
                required_total += 1
                if is_added:
                    required_done += 1
            else:
                optional_total += 1
                if is_added:
                    optional_done += 1

            row = box.row(align=True)
            if is_added:
                row.label(text="", icon="CHECKMARK")
                row.label(text=bone_def.name)
                op = row.operator("weaponrig.select_bone", text="", icon="RESTRICT_SELECT_OFF")
                op.bone_name = bone_def.name
            elif is_skipped:
                row.label(text="", icon="CANCEL")
                row.label(text=bone_def.name)
                row.label(text="(skipped)")
            else:
                if bone_def.presence == "required":
                    row.label(text="", icon="LAYER_ACTIVE")
                elif bone_def.presence == "expected":
                    row.label(text="", icon="LAYER_USED")
                else:
                    row.label(text="", icon="RADIOBUT_OFF")
                row.label(text=bone_def.name)
                # Skip button for each unadded bone
                op = row.operator("weaponrig.skip_bone", text="", icon="X")
                op.bone_name = bone_def.name
                if next_bone is None:
                    next_bone = bone_def

        # Progress
        row = layout.row()
        row.label(text=f"Required: {required_done}/{required_total}")
        row.label(text=f"Optional: {optional_done}/{optional_total}")

        # Next bone detail panel
        if next_bone:
            box = layout.box()
            box.label(text=f"Next: {next_bone.name}", icon="BONE_DATA")

            if next_bone.description:
                _wrap_text(box, next_bone.description)
            box.separator()

            if next_bone.movement_type != "static":
                box.label(text=f"Movement: {next_bone.movement_type} on {next_bone.axis}", icon="CON_LOCLIKE")
            if next_bone.parent:
                box.label(text=f"Parent: {next_bone.parent}", icon="CON_CHILDOF")

            if next_bone.placement:
                box.separator()
                box.label(text="Placement:", icon="CURSOR")
                _wrap_text(box, next_bone.placement)

            params = next_bone.parameters
            if params:
                box.separator()
                box.label(text="Specs:", icon="INFO")
                for key, val in params.items():
                    if key in ("source", "pivot_description"):
                        continue
                    if isinstance(val, (list, dict)):
                        continue
                    display_key = key.replace("_", " ").title()
                    box.label(text=f"  {display_key}: {val}")

            box.separator()
            row = box.row(align=True)
            op = row.operator("weaponrig.add_bone", text="Add at 3D Cursor", icon="CURSOR")
            op.bone_name = next_bone.name
            op.use_selection = False
            op = row.operator("weaponrig.add_bone", text="Add at Selection", icon="RESTRICT_SELECT_OFF")
            op.bone_name = next_bone.name
            op.use_selection = True
        elif not added:
            box = layout.box()
            box.label(text="Select a bone or use Add All", icon="INFO")
        else:
            box = layout.box()
            box.label(text="All bones added!", icon="CHECKMARK")

        # Mesh tools (show when bones exist)
        if added:
            box = layout.box()
            box.label(text="Mesh Tools", icon="MOD_VERTEX_WEIGHT")
            box.operator("weaponrig.assign_weights", text="Assign Mesh to Bones", icon="BONE_DATA")
            box.operator("weaponrig.segment_mesh", text="Segment Fused Mesh", icon="MOD_EXPLODE")

        # Animation section
        if added:
            box = layout.box()
            box.label(text="Animation", icon="ACTION")
            box.operator("weaponrig.generate_cycle", text="Generate Firing Cycle", icon="PHYSICS")
            row = box.row(align=True)
            op = row.operator("weaponrig.generate_recoil", text="Recoil: Rifle", icon="FORCE_HARMONIC")
            op.preset = "rifle"
            op = row.operator("weaponrig.generate_recoil", text="Pistol")
            op.preset = "pistol"
            box.operator("weaponrig.generate_fire_modes", text="Generate All Fire Modes (NLA)", icon="NLA")
            box.operator("weaponrig.play_cycle", text="Play Animation", icon="PLAY")

        # Export section
        if added:
            box = layout.box()
            box.label(text="Export", icon="EXPORT")
            row = box.row(align=True)
            op = row.operator("weaponrig.export_fbx", text="UE5")
            op.engine = "UE5"
            op = row.operator("weaponrig.export_fbx", text="Unity")
            op.engine = "Unity"
            op = row.operator("weaponrig.export_fbx", text="Godot")
            op.engine = "Godot"


class WEAPONRIG_PT_cycle(bpy.types.Panel):
    """Firing cycle test slider"""
    bl_label = "Firing Cycle Test"
    bl_idname = "WEAPONRIG_PT_cycle"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "WeaponRig"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        added = _get_added_list(context)
        return len(added) > 0

    def draw(self, context):
        layout = self.layout
        props = context.scene.weaponrig_props
        layout.prop(props, "cycle_progress", slider=True)
        layout.label(text="Drag to simulate firing cycle", icon="PLAY")




# ===================================================================
# REGISTRATION
# ===================================================================

_classes = (
    WeaponRigProperties,
    WEAPONRIG_OT_add_bone,
    WEAPONRIG_OT_select_bone,
    WEAPONRIG_OT_add_all_bones,
    WEAPONRIG_OT_skip_bone,
    WEAPONRIG_OT_auto_detect,
    WEAPONRIG_OT_assign_weights,
    WEAPONRIG_OT_import_mesh,
    WEAPONRIG_OT_generate_cycle,
    WEAPONRIG_OT_generate_recoil,
    WEAPONRIG_OT_generate_fire_modes,
    WEAPONRIG_OT_segment_mesh,
    WEAPONRIG_OT_export_fbx,
    WEAPONRIG_OT_play_cycle,
    WEAPONRIG_PT_main,
    WEAPONRIG_PT_cycle,
)


def _weapon_type_items(self, context):
    return [(k, v["display_name"], v.get("description", "")) for k, v in WEAPON_CONFIGS.items()]


def register():
    global _draw_handler
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.weaponrig_weapon_type = bpy.props.EnumProperty(
        name="Weapon Type",
        description="Select the weapon operating system",
        items=_weapon_type_items,
    )
    bpy.types.Scene.weaponrig_added_bones = bpy.props.StringProperty(
        name="Added Bones",
        description="JSON list of added bone names",
        default="",
    )
    bpy.types.Scene.weaponrig_skipped_bones = bpy.props.StringProperty(
        name="Skipped Bones",
        description="JSON list of skipped bone names",
        default="",
    )
    bpy.types.Scene.weaponrig_naming = bpy.props.EnumProperty(
        name="Naming",
        description="Bone naming convention",
        items=[
            ("TITLE", "Title Case", "Bolt Carrier"),
            ("SNAKE", "snake_case", "bolt_carrier"),
            ("PASCAL", "PascalCase", "BoltCarrier"),
            ("UPPER_SNAKE", "UPPER_SNAKE", "BOLT_CARRIER"),
        ],
        default="TITLE",
    )
    bpy.types.Scene.weaponrig_props = bpy.props.PointerProperty(type=WeaponRigProperties)
    _draw_handler = bpy.types.SpaceView3D.draw_handler_add(
        _draw_constraint_ranges, (), "WINDOW", "POST_VIEW"
    )


def unregister():
    global _draw_handler
    if _draw_handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handler, "WINDOW")
        _draw_handler = None
    del bpy.types.Scene.weaponrig_props
    del bpy.types.Scene.weaponrig_naming
    del bpy.types.Scene.weaponrig_skipped_bones
    del bpy.types.Scene.weaponrig_added_bones
    del bpy.types.Scene.weaponrig_weapon_type
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


# ===================================================================
# PHYSICS FIRING CYCLE SIMULATOR (v0.4)
# ===================================================================

def _simulate_carrier_cycle(params, fps=60):
    """Spring-mass simulation of bolt carrier cycle. Returns {frame: position_m}."""
    mass = params.get("carrier_mass_kg", 0.3)
    spring_k = params.get("buffer_spring_rate_n_per_m", 3500)
    travel = params.get("carrier_travel_m", 0.095)
    peak_vel = params.get("carrier_peak_velocity_m_per_s", 5.8)
    gas_dur = params.get("gas_impulse_duration_ms", 1.2) / 1000.0

    dt = 0.00005  # 50 microsecond timestep for accuracy
    restitution = 0.3  # buffer impact bounce coefficient

    # Calculate gas force from peak velocity and impulse duration
    gas_force = (mass * peak_vel) / gas_dur if gas_dur > 0 else mass * peak_vel / 0.001

    x = 0.0  # position (negative = rearward)
    v = 0.0  # velocity
    t = 0.0

    # Determine total sim duration from cyclic rate or default
    rpm = params.get("cyclic_rate_rpm", 700)
    if rpm and rpm > 0:
        cycle_time = 60.0 / rpm
    else:
        cycle_time = 0.1  # 100ms for semi-auto

    num_frames = int(cycle_time * fps) + 1
    frame_dt = 1.0 / fps
    results = {}
    frame_idx = 0
    next_frame_time = 0.0
    phase = "gas"  # gas -> decel -> bounce -> return -> lockup

    while t < cycle_time and frame_idx < num_frames + 10:
        # Record frame data
        if t >= next_frame_time:
            results[frame_idx] = max(-travel, min(0.0, x))
            frame_idx += 1
            next_frame_time = frame_idx * frame_dt

        # Forces
        f_total = 0.0

        # Gas impulse (rearward)
        if t < gas_dur and phase == "gas":
            f_total -= gas_force

        # Spring force (resists rearward, pushes forward)
        if x < 0:
            f_total -= spring_k * x  # x is negative, so this pushes forward (positive)

        # Buffer stop
        if x <= -travel:
            x = -travel
            if v < 0:
                v = -v * restitution  # bounce
                phase = "return"

        # Forward stop (battery)
        if x >= 0 and v > 0 and phase == "return":
            x = 0.0
            v = 0.0
            phase = "lockup"

        if phase != "lockup":
            a = f_total / mass
            v += a * dt
            x += v * dt

        if phase == "gas" and t >= gas_dur:
            phase = "decel"

        t += dt

    # Fill remaining frames
    while frame_idx < num_frames:
        results[frame_idx] = 0.0
        frame_idx += 1

    return results


def _bake_cycle_to_action(armature, config, fps=60):
    """Simulate firing cycle and bake to a Blender Action. Returns the Action."""
    physics = config.physics
    if not physics:
        return None

    rpm = config.cyclic_rate_rpm.get("auto") or config.cyclic_rate_rpm.get("semi") or 700
    physics_params = dict(physics)
    physics_params["cyclic_rate_rpm"] = rpm

    carrier_positions = _simulate_carrier_cycle(physics_params, fps)
    if not carrier_positions:
        return None

    # Find the carrier bone
    carrier_bone = None
    for bd in config.bones:
        if bd.movement_type == "translate" and bd.constraints:
            for c in bd.constraints:
                if c.type == "LIMIT_LOCATION":
                    carrier_bone = bd
                    break
            if carrier_bone:
                break

    if not carrier_bone:
        return None

    arm = armature
    if arm.animation_data is None:
        arm.animation_data_create()

    action_name = f"FiringCycle_{config.display_name}"
    action = bpy.data.actions.new(name=action_name)

    axis_idx = _AXIS_INDEX.get(carrier_bone.axis.lower(), 1) if carrier_bone.axis else 1
    data_path = f'pose.bones["{carrier_bone.name}"].location'
    fcu = action.fcurves.new(data_path=data_path, index=axis_idx)
    fcu.keyframe_points.add(len(carrier_positions))
    for i, (frame, pos) in enumerate(sorted(carrier_positions.items())):
        fcu.keyframe_points[i].co = (frame + 1, pos)  # Blender frames start at 1
        fcu.keyframe_points[i].interpolation = "BEZIER"
    fcu.update()

    # Drive dependent bones (rotation bones with drivers linked to carrier)
    for bd in config.bones:
        if not bd.drivers:
            continue
        for ddef in bd.drivers:
            if ddef.driver_bone != carrier_bone.name:
                continue
            d_path, d_idx = _parse_prop(ddef.driven_property)
            dfcu = action.fcurves.new(
                data_path=f'pose.bones["{bd.name}"].{d_path}', index=d_idx
            )
            dfcu.keyframe_points.add(len(carrier_positions))
            for i, (frame, carrier_pos) in enumerate(sorted(carrier_positions.items())):
                var = carrier_pos
                if ddef.cam_curve_keyframes:
                    travel = bd.parameters.get("carrier_travel_m", carrier_bone.parameters.get("carrier_travel_m", 1.0))
                    rot_rad = math.radians(bd.parameters.get("rotation_degrees", 1.0))
                    sorted_kfs = sorted(ddef.cam_curve_keyframes, key=lambda k: k.carrier_travel_pct)
                    pct = abs(var) / travel if travel > 0 else 0
                    val = 0.0
                    for ki in range(len(sorted_kfs) - 1):
                        if sorted_kfs[ki].carrier_travel_pct <= pct <= sorted_kfs[ki + 1].carrier_travel_pct:
                            seg_len = sorted_kfs[ki + 1].carrier_travel_pct - sorted_kfs[ki].carrier_travel_pct
                            if seg_len > 0:
                                t = (pct - sorted_kfs[ki].carrier_travel_pct) / seg_len
                            else:
                                t = 0
                            val = (sorted_kfs[ki].bolt_rotation_pct + t * (sorted_kfs[ki + 1].bolt_rotation_pct - sorted_kfs[ki].bolt_rotation_pct)) * rot_rad
                            break
                    else:
                        if sorted_kfs:
                            val = sorted_kfs[-1].bolt_rotation_pct * rot_rad
                else:
                    try:
                        val = eval(ddef.expression or "var", {"var": var, "abs": abs, "math": math})
                    except Exception:
                        val = 0.0
                dfcu.keyframe_points[i].co = (frame + 1, val)
                dfcu.keyframe_points[i].interpolation = "BEZIER"
            dfcu.update()

    return action


# ===================================================================
# SPRING-DAMPER RECOIL GENERATOR (v0.4)
# ===================================================================

def _halflife_to_damping(halflife):
    return (4.0 * 0.69314718056) / max(halflife, 1e-5)


def _decay_spring(x, v, halflife, dt):
    """Critically-damped spring decay toward zero."""
    y = _halflife_to_damping(halflife) / 2.0
    j1 = v + x * y
    eydt = math.exp(-y * dt)
    new_x = eydt * (x + j1 * dt)
    new_v = eydt * (v - j1 * y * dt)
    return new_x, new_v


_RECOIL_PRESETS = {
    "rifle": {"kick_back": 0.02, "kick_up_deg": 3.0, "kick_side_deg": 1.0, "recovery_halflife": 0.15},
    "pistol": {"kick_back": 0.01, "kick_up_deg": 5.0, "kick_side_deg": 2.0, "recovery_halflife": 0.12},
    "smg": {"kick_back": 0.015, "kick_up_deg": 2.0, "kick_side_deg": 1.5, "recovery_halflife": 0.10},
    "shotgun": {"kick_back": 0.04, "kick_up_deg": 8.0, "kick_side_deg": 3.0, "recovery_halflife": 0.25},
}


def _generate_recoil_action(armature, root_bone_name, preset_name="rifle", fps=60):
    """Generate a recoil animation using critically-damped spring physics."""
    preset = _RECOIL_PRESETS.get(preset_name, _RECOIL_PRESETS["rifle"])
    dt = 1.0 / fps
    num_frames = int(0.4 * fps)  # 400ms

    channels = {
        ("location", 1): -preset["kick_back"],        # Y backward kick
        ("rotation_euler", 0): math.radians(preset["kick_up_deg"]),   # X muzzle rise
        ("rotation_euler", 2): math.radians(preset["kick_side_deg"]) * (1 if hash(root_bone_name) % 2 == 0 else -1),
    }

    arm = armature
    if arm.animation_data is None:
        arm.animation_data_create()

    action = bpy.data.actions.new(name=f"Recoil_{preset_name}")

    for (prop, idx), initial in channels.items():
        data_path = f'pose.bones["{root_bone_name}"].{prop}'
        fcu = action.fcurves.new(data_path=data_path, index=idx)
        fcu.keyframe_points.add(num_frames)

        x, v = initial, 0.0
        for frame in range(num_frames):
            if frame == 0:
                x = initial
                v = -initial * 20  # sharp kick
            x, v = _decay_spring(x, v, preset["recovery_halflife"], dt)
            fcu.keyframe_points[frame].co = (frame + 1, x)
            fcu.keyframe_points[frame].interpolation = "BEZIER"
        fcu.update()

    return action


# ===================================================================
# NLA FIRE MODE ACTIONS (v0.4)
# ===================================================================

def _create_fire_mode_actions(armature, cycle_action, recoil_action, config, fps=60):
    """Generate NLA tracks for semi, auto, burst from base actions."""
    if armature.animation_data is None:
        armature.animation_data_create()

    actions = {}

    # Semi = single cycle + recoil
    if cycle_action:
        semi = cycle_action.copy()
        semi.name = f"Fire_Semi_{config.display_name}"
        actions["semi"] = semi

    # Auto = repeated cycles
    auto_rpm = config.cyclic_rate_rpm.get("auto")
    if auto_rpm and cycle_action:
        frames_per_shot = max(1, int(fps * 60.0 / auto_rpm))
        burst_count = 10
        auto_action = bpy.data.actions.new(name=f"Fire_Auto_{config.display_name}")

        for fcu_src in cycle_action.fcurves:
            fcu = auto_action.fcurves.new(data_path=fcu_src.data_path, index=fcu_src.array_index)
            kf_data = []
            for shot in range(burst_count):
                offset = shot * frames_per_shot
                for kp in fcu_src.keyframe_points:
                    kf_data.append((kp.co[0] + offset, kp.co[1]))
            fcu.keyframe_points.add(len(kf_data))
            for i, (f, v) in enumerate(kf_data):
                fcu.keyframe_points[i].co = (f, v)
            fcu.update()
        actions["auto"] = auto_action

    # 3-round burst
    burst_rpm = config.cyclic_rate_rpm.get("burst_3")
    if burst_rpm and cycle_action:
        frames_per_shot = max(1, int(fps * 60.0 / burst_rpm))
        burst_action = bpy.data.actions.new(name=f"Fire_Burst3_{config.display_name}")

        for fcu_src in cycle_action.fcurves:
            fcu = burst_action.fcurves.new(data_path=fcu_src.data_path, index=fcu_src.array_index)
            kf_data = []
            for shot in range(3):
                offset = shot * frames_per_shot
                for kp in fcu_src.keyframe_points:
                    kf_data.append((kp.co[0] + offset, kp.co[1]))
            fcu.keyframe_points.add(len(kf_data))
            for i, (f, v) in enumerate(kf_data):
                fcu.keyframe_points[i].co = (f, v)
            fcu.update()
        actions["burst_3"] = burst_action

    # Push all to NLA tracks
    anim_data = armature.animation_data
    for mode_name, action in actions.items():
        track = anim_data.nla_tracks.new()
        track.name = f"FireMode_{mode_name}"
        track.strips.new(name=action.name, start=0, action=action)

    anim_data.action = None  # clear active so NLA takes over
    return actions


# ===================================================================
# MESH SEGMENTATION (v0.4) — no ML required
# ===================================================================

def _separate_loose_parts(obj):
    """Separate mesh into disconnected islands. Returns list of new objects."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()

    visited = set()
    islands = []
    for v in bm.verts:
        if v.index in visited:
            continue
        island = set()
        stack = [v]
        while stack:
            vert = stack.pop()
            if vert.index in visited:
                continue
            visited.add(vert.index)
            island.add(vert.index)
            for edge in vert.link_edges:
                other = edge.other_vert(vert)
                if other.index not in visited:
                    stack.append(other)
        islands.append(island)
    bm.free()
    return islands


def _segment_by_dihedral(obj, angle_threshold_deg=45.0):
    """Segment fused mesh at sharp edges using region growing. Returns list of face index sets."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()

    threshold = math.radians(angle_threshold_deg)
    visited = set()
    regions = []

    for face in bm.faces:
        if face.index in visited:
            continue
        region = set()
        stack = [face]
        while stack:
            f = stack.pop()
            if f.index in visited:
                continue
            visited.add(f.index)
            region.add(f.index)
            for edge in f.edges:
                for neighbor in edge.link_faces:
                    if neighbor.index != f.index and neighbor.index not in visited:
                        angle = f.normal.angle(neighbor.normal, 0.0)
                        if angle < threshold:
                            stack.append(neighbor)
        if len(region) > 0:
            regions.append(region)
    bm.free()
    return regions


# ===================================================================
# FBX EXPORT PRESETS (v0.4)
# ===================================================================

_FBX_PRESETS = {
    "UE5": {
        "apply_scale_options": "FBX_SCALE_UNITS",
        "axis_forward": "-Z", "axis_up": "Y",
        "add_leaf_bones": False,
        "primary_bone_axis": "Y", "secondary_bone_axis": "X",
        "use_mesh_modifiers": True, "use_armature_deform_only": True,
        "bake_anim": True, "bake_anim_simplify_factor": 0.0,
        "object_types": {"ARMATURE", "MESH"}, "global_scale": 1.0,
        "mesh_smooth_type": "FACE",
    },
    "Unity": {
        "apply_scale_options": "FBX_SCALE_ALL",
        "axis_forward": "-Z", "axis_up": "Y",
        "add_leaf_bones": False,
        "primary_bone_axis": "Y", "secondary_bone_axis": "X",
        "use_mesh_modifiers": True, "use_armature_deform_only": True,
        "bake_anim": True, "bake_anim_simplify_factor": 1.0,
        "object_types": {"ARMATURE", "MESH"}, "global_scale": 1.0,
        "mesh_smooth_type": "FACE",
    },
    "Godot": {
        "apply_scale_options": "FBX_SCALE_NONE",
        "axis_forward": "-Z", "axis_up": "Y",
        "add_leaf_bones": False,
        "primary_bone_axis": "Y", "secondary_bone_axis": "X",
        "use_mesh_modifiers": True, "bake_anim": True,
        "object_types": {"ARMATURE", "MESH"}, "global_scale": 1.0,
        "mesh_smooth_type": "FACE",
    },
}


# ===================================================================
# v0.4 OPERATORS
# ===================================================================

class WEAPONRIG_OT_generate_cycle(bpy.types.Operator):
    """Generate physics-based firing cycle animation from weapon specs"""
    bl_idname = "weaponrig.generate_cycle"
    bl_label = "Generate Firing Cycle"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arm_obj = None
        for obj in context.scene.objects:
            if obj.type == "ARMATURE" and obj.get("weaponrig"):
                arm_obj = obj
                break
        if arm_obj is None:
            self.report({"ERROR"}, "No WeaponRig armature found")
            return {"CANCELLED"}

        weapon_type = context.scene.weaponrig_weapon_type
        if weapon_type not in WEAPON_CONFIGS:
            self.report({"ERROR"}, "No config loaded")
            return {"CANCELLED"}

        config = WeaponConfig.from_dict(WEAPON_CONFIGS[weapon_type])
        action = _bake_cycle_to_action(arm_obj, config)
        if action is None:
            self.report({"ERROR"}, "Could not generate cycle — check physics config")
            return {"CANCELLED"}

        arm_obj.animation_data.action = action
        start, end = action.frame_range
        context.scene.frame_start = int(start)
        context.scene.frame_end = int(end)
        context.scene.frame_current = int(start)

        self.report({"INFO"}, f"Generated firing cycle: {int(end - start + 1)} frames")
        return {"FINISHED"}


class WEAPONRIG_OT_generate_recoil(bpy.types.Operator):
    """Generate spring-damper recoil animation"""
    bl_idname = "weaponrig.generate_recoil"
    bl_label = "Generate Recoil"
    bl_options = {"REGISTER", "UNDO"}

    preset: bpy.props.EnumProperty(
        name="Weapon Class",
        items=[("rifle", "Rifle", ""), ("pistol", "Pistol", ""), ("smg", "SMG", ""), ("shotgun", "Shotgun", "")],
        default="rifle",
    )

    def execute(self, context):
        arm_obj = None
        for obj in context.scene.objects:
            if obj.type == "ARMATURE" and obj.get("weaponrig"):
                arm_obj = obj
                break
        if arm_obj is None:
            self.report({"ERROR"}, "No WeaponRig armature found")
            return {"CANCELLED"}

        # Find root bone
        root_name = None
        added = _get_added_list(context)
        weapon_type = context.scene.weaponrig_weapon_type
        if weapon_type in WEAPON_CONFIGS:
            config = WeaponConfig.from_dict(WEAPON_CONFIGS[weapon_type])
            for bd in config.bones:
                if bd.parent is None and bd.name in added:
                    root_name = bd.name
                    break
        if root_name is None and arm_obj.pose.bones:
            root_name = arm_obj.pose.bones[0].name

        if root_name is None:
            self.report({"ERROR"}, "No root bone found")
            return {"CANCELLED"}

        action = _generate_recoil_action(arm_obj, root_name, self.preset)
        arm_obj.animation_data.action = action
        start, end = action.frame_range
        context.scene.frame_start = int(start)
        context.scene.frame_end = int(end)

        self.report({"INFO"}, f"Generated {self.preset} recoil: {int(end - start + 1)} frames")
        return {"FINISHED"}


class WEAPONRIG_OT_generate_fire_modes(bpy.types.Operator):
    """Generate NLA actions for all fire modes (semi, auto, burst)"""
    bl_idname = "weaponrig.generate_fire_modes"
    bl_label = "Generate All Fire Modes"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arm_obj = None
        for obj in context.scene.objects:
            if obj.type == "ARMATURE" and obj.get("weaponrig"):
                arm_obj = obj
                break
        if arm_obj is None:
            self.report({"ERROR"}, "No WeaponRig armature found")
            return {"CANCELLED"}

        weapon_type = context.scene.weaponrig_weapon_type
        if weapon_type not in WEAPON_CONFIGS:
            self.report({"ERROR"}, "No config loaded")
            return {"CANCELLED"}

        config = WeaponConfig.from_dict(WEAPON_CONFIGS[weapon_type])

        # Generate base cycle
        cycle_action = _bake_cycle_to_action(arm_obj, config)

        # Generate base recoil
        root_name = None
        for bd in config.bones:
            if bd.parent is None:
                root_name = bd.name
                break
        recoil_action = _generate_recoil_action(arm_obj, root_name or "Weapon Root") if root_name else None

        actions = _create_fire_mode_actions(arm_obj, cycle_action, recoil_action, config)
        self.report({"INFO"}, f"Generated {len(actions)} fire mode actions as NLA tracks")
        return {"FINISHED"}


class WEAPONRIG_OT_segment_mesh(bpy.types.Operator):
    """Separate fused mesh into parts using edge angle detection"""
    bl_idname = "weaponrig.segment_mesh"
    bl_label = "Segment Mesh"
    bl_options = {"REGISTER", "UNDO"}

    angle_threshold: bpy.props.FloatProperty(
        name="Angle Threshold", default=45.0, min=10.0, max=90.0,
        description="Split at edges sharper than this angle (degrees)",
    )

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select a mesh object")
            return {"CANCELLED"}

        # First check for loose parts
        islands = _separate_loose_parts(obj)
        if len(islands) > 1:
            # Use Blender's built-in separate by loose parts
            context.view_layer.objects.active = obj
            obj.select_set(True)
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.separate(type="LOOSE")
            bpy.ops.object.mode_set(mode="OBJECT")
            new_count = len([o for o in context.selected_objects if o.type == "MESH"])
            self.report({"INFO"}, f"Separated into {new_count} loose parts")
            return {"FINISHED"}

        # If single mesh, try dihedral angle segmentation
        regions = _segment_by_dihedral(obj, self.angle_threshold)
        if len(regions) <= 1:
            self.report({"WARNING"}, "Could not segment — mesh appears to be one continuous surface. Try lowering the angle threshold")
            return {"CANCELLED"}

        # Separate regions into objects using vertex groups then separate
        import bmesh
        context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()

        # Create vertex groups per region
        for i, face_indices in enumerate(regions):
            vg = obj.vertex_groups.new(name=f"Part_{i:03d}")
            vert_indices = set()
            for fi in face_indices:
                if fi < len(bm.faces):
                    for v in bm.faces[fi].verts:
                        vert_indices.add(v.index)
            bpy.ops.mesh.select_all(action="DESELECT")
            bm.verts.ensure_lookup_table()
            for vi in vert_indices:
                bm.verts[vi].select = True
            bmesh.update_edit_mesh(obj.data)
            bpy.ops.object.vertex_group_assign()

        bpy.ops.object.mode_set(mode="OBJECT")
        self.report({"INFO"}, f"Found {len(regions)} regions as vertex groups. Select groups and separate manually (P key) for best results")
        return {"FINISHED"}


class WEAPONRIG_OT_export_fbx(bpy.types.Operator):
    """Export weapon rig as FBX with game engine presets"""
    bl_idname = "weaponrig.export_fbx"
    bl_label = "Export FBX"
    bl_options = {"REGISTER"}

    engine: bpy.props.EnumProperty(
        name="Engine",
        items=[("UE5", "Unreal Engine 5", ""), ("Unity", "Unity", ""), ("Godot", "Godot", "")],
        default="UE5",
    )
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        preset = _FBX_PRESETS.get(self.engine, _FBX_PRESETS["UE5"])

        try:
            bpy.ops.export_scene.fbx(filepath=self.filepath, **preset)
        except Exception as e:
            self.report({"ERROR"}, f"Export failed: {e}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"Exported for {self.engine}: {Path(self.filepath).name}")
        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class WEAPONRIG_OT_play_cycle(bpy.types.Operator):
    """Play firing cycle animation in viewport"""
    bl_idname = "weaponrig.play_cycle"
    bl_label = "Play Cycle"

    def execute(self, context):
        arm_obj = None
        for obj in context.scene.objects:
            if obj.type == "ARMATURE" and obj.get("weaponrig"):
                arm_obj = obj
                break
        if arm_obj is None or arm_obj.animation_data is None or arm_obj.animation_data.action is None:
            self.report({"WARNING"}, "No animation to play. Generate a firing cycle first")
            return {"CANCELLED"}

        action = arm_obj.animation_data.action
        start, end = action.frame_range
        context.scene.frame_start = int(start)
        context.scene.frame_end = int(end)
        context.scene.frame_current = int(start)
        bpy.ops.screen.animation_play()
        return {"FINISHED"}


if __name__ == "__main__":
    register()
