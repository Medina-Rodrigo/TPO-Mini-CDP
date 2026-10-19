"""Plain-English assistant for the Growth team that never sees PII.

How PII is kept out of the model:
  1. The model never gets rows or SQL access. It can only call the tools below.
  2. Each tool runs on OUR server and returns aggregates to the model: counts,
     groupings, page names, or a count + description of a list it built.
  3. When a tool builds a list of people, the list (with emails) goes into
     `tables`, which is returned straight to the browser. It is never put into
     a message to the model.
  4. Emails typed into the question are redacted before it is sent.
  5. Defense in depth: every tool result is scanned for anything email-shaped
     before it leaves the server; if one is found, the request fails.
The `trace` returned to the UI shows exactly what the model received.
"""
import json
import re
from collections import Counter
from datetime import datetime, time, timedelta, timezone

import anthropic
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.config import TODAY
from app.models import Event, Profile
from app.segments import SegmentFilters, profile_row, segment_query

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def redact(text: str) -> str:
    return EMAIL_RE.sub("[email removed]", text)


SYSTEM_PROMPT = """You are a data assistant for The Pour Over's Growth team.
Today is 2026-09-28. "Last month" means 2026-08-01 to 2026-08-31.
Answer only from tool results; never guess numbers.
You never see personal data. Tools return counts, groupings and page names.
When the user wants a list of people, call build_segment or top_engaged: the
list is shown to the user automatically, so describe it (how many people,
which filters) instead of listing anyone.
Acquisition sources: instagram, facebook, referral, google, direct, podcast, x.
"Went cold" means no newsletter open in the last 30 days unless told otherwise.
Keep answers short and plain; no jargon."""

# JSON Schema for the filters, shared by several tools.
FILTERS_SCHEMA = {
    "type": "object",
    "description": "Optional filters, all combined with AND.",
    "properties": {
        "source": {"type": "string", "description": "Acquisition source, e.g. instagram"},
        "status": {"type": "string", "enum": ["active", "unsubscribed"]},
        "signed_up_from": {"type": "string", "format": "date"},
        "signed_up_to": {"type": "string", "format": "date"},
        "not_opened_days": {"type": "integer", "description": "No newsletter open in this many days"},
        "min_events": {"type": "integer", "description": "At least this many web/app events"},
        "has_app": {"type": "boolean"},
    },
}

