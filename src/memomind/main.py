# # 프로그램을 처음 실행하는 시작 점입니다. MemoMindAI.py 파일을 실행하면 가장 먼저 이 파일이 실행됩니다.
# # 이 파일은 src/memomind/main.py 파일을 불러와서 프로그램을 작동시키는 역할을 합니다.

import flet as ft

# 같은 폴더 안에 있는 설정(config) 파일과 화면(ui) 파일에서 필요한 기능을 가져옵니다.
from .config import Settings
from .ui.app import main


def run() -> None:
    settings = Settings.from_environment()
    ft.run(lambda page: main(page, settings), assets_dir=str(settings.assets_dir))
