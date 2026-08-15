"""프로그램의 환경 설정과 실행 중 사용하는 파일 및 디렉터리 경로를 관리합니다."""

from dataclasses import dataclass
import os
from pathlib import Path
import sys


# llama.cpp 서버의 기본 OpenAI 호환 API 주소입니다.
DEFAULT_API_URL = "http://127.0.0.1:8080/v1/chat/completions"

# 기본으로 사용할 LLM 모델의 이름입니다.
DEFAULT_MODEL_NAME = "gemma-4-e2b-it"


def project_root() -> Path:
    """
    프로그램 내부에 포함된 리소스의 기준 경로를 반환합니다.

    일반적인 Python 실행 환경에서는
    프로젝트 루트를 기준 경로로 사용합니다.

    PyInstaller로 패키징된 환경에서는
    PyInstaller가 프로그램 실행을 위해 사용하는
    임시 리소스 폴더(_MEIPASS)를 기준으로 사용합니다.
    """

    # PyInstaller 등으로 프로그램이 패키징되면
    # sys.frozen 값이 True가 됩니다.
    if getattr(sys, "frozen", False):

        # PyInstaller는 프로그램 실행에 필요한 파일을
        # _MEIPASS 폴더에 풀어서 실행합니다.
        #
        # flet pack으로 포함한 assets 폴더도
        # 이 위치에서 찾을 수 있습니다.
        if hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS)

        # _MEIPASS를 사용할 수 없는 특수한 frozen 환경에서는
        # 현재 실행 파일이 있는 폴더를 기준으로 사용합니다.
        return Path(sys.executable).resolve().parent

    # 일반적인 Python 소스 코드 환경입니다.
    #
    # 현재 파일:
    # src/memomind/config.py
    #
    # parents[0] → src/memomind
    # parents[1] → src
    # parents[2] → 프로젝트 루트
    return Path(__file__).resolve().parents[2]


def data_root() -> Path:
    """
    사용자 데이터를 저장할 기준 폴더를 반환합니다.

    개발 환경에서는 프로젝트 루트를 기준으로 사용합니다.

    패키징된 프로그램에서는 운영체제별 사용자 데이터 폴더를 사용합니다.
    """

    # ---------------------------------------------------------
    # 1. 개발 환경
    # ---------------------------------------------------------
    #
    # Flet으로 실행하면 현재 작업 디렉터리(Path.cwd())가
    # .flet/storage/data 등으로 변경될 수 있습니다.
    #
    # 따라서 현재 작업 디렉터리가 아니라
    # config.py 파일의 위치를 기준으로 계산한
    # 프로젝트 루트를 사용합니다.
    if not getattr(sys, "frozen", False):
        return project_root()

    # ---------------------------------------------------------
    # 2. macOS 패키징 환경
    # ---------------------------------------------------------
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "MemoMindAI"
        )

    # ---------------------------------------------------------
    # 3. Windows 패키징 환경
    # ---------------------------------------------------------
    if sys.platform == "win32":
        local_app_data = os.getenv("LOCALAPPDATA")

        if local_app_data:
            return Path(local_app_data) / "MemoMindAI"

        return (
            Path.home()
            / "AppData"
            / "Local"
            / "MemoMindAI"
        )

    # ---------------------------------------------------------
    # 4. Linux 및 기타 운영체제
    # ---------------------------------------------------------
    return Path.home() / ".memomind"


@dataclass(frozen=True)
class Settings:
    """
    프로그램에서 사용하는 환경 설정과
    주요 파일 및 디렉터리 경로를 관리하는 객체입니다.
    """

    # llama.cpp 서버의 OpenAI 호환 API 주소입니다.
    api_url: str

    # 사용할 LLM 모델의 이름입니다.
    model_name: str

    # 프로그램 내부 리소스의 기준 디렉터리입니다.
    #
    # 개발 환경:
    #   프로젝트 루트
    #
    # PyInstaller:
    #   _MEIPASS
    base_dir: Path

    # 사용자 메모 데이터를 저장하는 디렉터리입니다.
    memo_dir: Path

    # 실제 메모 데이터가 저장되는 JSON 파일입니다.
    db_path: Path

    # 이미지와 아이콘 등의 프로그램 리소스가 들어 있는
    # assets 디렉터리입니다.
    assets_dir: Path

    @classmethod
    def from_environment(cls) -> "Settings":
        """
        환경변수와 실행 환경에 맞는 경로를 이용하여
        Settings 객체를 생성합니다.
        """

        # 프로그램 내부 리소스의 기준 경로를 가져옵니다.
        #
        # 개발 환경:
        #   프로젝트 루트
        #
        # PyInstaller:
        #   _MEIPASS
        base_dir = project_root()

        # 사용자 데이터를 저장할 기준 폴더를 가져옵니다.
        #
        # 개발 환경:
        #   현재 실행 경로
        #
        # Mac:
        #   ~/Library/Application Support/MemoMindAI
        #
        # Windows:
        #   %LOCALAPPDATA%/MemoMindAI
        data_dir = data_root()

        # 실제 메모 데이터를 저장할 폴더입니다.
        memo_dir = data_dir / "memoAI"

        # memoAI 폴더가 존재하지 않으면 자동으로 생성합니다.
        #
        # parents=True:
        #   상위 폴더가 없어도 함께 생성합니다.
        #
        # exist_ok=True:
        #   이미 폴더가 존재해도 오류를 발생시키지 않습니다.
        memo_dir.mkdir(parents=True, exist_ok=True)

        return cls(
            # LLAMACPP_API_URL 환경변수가 설정되어 있으면
            # 해당 값을 사용합니다.
            #
            # 환경변수가 없으면 기본 API 주소를 사용합니다.
            api_url=os.getenv(
                "LLAMACPP_API_URL",
                DEFAULT_API_URL,
            ),

            # MODEL_NAME 환경변수가 설정되어 있으면
            # 해당 모델 이름을 사용합니다.
            #
            # 환경변수가 없으면 기본 모델 이름을 사용합니다.
            model_name=os.getenv(
                "MODEL_NAME",
                DEFAULT_MODEL_NAME,
            ),

            # 프로그램 내부 리소스의 기준 경로입니다.
            base_dir=base_dir,

            # 사용자 메모 데이터 저장 폴더입니다.
            memo_dir=memo_dir,

            # memoAI 폴더 안에 메모 데이터를 JSON 형식으로 저장합니다.
            db_path=memo_dir / "individual_data.json",

            # 프로그램에 포함된 assets 폴더입니다.
            #
            # 개발 환경:
            #   프로젝트루트/assets
            #
            # 패키징 환경:
            #   _MEIPASS/assets
            assets_dir=base_dir / "assets",
        )