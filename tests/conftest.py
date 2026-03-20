import pytest
from pathlib import Path

from weaponrig.database.schema import WeaponConfig


CONFIGS_DIR = Path(__file__).resolve().parent.parent / "weaponrig" / "database" / "configs"


@pytest.fixture
def ar15_config_path():
    return CONFIGS_DIR / "ar15_di.json"


@pytest.fixture
def template_config_path():
    return CONFIGS_DIR / "_template.json"


@pytest.fixture
def ar15_config(ar15_config_path):
    return WeaponConfig.load(ar15_config_path)
