"""Settings: .env gives first defaults, the SQLite settings table overrides them."""
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared import db

ROOT = Path(__file__).resolve().parent.parent

# The settings an engine carries. Model names are the server's own, so they are cleared when an engine does not set them.
ENGINE_KEYS = ("base_url", "api_key", "model_name", "embed_model", "planner_model", "chat_model", "judge_model", "max_context_tokens")
PER_SERVER = ("model_name", "embed_model", "planner_model", "chat_model", "judge_model")


class Engine(BaseModel):
    """A way to run models: a server and what to use on it. `kind` says what the server can do: unsloth loads and swaps
    models on demand (role models swap here); llama.cpp holds the one model it was started with; openai is any other
    OpenAI-compatible server; mlx runs its model in this process, where its hidden states can be read and steered (its URL is
    the server left for embeddings). New kinds of server can be added here as they come."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")
    name: str = Field(min_length=1, max_length=40)
    kind: Literal["llama.cpp", "unsloth", "openai", "mlx"] = "openai"
    note: str = Field("", max_length=200)
    values: dict[str, Any] = {}

    @field_validator("values")
    @classmethod
    def _values(cls, v: dict[str, Any]) -> dict[str, Any]:
        bad = sorted(set(v) - set(ENGINE_KEYS))
        if bad:
            raise ValueError(f"an engine cannot set {', '.join(bad)}")
        return v


# shortcut: phase 1 holds only connection, generation and reflection target; phase 8 adds the rest.
class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str = "http://localhost:8888/v1"
    api_key: str = ""
    model_name: str = ""  # empty = first model the server lists
    embed_model: str = ""  # for the graph; empty = first model the server lists with "embed" in its name that works
    # one model per harness role, loaded on demand (llm.ensure); empty = use whatever is loaded, no swap
    planner_model: str = ""
    chat_model: str = ""
    judge_model: str = ""
    # the dory engine: its own llama-server build, started on demand when a role picks "dory"; empty command = no dory engine
    dory_cmd: str = ""
    dory_url: str = "http://127.0.0.1:8080/v1"
    temperature: float = Field(0.2, ge=0, le=1)
    max_context_tokens: int = Field(32768, ge=2048, le=262144)
    max_output_tokens: int = Field(1024, ge=64, le=16384)
    timeout_s: int = Field(180, ge=5, le=1800)
    reflections_target: int = Field(6, ge=1, le=50)
    # AI summary (the primer)
    primer_sentences: int = Field(2, ge=1, le=3)
    primer_auto: bool = False  # make it right after upload
    primer_panel: Literal["after_writing", "click", "open"] = "after_writing"
    # checker
    hint_words: int = Field(40, ge=20, le=60)
    checker_hints: bool = True  # False = show the verdict only
    # Dot's personality, in your words; used when Dot talks in the Library
    dot_persona: str = Field("", max_length=300)
    # engines: named model setups (a server, its key, its models, its role models), picked on Model connection.
    # The keys above stay the live values every part of the app reads; picking an engine writes its values into them.
    engines: list[dict[str, Any]] = []
    engine: str = ""  # the engine in use; "" = none picked, the fields above as typed

    @field_validator("engines")
    @classmethod
    def _engines(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = [Engine(**e).model_dump() for e in v]
        if len({e["id"] for e in out}) != len(out):
            raise ValueError("two engines have the same name")
        return out

    @field_validator("base_url", "dory_url")
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


OVERRIDE: dict[str, Any] = {}  # a pipeline stage's models; never written to the DB, so a crash cannot leave a stage's engine behind


def get_all() -> Settings:
    return Settings(**{**read_env(), **db.get_settings(), **OVERRIDE})


def stored() -> Settings:
    """What is saved, without a pipeline stage's override: what the Models panel shows and writes back."""
    return Settings(**{**read_env(), **db.get_settings()})


def update(patch: dict[str, Any]) -> Settings:
    """Validate the merged result first; store only the changed keys. A change to a connection key while an engine is
    in use is kept in that engine too, so picking it again brings it back. Raises ValidationError."""
    new = Settings(**{**get_all().model_dump(), **patch})
    synced = {k: getattr(new, k) for k in patch if k in ENGINE_KEYS}
    if new.engine and synced and "engines" not in patch:
        new.engines = [{**e, "values": {**e["values"], **synced}} if e["id"] == new.engine else e for e in new.engines]
        patch = {**patch, "engines": new.engines}
    db.set_settings({k: getattr(new, k) for k in patch})
    return new
