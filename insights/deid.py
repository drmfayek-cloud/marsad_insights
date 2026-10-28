"""De-identification applied at upload (Decision D-14).

* Case, claim and approval references are replaced by a keyed hash (HMAC-SHA256, key kept on the server),
  so the same reference matches across uploads but cannot be read back.
* Staff names become stable pseudonyms (Reviewer 1, Reviewer 2, ...).
* Patient identifiers and free-text narratives are never read from the workbook at all.
"""
import hashlib
import hmac
import os
import secrets

from . import db

_KEY = None


def init(data_dir):
    """Load the hashing key from MARSAD_HASH_KEY or a key file kept in the data directory."""
    global _KEY
    env = os.environ.get("MARSAD_HASH_KEY", "")
    if env:
        _KEY = env.encode()
        return
    path = os.path.join(data_dir, "hash.key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
        os.chmod(path, 0o600)
    with open(path) as f:
        _KEY = f.read().strip().encode()


def ref(value):
    """Keyed hash of a reference; blank stays blank."""
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return hmac.new(_KEY, s.encode(), hashlib.sha256).hexdigest()[:16]


def person(name, prefix="Reviewer"):
    """Stable pseudonym for a staff name."""
    if name is None or not str(name).strip():
        return ""
    h = ref("person:" + str(name).strip().lower())
    row = db.q1("SELECT label FROM pseudonyms WHERE hash=?", (h,))
    if row:
        return row["label"]
    n = (db.val("SELECT COUNT(*) FROM pseudonyms WHERE kind=?", (prefix,), 0) or 0) + 1
    label = f"{prefix} {n}"
    db.insert("pseudonyms", hash=h, label=label, kind=prefix)
    return label
