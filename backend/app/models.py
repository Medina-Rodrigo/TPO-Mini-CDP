"""
Databse Tables for the CDP

A profile is one real person, everything else hangs off of it:
- newsletter fields (from subscribers.csv) live on the profile
- Identity rows map other IDs (visitor_id, app_user_id, device_id) to it
- Event rows are things the person did, on the website or in the app
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

class Profile(Base):
    __tablename__= "profiles"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Normalized email. unique=True makes Postgres itself reject duplicates
    # It's optimal because an app user_id we've never seen still
    # gets a profile before we know their email
    # Postgres allows many NULLs in a unique column, so that's safe
    email: Mapped[str | None] = mapped_column(String(320), unique = True)

    # Newsletter fields, all optional since not every person is a subscriber
    signup_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(String(20))
    acquisition_source: Mapped [str | None] = mapped_column(String(50))
    last_open_date: Mapped[date | None] = mapped_column(Date)

    # server_default: Postgres fills in the time when the row is inserted
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone = True), server_default = func.now()
    )

    # relationship() lets Python code do profile.events instead of writing
    # a JOIN by hand, back_populates link each side to the other
    identities: Mapped[list["Identity"]] = relationship(back_populates = "profile")
    events: Mapped[list["Event"]] = relationship(back_populates = "profile")

class Identity(Base):
    __tablename__ = "identities"
    #The same visitor_id can never point to two different people
    __table_args__ = (UniqueConstraint("kind", "value"),)

    id: Mapped[int] = mapped_column(primary_key = True)
    # ForeignKey: must match a real profile id, index = True speeds up
    # "find all identities for this profile"
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), index = True)
    kind: Mapped[str] = mapped_column(String(20)) # visitor_id, app_user_id, device_id
    value: Mapped[str] = mapped_column(String(100))

    profile: Mapped[Profile] = relationship(back_populates = "identities")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key = True)

    # Anonymous events are stored now and attached to a profile later
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id"), index = True)

    source:  Mapped[str] = mapped_column(String(10)) # web or app
    event_type: Mapped[str] = mapped_column(String(30)) # page_view, read_story, etc

    # When it happened according to the data
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), index = True)

    #The raw IDs the event arrived with, kept so it can be attached later
    visitor_id: Mapped[str | None] = mapped_column(String(100), index = True)
    device_id: Mapped[str | None] = mapped_column(String(100), index = True)

    # Website-only details
    page: Mapped[str | None] = mapped_column(String(500))
    utm_source: Mapped[str | None] = mapped_column(String(50))

    # The webhook's event_id, unique = True means a dup delivery of
    # the same event is rejected by the database: dedupe for free
    external_id: Mapped[str | None] = mapped_column(String(100), unique = True)

    # Free form extras
    # JSONB is Postgres' binary JSON type, which can be quiered and indexed
    properties: Mapped[dict | None] = mapped_column(JSONB)

    profile: Mapped[Profile | None] = relationship(back_populates = "events")

