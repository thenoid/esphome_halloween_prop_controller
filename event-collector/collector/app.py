import asyncio
import csv
import io
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from .config import Settings
from .protocol import EVENT_TYPES
from .receiver import Runtime
from .store import timestamp

EventType = Enum("EventType", {name.replace(".", "_"): name for name in EVENT_TYPES}, type=str)
bearer = HTTPBearer(auto_error=False)


class EventRecord(BaseModel):
    id: int
    received_at: datetime
    source: str
    event: EventType
    item: int
    reason: str
    sender_ip: str
    sender_port: int
    raw_packet: str


class EventPage(BaseModel):
    events: list[EventRecord]
    has_more: bool
    next_after_id: int | None
    next_before_id: int | None


class Health(BaseModel):
    status: Literal["ok", "degraded"]


class CounterRecord(BaseModel):
    packets_received: int
    invalid_packets: int
    queue_overflows: int
    events_written: int
    write_errors: int
    udp_errors: int
    events_purged: int


class CollectorStatus(Health):
    started_at: datetime
    udp_listening: bool
    udp_port: int | None
    queue_depth: int
    queue_capacity: int
    last_packet_at: datetime | None
    last_event_at: datetime | None
    storage_error: str | None
    retention_error: str | None
    retention_days: int
    counters: CounterRecord
    stored_events: int
    oldest_received_at: datetime | None
    newest_received_at: datetime | None
    latest_id: int | None


class ControllerRecord(BaseModel):
    source: str
    event_count: int
    first_received_at: datetime
    last_received_at: datetime


class ControllerPage(BaseModel):
    controllers: list[ControllerRecord]


class SummaryGroup(BaseModel):
    source: str
    event: EventType
    item: int
    count: int
    first_received_at: datetime
    last_received_at: datetime


class Summary(BaseModel):
    total: int
    groups: list[SummaryGroup]


def filters(
    source: Annotated[str | None, Query(pattern=r"^[a-z0-9-]{1,63}$")] = None,
    event: EventType | None = None,
    item: Annotated[int | None, Query(ge=1, le=4)] = None,
    reason: Literal["", "cooldown_finished", "stopped"] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    after_id: Annotated[int | None, Query(ge=0)] = None,
    before_id: Annotated[int | None, Query(ge=1)] = None,
):
    """Receipt times: since inclusive, until exclusive. IDs are collector-local."""
    try:
        start = timestamp(since) if since else None
        end = timestamp(until) if until else None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if start and end and start >= end:
        raise HTTPException(422, "since must be earlier than until")
    if after_id is not None and before_id is not None and after_id >= before_id:
        raise HTTPException(422, "after_id must be smaller than before_id")
    return dict(source=source, event=event.value if event else None, item=item, reason=reason,
                since=start, until=end, after_id=after_id, before_id=before_id)


def authorize(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
):
    token = credentials.credentials if credentials else ""
    if not secrets.compare_digest(token.encode(), request.app.state.runtime.settings.api_token.encode()):
        raise HTTPException(401, "A valid bearer token is required", headers={"WWW-Authenticate": "Bearer"})


def create_app(settings: Settings | None = None):
    @asynccontextmanager
    async def lifespan(app):
        runtime = Runtime(settings or Settings.from_env())
        app.state.runtime = runtime
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(
        title="Controller Event Collector", version="1.0.0", lifespan=lifespan,
        description="Read-only archive of HC1 UDP events from all controllers. "
        "received_at is collector receipt time. Delivery and physical prop operation are not guaranteed. "
        "Use bearer authentication for /api/v1 endpoints. No event injection or controller commands.",
    )

    @app.middleware("http")
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path == "/":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
            )
        return response

    @app.exception_handler(Exception)
    async def server_error(request, exc):
        # Never return database paths or exception internals to API clients.
        return JSONResponse({"detail": "Collector operation failed; check service logs and status"}, status_code=503)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get("/ui/{asset}", include_in_schema=False)
    def asset(asset: Literal["app.js", "style.css"]):
        return FileResponse(Path(__file__).parent / "static" / asset)

    @app.get("/healthz", operation_id="health", response_model=Health, responses={503: {"model": Health}})
    async def health(request: Request):
        runtime = request.app.state.runtime
        try:
            await asyncio.to_thread(runtime.store.status)
            healthy = runtime.healthy()
        except Exception:
            healthy = False
        return JSONResponse({"status": "ok" if healthy else "degraded"}, status_code=200 if healthy else 503)

    auth = [Depends(authorize)]

    @app.get("/api/v1/status", dependencies=auth, operation_id="collector_status", response_model=CollectorStatus)
    async def status(request: Request):
        runtime = request.app.state.runtime
        archive = await asyncio.to_thread(runtime.store.status)
        return {"status": "ok" if runtime.healthy() else "degraded", **runtime.status(), **archive}

    @app.get("/api/v1/controllers", dependencies=auth, operation_id="list_controllers", response_model=ControllerPage)
    def controllers(request: Request):
        return {"controllers": request.app.state.runtime.store.controllers()}

    @app.get("/api/v1/events", dependencies=auth, response_model=EventPage, operation_id="list_events")
    def events(
        request: Request, selection: Annotated[dict, Depends(filters)],
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        order: Literal["asc", "desc"] = "desc",
    ):
        return request.app.state.runtime.store.events(selection, limit, order)

    @app.get("/api/v1/summary", dependencies=auth, operation_id="summarize_events", response_model=Summary)
    def summary(request: Request, selection: Annotated[dict, Depends(filters)]):
        return request.app.state.runtime.store.summary(selection)

    @app.get("/api/v1/events.csv", dependencies=auth, operation_id="export_events",
             response_class=Response, responses={200: {"content": {"text/csv": {}}}})
    def export(
        request: Request, selection: Annotated[dict, Depends(filters)],
        limit: Annotated[int, Query(ge=1, le=1000)] = 1000,
        order: Literal["asc", "desc"] = "desc",
    ):
        page = request.app.state.runtime.store.events(selection, limit, order)
        output = io.StringIO(newline="")
        fields = list(EventRecord.model_fields)
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for row in page["events"]:
            # Controller names permit a leading '-'; prevent spreadsheet formulas.
            writer.writerow({k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v
                             for k, v in row.items()})
        return Response(output.getvalue(), media_type="text/csv", headers={
            "Content-Disposition": 'attachment; filename="controller-events.csv"',
            "X-Has-More": str(page["has_more"]).lower(),
            "X-Next-After-Id": str(page["next_after_id"] or ""),
            "X-Next-Before-Id": str(page["next_before_id"] or ""),
        })

    return app


app = create_app()
