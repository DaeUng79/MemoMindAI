"""
MemoMindAI 프로그램 시작점이 파일은 MemoMindAI 프로그램을 실행할 때 가장 먼저 거치는 연결 통로입니다. 
실제 프로그램 핵심 코드는 src/memomind라는 폴더 안에 들어있습니다.
이렇게 따로 연결 파일을 만들어 둔 이유는, 기존에 쓰던 python MemoMindAI.py 같은 실행 명령어를 그대로 사용할 수 있게 만들기 위해서입니다.
프로그램을 개발하면서 src 폴더 안에 있는 파일들을 수정했다면, 변경 내용을 적용하기 위해 실행 중인 명령어(flet run)를 껐다가 다시 켜야 합니다. 
모듈설치 : pip install -r requirements.txt
실행명령어 : flet run MemoMindAI.py
"""

from pathlib import Path
import sys


SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from memomind.main import run  # noqa: E402


if __name__ == "__main__":
    run()
