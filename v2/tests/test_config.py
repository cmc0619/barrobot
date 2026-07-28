"""Configuration model and persistence tests."""

from __future__ import annotations

import json

import pytest

from barrobot.config import BarRobotConfig, ConfigError, ConfigStore


def test_config_normalizes_and_pads_slots() -> None:
    """Ingredient inputs are normalized and short legacy slot lists are padded."""
    config = BarRobotConfig.from_mapping(
        {
            "slots": ["  Dark   Rum ", ""],
            "pantry": [" Lime Juice ", "lime   juice", None],
            "substitutions": {"White Rum": " Dark Rum "},
        }
    )

    assert config.slots == ("dark rum", None) + (None,) * 10
    assert config.pantry == ("lime juice",)
    assert config.substitutions == {"white rum": "dark rum"}


def test_config_rejects_duplicate_or_out_of_range_pins() -> None:
    """GPIO signals cannot share pins or reference invalid BCM numbers."""
    with pytest.raises(ConfigError, match="unique"):
        BarRobotConfig.from_mapping({"pins": {"DIR": 20, "STEP": 20, "ENABLE": 16, "ACTUATOR": 26}})
    with pytest.raises(ConfigError, match="0 through 27"):
        BarRobotConfig.from_mapping({"pins": {"DIR": 28, "STEP": 21, "ENABLE": 16, "ACTUATOR": 26}})


def test_config_rejects_unsafe_shot_size() -> None:
    """The existing half-ounce lower limit remains enforced."""
    with pytest.raises(ConfigError, match="at least 0.5"):
        BarRobotConfig.from_mapping({"shot_size": 0.1})


def test_store_imports_legacy_file_and_preserves_unknown_keys(tmp_path) -> None:
    """The first load migrates v1 configuration into canonical config.json."""
    legacy = tmp_path / "bottle_config.json"
    canonical = tmp_path / "config.json"
    legacy.write_text(json.dumps({"slots": ["Rum"], "future": {"enabled": True}}))
    store = ConfigStore(canonical, legacy)

    config = store.load()

    assert config.slots[0] == "rum"
    assert config.extra["future"] == {"enabled": True}
    assert canonical.exists()
    assert json.loads(canonical.read_text())["future"] == {"enabled": True}


def test_store_does_not_overwrite_invalid_json(tmp_path) -> None:
    """Malformed runtime configuration remains intact for operator recovery."""
    path = tmp_path / "config.json"
    path.write_text("{not-json")
    store = ConfigStore(path)

    with pytest.raises(ConfigError, match="Unable to read"):
        store.load()

    assert path.read_text() == "{not-json"
