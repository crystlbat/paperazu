"""Load and validate framework.yaml, the single source of truth for the reading steps."""
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "framework.yaml"
# reading templates: a research paper (the default) and lecture slides
TEMPLATES = {"paper": DEFAULT_PATH, "slides": ROOT / "framework_slides.yaml"}
Template = Literal["paper", "slides"]

FieldType = Literal["text", "long", "date", "rows", "choice", "checks"]


class Field(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: FieldType
    label: str
    help: str | None = None
    cols: list[str] | None = None
    start_rows: int = 1
    numbered: bool = False
    options: list[str] | None = None

    @model_validator(mode="after")
    def _needs(self) -> "Field":
        if self.type == "rows" and not self.cols:
            raise ValueError(f"field '{self.id}': type 'rows' needs 'cols'")
        if self.type in ("choice", "checks") and not self.options:
            raise ValueError(f"field '{self.id}': type '{self.type}' needs 'options'")
        return self


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    n: int
    title: str
    minutes: int
    look_in: list[str] = []
    paper_hidden: bool = False
    fields: list[Field]
    gate: list[str] = []

    @model_validator(mode="after")
    def _unique_fields(self) -> "Step":
        ids = [f.id for f in self.fields]
        if len(ids) != len(set(ids)):
            raise ValueError(f"step '{self.id}': field ids must be unique")
        return self


class Framework(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[Step]

    @model_validator(mode="after")
    def _unique_steps(self) -> "Framework":
        ids = [s.id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step ids must be unique")
        return self


def parse(text: str) -> Framework:
    return Framework.model_validate(yaml.safe_load(text))


def load(path: Path = DEFAULT_PATH) -> Framework:
    return parse(path.read_text(encoding="utf-8"))


def load_template(template: str) -> Framework:
    return load(TEMPLATES.get(template, DEFAULT_PATH))


def load_all() -> dict[str, Framework]:
    return {name: load(path) for name, path in TEMPLATES.items()}