TOOLS = [
    {
        "name": "count_segment",
        "description": "Count subscribers matching filters. Returns only a number.",
        "input_schema": {
            "type": "object",
            "properties": {"filters": FILTERS_SCHEMA},
            "required": ["filters"],
        },
    },
    {
        "name": "breakdown",
        "description": "Count subscribers matching filters, grouped by a field.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filters": FILTERS_SCHEMA,
                "group_by": {"type": "string", "enum": ["acquisition_source", "status", "signup_month"]},
            },
            "required": ["filters", "group_by"],
        },
    },
    {
        "name": "build_segment",
        "description": (
            "Build a list of subscribers matching filters for the user to view and export. "
            "You receive only the count; the list is shown to the user directly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"filters": FILTERS_SCHEMA, "title": {"type": "string"}},
            "required": ["filters"],
        },
    },
    {
        "name": "top_engaged",
        "description": (
            "Build a list of the most engaged readers, ranked by web visits + app events "
            "in the last N days. You receive only the count and score range."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 50},
                "days": {"type": "integer", "default": 30},
            },
        },
    },
    {
        "name": "first_pages",
        "description": (
            "Which website pages people visit first (each person's earliest page view). "
            "Optionally only people who subscribed within the last N days."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "signed_up_within_days": {"type": "integer"},
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
]


def _count(db: Session, f: SegmentFilters) -> int:
    return db.scalar(select(func.count()).select_from(segment_query(f).subquery()))


def run_tool(db: Session, name: str, args: dict) -> tuple[dict, dict | None]:
    """Returns (what the MODEL sees, optional table for the BROWSER only)."""
    if name == "count_segment":
        f = SegmentFilters.model_validate(args.get("filters") or {})
        return {"count": _count(db, f)}, None

    if name == "breakdown":
        f = SegmentFilters.model_validate(args.get("filters") or {})
        base = segment_query(f).subquery()
        column = {
            "acquisition_source": base.c.acquisition_source,
            "status": base.c.status,
            "signup_month": func.to_char(base.c.signup_date, "YYYY-MM"),
        }[args["group_by"]]
        rows = db.execute(
            select(column.label("group"), func.count().label("n"))
            .group_by(column)
            .order_by(func.count().desc())
        ).all()
        return {"groups": [{"group": g, "count": n} for g, n in rows]}, None

    if name == "build_segment":
        f = SegmentFilters.model_validate(args.get("filters") or {})
        people = db.scalars(segment_query(f).order_by(Profile.id)).all()
        table = {
            "title": args.get("title") or "Segment",
            "columns": ["email", "status", "acquisition_source", "signup_date", "last_open_date"],
            "rows": [[profile_row(p)[c] for c in ("email", "status", "acquisition_source", "signup_date", "last_open_date")] for p in people],
        }
        return {"count": len(people), "shown_to_user": True}, table

    if name == "top_engaged":
        limit = min(int(args.get("limit") or 50), 500)
        days = int(args.get("days") or 30)
        since = datetime.combine(TODAY - timedelta(days=days), time.min, tzinfo=timezone.utc)
        rows = db.execute(
            select(Profile, func.count(Event.id).label("n"))
            .join(Event, Event.profile_id == Profile.id)
            .where(Event.occurred_at >= since, Profile.email.is_not(None))
            .group_by(Profile.id)
            .order_by(func.count(Event.id).desc())
            .limit(limit)
        ).all()
        table = {
            "title": f"Most engaged readers (last {days} days)",
            "columns": ["email", "acquisition_source", f"events_last_{days}_days"],
            "rows": [[p.email, p.acquisition_source, n] for p, n in rows],
        }
        summary = {"count": len(rows), "shown_to_user": True}
        if rows:
            summary |= {"most_events": rows[0][1], "fewest_events": rows[-1][1]}
        return summary, table

    if name == "first_pages":
        q = (
            select(Event.profile_id, Event.page)
            .where(Event.source == "web", Event.profile_id.is_not(None))
            .order_by(Event.profile_id, Event.occurred_at)
        )
        within = args.get("signed_up_within_days")
        if within:
            q = q.join(Profile, Profile.id == Event.profile_id).where(
                Profile.signup_date >= TODAY - timedelta(days=int(within))
            )
        first: dict[int, str] = {}
        for profile_id, page in db.execute(q):
            first.setdefault(profile_id, page)  # rows are time-ordered: keep the earliest
        top = Counter(first.values()).most_common(int(args.get("limit") or 10))
        return {"people": len(first), "pages": [{"page": p, "people": n} for p, n in top]}, None

    return {"error": f"Unknown tool {name}"}, None


def ask(db: Session, question: str) -> dict:
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    safe_question = redact(question)
    messages: list[dict] = [{"role": "user", "content": safe_question}]
    tables: list[dict] = []
    trace: list[dict] = [{"step": "question", "sent_to_model": safe_question}]

    # Tool-use loop: the model either answers or asks us to run tools.
    for _ in range(6):
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )
        if response.stop_reason != "tool_use":
            answer = "".join(b.text for b in response.content if b.type == "text")
            return {"answer": answer, "tables": tables, "trace": trace}

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                model_result, table = run_tool(db, block.name, block.input)
            except Exception as exc:  # bad filters etc.: tell the model, don't crash
                model_result, table = {"error": str(exc)[:300]}, None
            payload = json.dumps(model_result, default=str)
            # Defense in depth: nothing email-shaped may ever reach the model.
            if EMAIL_RE.search(payload):
                raise RuntimeError("PII guard: tool result contained an email address")
            if table:
                tables.append(table)
            trace.append({"step": f"tool: {block.name}", "input": block.input, "sent_to_model": model_result})
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": payload})
        messages.append({"role": "user", "content": results})

    return {"answer": "Sorry, that question took too many steps.", "tables": tables, "trace": trace}
