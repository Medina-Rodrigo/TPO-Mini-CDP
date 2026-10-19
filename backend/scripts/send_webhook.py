"""Send a correctly signed test event to the webhook (for demos and testing).

Run from backend/ with the venv active, e.g.:
  python scripts/send_webhook.py http://localhost:8000 --event app_open --device d_demo1
  python scripts/send_webhook.py http://localhost:8000 --event login --device d_demo1 --user u_2b6447a3
  python scripts/send_webhook.py http://localhost:8000 --event-id evt_same  (run twice: 2nd is a duplicate)

Reads WEBHOOK_SECRET from the environment or backend/.env.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so `app` imports work
from dotenv import load_dotenv  # noqa: E402

from app.webhook import sign  # noqa: E402

load_dotenv()

parser = argparse.ArgumentParser()
parser.add_argument("base_url")
parser.add_argument("--event", default="app_open", choices=["app_open", "read_story", "link_click", "login"])
parser.add_argument("--user", default=None, help="user_id (omit for an anonymous event)")
parser.add_argument("--device", default="d_demo1")
parser.add_argument("--event-id", default=None)
parser.add_argument("--timestamp", default=None, help="ISO time it happened, e.g. 2026-09-27T10:00:00Z")
parser.add_argument("--story", default=None)
args = parser.parse_args()

payload = {
    "event_id": args.event_id or f"evt_{uuid.uuid4().hex[:8]}",
    "event": args.event,
    "user_id": args.user,
    "device_id": args.device,
    "timestamp": args.timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "properties": {"story": args.story} if args.story else {},
}
body = json.dumps(payload).encode()
ts = str(int(time.time()))

request = urllib.request.Request(
    args.base_url.rstrip("/") + "/webhooks/app",
    data=body,
    method="POST",
    headers={
        "Content-Type": "application/json",
        "X-TPO-Timestamp": ts,
        "X-TPO-Signature": sign(os.environ["WEBHOOK_SECRET"], ts, body),
    },
)
print("Sent:", json.dumps(payload))
try:
    with urllib.request.urlopen(request) as response:
        print(response.status, response.read().decode())
except urllib.error.HTTPError as err:
    print(err.code, err.read().decode())
