"""
Shared Normalization Helpers

Every place that reads an email (CSV import, webhook, lookup search)
must call normalize_email() so the same person always produces the
same key. Keeping this in ONE function is what makes dedupe reliable.

"""

def normalize_email(raw: str | None) -> str | None:
    # Missing values show up as None, "" or NaN (pandas' float for blanks)
    # Anything that isn't a string can't be an email.
    if not isinstance(raw, str):
        return None

    # Fix the two problems found in the data: stray whitespace and inconsistent case
    email = raw.strip().lower()

    # Minimal validity check: exactly one "@" with text on both sides.
    # Partition() splits on the first "@"; if there isn't one, sep is ""
    local, sep, domain = email.partition("@")
    if not sep or not local or not domain or "@" in domain:
        return None

    return email


# Different systems name the same channel differently: beehiiv says "X"
# website UTMs say "twitter", we'll map aliases to one canonical lowercase name
SOURCE_ALIASES = {"twitter": "x"}

def normalize_source(raw: str | None) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    source = raw.strip().lower()
    # .get(key, default): use the alias if there is one, otherwise keep it
    return SOURCE_ALIASES.get(source, source)

