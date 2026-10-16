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
from sqlalchemy.orm import Mapped, mapped_column, relationships

from app.db import Base

class Profile(Base):
    __tablename__=:"profiles"

    id: Mapped[int] = mapped_column(primary_key=True)

    