"""Real-time app events: POST /webhooks/app.

Rules from the brief, and where each is handled:
  - Authenticated like production  -> verify_signature (HMAC-SHA256 + timestamp)
  - Can arrive twice               -> event_id stored as Event.external_id (unique)
  - Can arrive out of order        -> we store when it HAPPENED (occurred_at) and
                                      always sort by that, never by arrival time
  - Login attaches earlier
    anonymous events               -> device_id identity + backfill UPDATE
  - Unknown user_id gets a profile -> create Profile + app_user_id identity
  - Shows up without a restart     -> it's a normal database write; every page
                                      reads from the database on each request
"""
import hashlib
import hmac
import time
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Event, Identity, Profile

# Reject requests whose signed timestamp is more than 5 minutes off. Without
# this, someone who captured one valid request could replay it forever.
MAX_SKEW_SECONDS = 300


class AppEvent(BaseModel):
    """The payload shape from the brief. Pydantic rejects anything else with a 422."""

    event_id: str = Field(min_length=1, max_length=100)
    event: Literal["app_open", "read_story", "link_click", "login"]
    user_id: str | None = Field(None, max_length=100)
    device_id: str = Field(min_length=1, max_length=100)
    timestamp: datetime
    properties: dict = Field(default_factory=dict)


def sign(secret: str, timestamp: str, body: bytes) -> str:
    """The signature the sender must put in the X-TPO-Signature header."""
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return "sha256=" + digest.hexdigest()


def verify_signature(
    secret: str,
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    now: float | None = None,
) -> bool:
    # Fail closed: no secret configured, or a header missing -> reject.
    if not secret or not timestamp or not signature:
        return False
    try:
        sent_at = int(timestamp)
    except ValueError:
        return False
    now = time.time() if now is None else now
    if abs(now - sent_at) > MAX_SKEW_SECONDS:
        return False
    # compare_digest: constant-time comparison, so timing leaks nothing.
    return hmac.compare_digest(sign(secret, timestamp, body), signature)


def _profile_for(session: Session, kind: str, value: str) -> Profile | None:
    """Follow an identity (e.g. kind="device_id") to its profile, if any."""
    return session.scalar(
        select(Profile).join(Identity).where(Identity.kind == kind, Identity.value == value)
    )


def process_app_event(session: Session, evt: AppEvent) -> str:
    """Store one event. Returns "created" or "duplicate"."""
    # 1. Dedupe: the same event_id twice is the same event.
    if session.scalar(select(Event.id).where(Event.external_id == evt.event_id)) is not None:
        return "duplicate"

    profile: Profile | None = None
    if evt.user_id:
        # 2. Logged-in event: find the person through app_users.csv's user_id.
        profile = _profile_for(session, "app_user_id", evt.user_id)
        if profile is None:
            # Unknown user_id: still a person. Profile without an email for now.
            profile = Profile()
            profile.identities.append(Identity(kind="app_user_id", value=evt.user_id))
            session.add(profile)
            session.flush()  # flush = send to the DB now, so profile.id exists

        # 3. Remember that this device belongs to this person (first owner wins
        #    if a device is shared; an edge case to revisit).
        if _profile_for(session, "device_id", evt.device_id) is None:
            session.add(Identity(profile=profile, kind="device_id", value=evt.device_id))
            session.flush()

        # 4. Stitching: every earlier ANONYMOUS event from this device now
        #    belongs to this person. One UPDATE, however many events there are.
        session.execute(
            update(Event)
            .where(Event.device_id == evt.device_id, Event.profile_id.is_(None))
            .values(profile_id=profile.id)
        )
    else:
        # 5. Anonymous event (user_id is null). If the device already logged in
        #    (its login arrived first: out of order), attach it immediately.
        profile = _profile_for(session, "device_id", evt.device_id)

    session.add(
        Event(
            profile=profile,
            source="app",
            event_type=evt.event,
            occurred_at=evt.timestamp,
            device_id=evt.device_id,
            external_id=evt.event_id,
            properties=evt.properties or None,
        )
    )
    try:
        session.commit()
    except IntegrityError:
        # Two copies arrived at the same instant and both passed step 1;
        # the unique constraint on external_id stops the second one.
        session.rollback()
        return "duplicate"
    return "created"
