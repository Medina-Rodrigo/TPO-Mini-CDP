# TPO Mini CDP

A small customer data platform for The Pour Over: it merges newsletter subscribers, website visits and app accounts into one profile per person, lets the Growth team look anyone up and build segments, takes app events in real time through a signed webhook, and answers plain-English questions with an AI assistant that never sees personal data.

**Stack:** FastAPI (Python) · PostgreSQL · SQLAlchemy · React + TypeScript (Vite) · Claude API (tool use) · Railway

## How it fits together

- `backend/app/importer.py` loads the three CSVs into three tables:
  - `profiles`: one row per person, with newsletter fields
  - `identities`: visitor_id, app_user_id and device_id, each pointing to a profile
  - `events`: web visits and app events; a NULL profile means anonymous for now
- `backend/app/normalize.py` holds the **one** shared email and source normalizer. The importer, the lookup and the segment filters all use it.
- `backend/app/main.py` is the API, the webhook, and it serves the built React app from `backend/static`.
- `backend/app/segments.py` is one query builder shared by the Segments page and the AI assistant.
- `backend/app/webhook.py` verifies the HMAC signature and handles dedupe, out-of-order events, login stitching and unknown users.
- `backend/app/assistant.py` runs the AI assistant and its PII boundary (see below).

## Data rules

- **Dedupe:** emails are trimmed and lowercased. The first row wins, and later duplicates only fill blank fields. Rows with a blank or invalid email are skipped (8 fully blank rows, plus `not-an-email` and `@gmail.com`): 10 in total.
- **Linking:** an app account links to a subscriber by normalized email. A website visitor links when *any* of their visits carries an email, and then *all* of that visitor's visits attach. That stitches 8,441 of the 10,000 visits, compared with 1,400 that carry an email directly.
- **Sources:** `X` and `twitter` map to `x`. The raw UTM value is kept in `properties`.
- **Time:** "today" is 2026-09-28, as the brief specifies. CSV timestamps have no timezone and are treated as UTC.

## Webhook: `POST /webhooks/app`

Requests must be signed with HMAC-SHA256, the same pattern Stripe and GitHub use:

```
X-TPO-Timestamp: <unix seconds>
X-TPO-Signature: sha256=<hex HMAC of "<timestamp>.<raw body>" using WEBHOOK_SECRET>
```

- **Requests are rejected** if they have a bad signature, a timestamp more than 5 minutes off (replay protection), or no secret is configured.
- **Duplicates:** `event_id` is unique in the database, so a second delivery returns `{"status": "duplicate"}`.
- **Out of order:** events are stored with the time they *happened* and always sorted by it.
- **Login stitching:** the first event with a `user_id` links that `device_id` to the person and attaches the device's earlier anonymous events. Anonymous events that arrive *after* the login attach right away.
- **Unknown `user_id`:** the user still gets a profile, with no email yet.

Send a signed test event with `python scripts/send_webhook.py <base_url> --event login --user u_2b6447a3 --device d_demo1`.

## The AI assistant and PII

The model never gets rows or database access. It can only call five server-side tools: `count_segment`, `breakdown`, `build_segment`, `top_engaged` and `first_pages`. These return counts, groupings and page names. When a tool builds a list of people, the list (with emails) goes straight to the browser and is never added to a model message. Emails typed into a question are redacted before sending, and every tool result is scanned for email-shaped text before it leaves the server. The UI's **"What the AI model actually saw"** panel shows the exact data sent to the model.

## Run it locally

Requirements: Python 3.12, Node 20+, PostgreSQL 16.

```bash
# database
sudo service postgresql start
createdb tpo_cdp

# backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # then fill in the values
python -m app.create_tables
python -m app.importer data     # full reload of the CSVs
python -m pytest                # tests

# frontend (builds into backend/static)
cd ../frontend && npm install && npm run build

# run
cd ../backend && fastapi dev app/main.py
# open http://localhost:8000 and log in with APP_USERNAME / APP_PASSWORD
```

## Known limitations / next steps

- The importer is a full reload (truncate, then load), so re-running it erases webhook events. Next step: upserts.
- Schema changes use `create_all`. Next step: Alembic migrations.
- A shared device belongs to the first user who logs in on it.
- No automated tests yet for the database-backed webhook rules; the signature check and normalizers are tested.
- The UI uses a single shared password over HTTP Basic auth. Next step: SSO and per-user accounts.
