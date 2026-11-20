"""Routes every part of the app uses: settings and the model's status."""
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from pydantic import ValidationError

from shared import engines, llm, settings

router = APIRouter()


def errors(e: ValidationError) -> dict[str, str]:
    """A pydantic error as {field: message} for the page."""
    return {str(err["loc"][0]) if err["loc"] else "": err["msg"].removeprefix("Value error, ")
            for err in e.errors()}



@router.get("/settings")
def get_settings() -> dict[str, Any]:
    return settings.get_all().model_dump(exclude={"engines"})  # engines carry keys: they come from /settings/engines, keys left out


@router.patch("/settings")
def patch_settings(patch: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return settings.update(patch).model_dump(exclude={"engines"})
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": errors(e)})


@router.get("/settings/engines")
def list_engines() -> dict[str, Any]:
    """Every engine, whether its server is up and what it has loaded, which one is in use, and any swap going on."""
    return engines.listing()


@router.post("/settings/engines")
def save_engine(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return engines.save(body)
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": errors(e)})
    except ValueError as e:
        raise HTTPException(422, detail={"errors": {"": str(e)}})


@router.delete("/settings/engines/{eid}")
def delete_engine(eid: str) -> dict[str, Any]:
    try:
        if not engines.remove(eid):
            raise HTTPException(404, detail="There is no such engine.")
    except ValueError as e:
        raise HTTPException(409, detail=str(e))
    return {"ok": True}


@router.post("/settings/engines/{eid}/use")
def use_engine(eid: str) -> dict[str, Any]:
    """Make an engine the one in use. Refused (409) while a model swap or other model work is going on."""
    try:
        return engines.use(eid)
    except KeyError:
        raise HTTPException(404, detail="There is no such engine.")
    except engines.Busy as e:
        raise HTTPException(409, detail=str(e))


@router.post("/settings/test-connection")
def test_connection() -> dict[str, Any]:
    return llm.test_connection(settings.get_all())


@router.post("/settings/check-context")
def check_context() -> dict[str, Any]:
    """Reads the context window the local server reports. Does not send the paper."""
    return llm.context_window(settings.get_all())
@router.get("/model/status")
def model_status() -> dict[str, Any]:
    return llm.model_status(settings.get_all())

