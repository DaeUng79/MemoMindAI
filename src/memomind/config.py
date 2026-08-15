"""Environment settings and runtime paths."""

from dataclasses import dataclass
import os
from pathlib import Path
import sys


DEFAULT_API_URL = "http://127.0.0.1:8080/v1/chat/completions"
DEFAULT_MODEL_NAME = "gemma-4-e2b-it"


def project_root() -> Path:
    """Return the source checkout root or the frozen executable directory."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    api_url: str
    model_name: str
    base_dir: Path
    memo_dir: Path
    db_path: Path
    assets_dir: Path

    @classmethod
    def from_environment(cls) -> "Settings":
        base_dir = project_root()
        memo_dir = base_dir / "memoAI"
        return cls(
            api_url=os.getenv("LLAMACPP_API_URL", DEFAULT_API_URL),
            model_name=os.getenv("MODEL_NAME", DEFAULT_MODEL_NAME),
            base_dir=base_dir,
            memo_dir=memo_dir,
            db_path=memo_dir / "individual_data.json",
            assets_dir=base_dir / "assets",
        )
