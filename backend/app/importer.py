"""

Load the three CSVs into Postgres as one unified set of profiles

Run from backend/: python -m app.importer data

This is a FULL reload: it empties the tables first, so re-running it
is safe, but it also erases webhook events

Production fix: upserts

"""

import csv
import sys
from datetime import date, datetime, timezone
from pathlib import Path 

from sqlalchemy import text

from app.db import SessionLocal
from app.models import Event, Identity, Profile
from app.normalize import normalize_email, normalize_source

def read_csv(path: Path) -> list[dict[str,str]]:
    # DictReader turns each row into a dict keyed by the header row
    # Stripping every value handles stray whitespace in any column
with path.open(newline="", encoding="utf-8") as f:
    return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]

def parse_date(value: str) -> date | None:
    # Blank cells become None instead of crashing fromisoformat("")
    return date.fromisoformat(value) if value else None

def parse_timestamp(value: str) -> datetime:
    # CSV timestamps have no timezone, treat them as UTC and document it
    # webhook timestamps arrive in UTC and python refuses to compare
    # timezone-aware and timezone-naive datetimes
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)

def subscriber_fields(row: dict[str, str]) -> dict:
    # The newsletter columns, cleaned, 'or None' turns "" into a real NULL
    return{
        "signup_date": parse_date(row["signup_date"]),
        "status": row["status"].lower() or None,
        "acquisiton_source": normalize_source(row["acquisition_source"]),
        "last_open_date": parse_date(row["last_open_date"]),
    }

def run(data_dir: Path) -> None:
    stats = {"skipped_subscribers": 0, "duplicate_subscribers": 0, "app_only_profiles": 0}

    # 'with' closes the sessiona the end, if anything raises
    # before commit(), nothing is saved
    with SessionLocal() as session:
        # We start clean, TRUNCATE empties tables instantly
        # RESTART IDENTITY resets the id counters
        # CASCADE handles the foreign keys
        session.execute(text("TRUNCATE events, identities, profiles RESTART IDENTITY CASCADE"))

        # The dedupe index: normalized email -> the ONE Profile for that person
        profiles: dict[str, Profile] = {}

        def get_or_create_profile(email: str) -> Profile:
            if email not in profiles:
                profiles[email] = Profile(email = email)
                session.add(profiles[email])
            return profiles[email]

            # --- 1. Subscribers: one profile per normalized email ---
            for row in read_csv(data_dir / "subscribers.csv"):
                email = nromalize_email(row["email"])
                if email is None:
                    stats["skipped_subscribers"] += 1 # blank rows, "not-an-email"
                    continue
                if email in profiles:
                    stats["duplicate_subscribers"] += 1
                profile = get_or_create_profile(email)
                # Dedupe rule: the first row wins, a later dupe only fills in
                # fields that the first row left blank

                for field, value in subscriber_fields(row).items():
                    if getattr(profile, field) is None:
                        setattr(profile, field, value)

                