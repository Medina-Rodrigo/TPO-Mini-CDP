from app.webhook import sign, verify_signature

SECRET = "test-secret"
BODY = b'{"event_id":"evt_1","event":"app_open","user_id":null,"device_id":"d_1","timestamp":"2026-09-28T14:22:05Z"}'
NOW = 1_790_000_000


def test_valid_signature_is_accepted():
    ts = str(NOW)
    assert verify_signature(SECRET, BODY, ts, sign(SECRET, ts, BODY), now=NOW)


def test_tampered_body_is_rejected():
    ts = str(NOW)
    signature = sign(SECRET, ts, BODY)
    assert not verify_signature(SECRET, BODY.replace(b"app_open", b"login"), ts, signature, now=NOW)


def test_wrong_secret_is_rejected():
    ts = str(NOW)
    assert not verify_signature(SECRET, BODY, ts, sign("other-secret", ts, BODY), now=NOW)


def test_old_timestamp_is_rejected_to_stop_replays():
    ts = str(NOW - 3600)  # signed an hour ago
    assert not verify_signature(SECRET, BODY, ts, sign(SECRET, ts, BODY), now=NOW)


def test_missing_headers_or_secret_fail_closed():
    ts = str(NOW)
    good = sign(SECRET, ts, BODY)
    assert not verify_signature(SECRET, BODY, None, good, now=NOW)
    assert not verify_signature(SECRET, BODY, ts, None, now=NOW)
    assert not verify_signature("", BODY, ts, good, now=NOW)
