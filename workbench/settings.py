"""Settings: .env gives first defaults, the SQLite settings table overrides them."""
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import db

ROOT = Path(__file__).resolve().parent.parent

# shortcut: phase 1 holds only connection, generation and reflection target; phase 8 adds the rest.
class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str = "http://localhost:8888/v1"
    api_key: str = ""
    model_name: str = ""  # empty = first model the server lists
    embed_model: str = ""  # for the graph; empty = first model the server lists with "embed" in its name that works
    temperature: float = Field(0.2, ge=0, le=1)
    max_context_tokens: int = Field(32768, ge=2048, le=262144)
    max_output_tokens: int = Field(1024, ge=64, le=16384)
    timeout_s: int = Field(180, ge=5, le=1800)
    reflections_target: int = Field(6, ge=1, le=50)

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return v


ENV_KEYS = {
    "UNSLOTH_BASE_URL": "base_url",
    "UNSLOTH_API_KEY": "api_key",
    "MODEL_NAME": "model_name",
    "MAX_CONTEXT_TOKENS": "max_context_tokens",
}


def read_env(path: Path = ROOT / ".env") -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip("'\"")
    values.update({k: os.environ[k] for k in ENV_KEYS if k in os.environ})
    return {ENV_KEYS[k]: v for k, v in values.items() if k in ENV_KEYS and v != ""}


def get_all() -> Settings:
    return Settings(**{**read_env(), **db.get_settings()})


def update(patch: dict[str, Any]) -> Settings:
    """Validate the merged result first; store only the changed keys. Raises ValidationError."""
    new = Settings(**{**get_all().model_dump(), **patch})
    db.set_settings({k: getattr(new, k) for k in patch})
    return new
