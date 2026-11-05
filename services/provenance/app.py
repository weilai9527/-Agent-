"""按学校接收证书存证事件，供签发和验真服务查询。"""
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path, Response
from pydantic import BaseModel, ConfigDict, Field

from shared.service_db import ServiceDatabase
from shared.service_security import require_service
from .store import AnchorStore, ConflictingDigest

EVENT_ID = r"^[0-9a-f]{32}$"
RELAY = ("credentials", "system", "credentials-relay")
VERIFIER = ("credentials-verifier", "system", "credentials-verifier")


class AnchorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(pattern=EVENT_ID)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def authorized_school(identity, *principals):
    if (identity["caller"], identity["actor_type"], identity["actor_id"]) not in principals:
        raise HTTPException(403, "Caller cannot perform this anchor operation")
    return identity["school_id"]


def create_app(database=None):
    @asynccontextmanager
    async def lifespan(app):
        store = AnchorStore(database or ServiceDatabase.from_env("provenance"))
        store.initialize()
        app.state.anchors = store
        yield

    app = FastAPI(title="Provenance", lifespan=lifespan)

    @app.get("/health")
    def health():
        if not app.state.anchors.db.ping():
            raise HTTPException(503, "Database unavailable")
        return {"service": "provenance", "status": "ok"}

    @app.post("/internal/anchors")
    def submit(body: AnchorRequest, response: Response,
               identity=Depends(require_service("provenance", "provenance.submit"))):
        response.headers["Cache-Control"] = "no-store"
        try:
            return app.state.anchors.put(authorized_school(identity, RELAY), body.event_id, body.digest)
        except ConflictingDigest:
            raise HTTPException(409, "Event already bound to a different digest") from None

    @app.get("/internal/anchors/{event_id}")
    def read(event_id: Annotated[str, Path(pattern=EVENT_ID)], response: Response,
             identity=Depends(require_service("provenance", "provenance.read"))):
        response.headers["Cache-Control"] = "no-store"
        row = app.state.anchors.get(authorized_school(identity, RELAY, VERIFIER), event_id)
        if row is None:
            raise HTTPException(404, "Unknown event")
        return row

    return app


app = create_app()
