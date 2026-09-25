import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or Path(".env")
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    gemini_model: str


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-3.5-live-translate-preview"),
    )
