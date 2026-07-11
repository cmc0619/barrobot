"""Compatibility entry point for running BarRobot directly."""

from __future__ import annotations

import os

from barrobot import create_app

app = create_app()


if __name__ == "__main__":
    hardware = app.extensions["barrobot.hardware"]
    try:
        app.run(
            host="0.0.0.0",
            port=int(os.getenv("BARROBOT_PORT", "5000")),
            debug=os.getenv("BARROBOT_DEBUG", "0") == "1",
            use_reloader=False,
        )
    finally:
        hardware.cleanup()
