"""Segment filters: ONE query builder shared by the Segments page and the AI assistant.

Because both use segment_query(), a segment the assistant describes is exactly
the segment the UI would build from the same filters.
"""
from datetime import date, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import Select, exists, func, select

from app.config import TODAY
from app.models import Event, Identity, Profile
from app.normalize import normalize_source


class SegmentFilters(BaseModel):
    """Every filter is optional; only the ones you set are applied (AND-ed together)."""

    source: str | None = None  # acquisition source, e.g. "instagram"
    status: str | None = None  # "active" or "unsubscribed"
    signed_up_from: date | None = None
    signed_up_to: date | None = None
    # "Hasn't opened the newsletter in N days": last open older than N days, or
    # never opened. Only people subscribed for at least N days count, so a
    # brand-new subscriber isn't labeled "cold" before their first issue.
    not_opened_days: int | None = Field(None, ge=0)
    min_events: int | None = Field(None, ge=0)  # at least N web/app events ever
    has_app: bool | None = None  # has (or doesn't have) an app account


# Saved filter combinations shown as one-click buttons in the UI.
PRESETS: dict[str, SegmentFilters] = {
    # Surprise feature: people who were engaged (3+ visits/app events) and are
    # still subscribed, but haven't opened the newsletter in two weeks.
    # These are the readers worth a win-back email before they unsubscribe.
    "going_cold": SegmentFilters(status="active", not_opened_days=14, min_events=3),
}


def segment_query(f: SegmentFilters) -> Select:
    q = select(Profile)
    if f.source:
        # Same normalizer as the importer, so "X", "x" and "twitter" all match.
        q = q.where(Profile.acquisition_source == normalize_source(f.source))
    if f.status:
        q = q.where(Profile.status == f.status.strip().lower())
    if f.signed_up_from:
        q = q.where(Profile.signup_date >= f.signed_up_from)
    if f.signed_up_to:
        q = q.where(Profile.signup_date <= f.signed_up_to)
    if f.not_opened_days is not None:
        cutoff = TODAY - timedelta(days=f.not_opened_days)
        q = q.where(
            Profile.signup_date <= cutoff,
            Profile.last_open_date.is_(None) | (Profile.last_open_date < cutoff),
        )
    if f.min_events is not None:
        # A correlated subquery: "count this profile's events" for each row.
        event_count = (
            select(func.count(Event.id)).where(Event.profile_id == Profile.id).scalar_subquery()
        )
        q = q.where(event_count >= f.min_events)
    if f.has_app is not None:
        has_app = exists().where(Identity.profile_id == Profile.id, Identity.kind == "app_user_id")
        q = q.where(has_app if f.has_app else ~has_app)
    return q


def profile_row(p: Profile) -> dict:
    """The fields shown for a person in tables (this DOES include the email,
    so it is only ever sent to the browser, never to the AI model)."""
    return {
        "id": p.id,
        "email": p.email,
        "status": p.status,
        "acquisition_source": p.acquisition_source,
        "signup_date": p.signup_date.isoformat() if p.signup_date else None,
        "last_open_date": p.last_open_date.isoformat() if p.last_open_date else None,
    }
