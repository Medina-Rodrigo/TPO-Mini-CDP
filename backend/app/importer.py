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
        "acquisition_source": normalize_source(row["acquisition_source"]),
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
            email = normalize_email(row["email"])
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

        # --- 2. App users: link each user_id to a profile by email ---
        for row in read_csv(data_dir / "app_users.csv"):
            email = normalize_email(row["email"])
            if email is None:
                continue
            if email not in profiles:
                stats["app_only_profiles"] += 1
            profile = get_or_create_profile(email)
            profile.identities.append(Identity(kind="app_user_id", value = row["user_id"]))
            # Account creation is the first app activity that we know about
            session.add(Event(
                profile = profile,
                source = "app",
                event_type = "account_created",
                occurred_at = parse_timestamp(row["created_at"]),
            ))

        # --- 3. Web events, in two passes ---
        web_rows = read_csv(data_dir / "web_events.csv")

        # Pass 1: learn which visitor_id belongs to which profile.
        # The email might only appear on a visitor's later date
        # so we need the full mapping before storing any visits
        visitor_to_profile: dict[str, Profile] = {}
        for row in web_rows:
            email = normalize_email(row["email"])
            visitor_id = row["visitor_id"]
            if email and visitor_id not in visitor_to_profile:
                profile = get_or_create_profile(email)
                visitor_to_profile[visitor_id] = profile
                profile.identities.append(Identity(kind = "visitor_id", value = visitor_id))

        # Pass 2: store every visit, known visitors are attached to their
        # profile, the rest stay anonymous (profile = None) for later
        for row in web_rows:
            session.add(Event(
                profile = visitor_to_profile.get(row["visitor_id"]),
                source = "web",
                event_type = "page_view",
                occurred_at = parse_timestamp(row["timestamp"]),
                visitor_id = row ["visitor_id"],
                page = row["page"] or None,
                utm_source = normalize_source(row["utm_source"]),
                properties = {"utm_source_raw": row["utm_source"]} if row["utm_source"] else None,
            ))

        session.commit()
    print(f"Profiles: {len(profiles)} | visitors linked: {len(visitor_to_profile)} | " f"web events: {len(web_rows)}")
    print (stats)

if __name__ == "__main__":
    # sys.argv holds the command-line words; argv[1] is the folder, default is "data"
    run(Path(sys.argv[1] if len(sys.argv) > 1 else "data"))

        


                