"""Flask route and compatibility tests."""

from __future__ import annotations

from typing import Any

from barrobot.config import BarRobotConfig


def test_menu_filters_recipes_and_uses_post_pour(client: Any) -> None:
    """Only makeable drinks render and the primary pour action is POST-first."""
    response = client.get("/")

    assert response.status_code == 200
    assert b"Rum and Cola" in response.data
    assert b"Gin and Tonic" not in response.data
    assert b'method="post"' in response.data


def test_detail_and_suggestion_routes_remain_compatible(client: Any) -> None:
    """Existing detail and both suggestion URLs remain available."""
    assert b"Rum and Cola" in client.get("/drink/1").data
    assert b"tonic water" in client.get("/suggestions").data
    assert b"Gin and Tonic" in client.get("/suggestions2").data


def test_post_pour_executes_plan_and_legacy_get_still_works(app: Any, client: Any) -> None:
    """POST is primary while v1 GET bookmarks continue to execute in v2."""
    post = client.post("/make_drink/Rum%20and%20Cola", follow_redirects=True)
    get = client.get("/make_drink/Rum%20and%20Cola", follow_redirects=True)

    assert post.status_code == 200
    assert get.status_code == 200
    assert b"Rum and Cola is ready" in post.data
    assert app.testing_services["gpio"].outputs == []


def test_missing_recipe_is_rejected_before_hardware(app: Any, client: Any) -> None:
    """An unmakeable direct pour does not move or press hardware."""
    response = client.post("/make_drink/Gin%20and%20Tonic", follow_redirects=True)

    assert response.status_code == 200
    assert b"Missing ingredient" in response.data
    assert app.testing_services["gpio"].outputs == []


def test_position_and_rotation_api_validate_range(app: Any, client: Any) -> None:
    """Motor APIs use one-based slots and reject values outside 1 through 12."""
    assert client.post("/api/position/0").status_code == 400
    position = client.post("/api/position/12")
    rotation = client.post("/api/rotate/1")

    assert position.get_json() == {"status": "ok", "slot": 12}
    assert rotation.status_code == 200
    assert app.testing_services["hardware"].current_slot == 0


def test_configure_normalizes_inventory_and_preserves_pins(app: Any, client: Any) -> None:
    """The existing configuration form updates inventory through validation."""
    response = client.post(
        "/configure",
        data={
            "shot_size": "0.75",
            "slot0": " Dark  Rum ",
            "pantry": " Cola, Lime ",
            "sub_key0": "white rum",
            "sub_val0": "dark rum",
            "safe_mode": "on",
        },
    )

    config: BarRobotConfig = app.testing_services["store"].load()
    assert response.status_code == 302
    assert config.shot_size == 0.75
    assert config.slots[0] == "dark rum"
    assert config.pantry == ("cola", "lime")
    assert config.substitutions == {"white rum": "dark rum"}


def test_live_rotation_reports_untrusted_position(tmp_path: Any, recipes: Any) -> None:
    """The API returns a conflict instead of moving from an assumed live position."""
    from conftest import RecordingGpio, StaticRecipeRepository

    from barrobot import create_app
    from barrobot.config import ConfigStore
    from barrobot.hardware import HardwareController

    store = ConfigStore(tmp_path / "config.json")
    store.save(BarRobotConfig())
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "CONFIG_PATH": tmp_path / "config.json",
            "LEGACY_CONFIG_PATH": tmp_path / "legacy.json",
            "RECIPES_PATH": tmp_path / "recipes.json",
            "BARROBOT_CONFIG_STORE": store,
            "BARROBOT_RECIPE_REPOSITORY": StaticRecipeRepository(recipes),
            "BARROBOT_HARDWARE": HardwareController(gpio=RecordingGpio(), sleeper=lambda _: None),
        }
    )

    response = application.test_client().post("/api/rotate/2")

    assert response.status_code == 409
    assert "position is unknown" in response.get_json()["msg"]
