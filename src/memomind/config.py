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
    # PyInstaller 등으로 프로그램이 실행 파일 형태로 패키징된 경우
    # sys.frozen 값이 존재합니다.
    # 이 경우 현재 실행 중인 실행 파일(.exe)이 있는 폴더를
    # 프로그램의 기준 경로로 사용합니다.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    # 일반적인 Python 소스 코드 환경에서는
    # 현재 파일(__file__)을 기준으로 상위 2단계 폴더를
    # 프로젝트 루트로 사용합니다.
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    api_url: str
    model_name: str

    # 프로젝트의 최상위 기준 디렉터리입니다.
    base_dir: Path

    # 메모 및 사용자 데이터를 저장하는 디렉터리입니다.
    memo_dir: Path

    # 개인 데이터를 저장하는 JSON 파일의 경로입니다.
    db_path: Path

    # 이미지, 아이콘 등의 정적 리소스를 저장하는 디렉터리입니다.
    assets_dir: Path

    @classmethod
    def from_environment(cls) -> "Settings":
        # 현재 프로그램의 프로젝트 루트 경로를 가져옵니다.
        base_dir = project_root()

        # 프로젝트 루트 아래에 있는 memoAI 디렉터리를 메모 및 데이터 저장용 기본 디렉터리로 설정합니다.
        memo_dir = base_dir / "memoAI"

        # 위에서 계산한 설정값들을 하나의 Settings 객체로 만들어 반환합니다.
        return cls(
            # LLAMACPP_API_URL 환경변수가 있으면 그 값을 사용하고,없으면 DEFAULT_API_URL을 사용합니다.
            api_url=os.getenv("LLAMACPP_API_URL", DEFAULT_API_URL),

            # MODEL_NAME 환경변수가 있으면 그 값을 사용하고, 없으면 DEFAULT_MODEL_NAME을 사용합니다.
            model_name=os.getenv("MODEL_NAME", DEFAULT_MODEL_NAME),

            # 프로그램의 프로젝트 루트 경로입니다.
            base_dir=base_dir,

            # 메모 데이터 저장 디렉터리입니다.
            memo_dir=memo_dir,

            # memoAI 디렉터리 안의 individual_data.json을 개인 데이터 저장 파일로 사용합니다.
            db_path=memo_dir / "individual_data.json",

            # 프로젝트 루트 아래의 assets 디렉터리를 이미지, 아이콘 등의 리소스 디렉터리로 사용합니다.
            assets_dir=base_dir / "assets",
        )
