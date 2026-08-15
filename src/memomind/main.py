"""Application launcher."""

import flet as ft

from .config import Settings
from .ui.app import main


def run() -> None:
    settings = Settings.from_environment()
    ft.run(lambda page: main(page, settings), assets_dir=str(settings.assets_dir))
