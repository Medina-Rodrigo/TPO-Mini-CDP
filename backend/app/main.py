"""FastAPI app: the API, the webhook, and the built React frontend."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import config, models  # noqa: F401  (models import registers the tables)
from app.assistant import ask
from app.auth import require_login
from app.db import Base, SessionLocal, engine
from app.segments import PRESETS, SegmentFilters, profile_row, segment_query
from app.webhook import AppEvent, process_app_event, verify_signature

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create any missing tables on startup (safe to repeat; see create_tables.py).
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="TPO Mini CDP", lifespan=lifespan)


def get_db():
    # One database session per request, always closed afterwards.
    with SessionLocal() as session:
        yield session


@app.get("/api/health")
def health():
    return {"status": "ok"}  # public on purpose: hosts ping it


# Every route on this router requires the UI password.
api = APIRouter(prefix="/api", dependencies=[Depends(require_login)])


@api.get("/profiles")
def search_profiles(q: str = Query(min_length=2), db: Session = Depends(get_db)):
    """Find people by part of an email, or by an exact visitor/app/device id."""
    term = q.strip()
    stmt = (
        select(models.Profile)
        .outerjoin(models.Identity)
        .where(or_(models.Profile.email.ilike(f"%{term.lower()}%"), models.Identity.value == term))
        .distinct()
        .order_by(models.Profile.id)
        .limit(25)
    )
    return [profile_row(p) for p in db.scalars(stmt)]


@api.get("/profiles/{profile_id}")
def get_profile(profile_id: int, db: Session = Depends(get_db)):
    """One person: newsletter info, every linked id, and all activity."""
    profile = db.get(models.Profile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    events = db.scalars(
        select(models.Event)
        .where(models.Event.profile_id == profile_id)
        .order_by(models.Event.occurred_at.desc())  # by when it happened, not arrival
    ).all()
    return {
        **profile_row(profile),
        "identities": [{"kind": i.kind, "value": i.value} for i in profile.identities],
        "summary": {
            "web_visits": sum(e.source == "web" for e in events),
            "app_events": sum(e.source == "app" for e in events),
        },
        "events": [
            {
                "occurred_at": e.occurred_at.isoformat(),
                "source": e.source,
                "event_type": e.event_type,
                "page": e.page,
                "utm_source": e.utm_source,
                "properties": e.properties,
            }
            for e in events
        ],
    }


@api.post("/segments")
def run_segment(filters: SegmentFilters, db: Session = Depends(get_db)):
    people = db.scalars(segment_query(filters).order_by(models.Profile.id)).all()
    return {"count": len(people), "profiles": [profile_row(p) for p in people]}


@api.get("/segments/presets")
def segment_presets():
    return {name: f.model_dump(mode="json", exclude_none=True) for name, f in PRESETS.items()}


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


@api.post("/assistant")
def assistant(body: Question, db: Session = Depends(get_db)):
    return ask(db, body.question)


app.include_router(api)


@app.post("/webhooks/app", status_code=202)
async def app_webhook(request: Request):
    """Mobile app events. Authenticated by HMAC signature, not the UI password."""
    body = await request.body()  # the RAW bytes: the signature covers exactly these
    if not verify_signature(
        config.WEBHOOK_SECRET,
        body,
        request.headers.get("X-TPO-Timestamp"),
        request.headers.get("X-TPO-Signature"),
    ):
        raise HTTPException(status_code=401, detail="Invalid signature")
    try:
        event = AppEvent.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False))
    with SessionLocal() as session:
        result = process_app_event(session, event)
    # Duplicates still get a success code so the sender stops retrying.
    return {"status": result, "event_id": event.event_id}


# --- The built React app (frontend/ builds into backend/static) ---
if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/", include_in_schema=False)
def index(_user: str = Depends(require_login)):
    # Requiring login here is what makes the browser show its password prompt.
    if not (STATIC_DIR / "index.html").exists():
        return {"detail": "Frontend not built yet: run `npm run build` in frontend/"}
    return FileResponse(STATIC_DIR / "index.html")
