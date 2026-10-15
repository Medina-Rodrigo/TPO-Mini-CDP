import pytest

from app.normalize import normalize_email

# Parametrize runs the same rest once per (input, expected) pair,
# so each messy case from the real CSVs gets its own pass/fail line.

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("zoe.allen235@gmail.com", "zoe.allen235@gmail.com"),
        ("  zoe.allen235@gmail.com ", "zoe.allen235@gmail.com"),
        ("Faith.Thomas60@Protonmail.Com", "faith.thomas60@protonmail.com"),
        ("ISAAC.TAYLOR434@PROTONMAIL.COM", "isaac.taylor434@protonmail.com"),
    ],
)
def test_valid_emails_are_cleaned(raw, expected):
    assert normalize_email(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [None, "", "   ", "not-an-email", "@gmail.com", "zoe@", "a@b@c.com", float("nan")],
)
def test_invalid_values_return_none(raw):
    assert normalize_email(raw) is None