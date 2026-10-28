"""Sign-in: scrypt passwords, authenticator-app codes (TOTP, RFC 6238), lockout, roles and CSRF."""
import base64
import datetime as dt
import functools
import hashlib
import hmac
import os
import secrets
import struct
import time
from urllib.parse import quote

from flask import abort, g, redirect, request, session, url_for

from . import db

# role -> what it may do. Admin uploads, publishes and closes periods; KPMG sees internal cuts (per reviewer);
# CNHI sees every page without internal cuts. The CFO is a CNHI user and lands on the executive page.
ROLES = {
    "admin": "Administrator (KPMG)",
    "kpmg": "KPMG viewer",
    "cnhi": "CNHI viewer",
}
INTERNAL = {"admin", "kpmg"}

MAX_FAILED = 5
LOCK_MINUTES = 15


# ------------------------------------------------------------------ passwords
def hash_pw(pw):
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def check_pw(pw, stored):
    try:
        _, s, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=base64.b64decode(s), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


def pw_problem(pw):
    if len(pw) < 12:
        return "Use at least 12 characters."
    has = [any(c.islower() for c in pw), any(c.isupper() for c in pw), any(c.isdigit() for c in pw),
           any(not c.isalnum() for c in pw)]
    if sum(has) < 3:
        return "Mix at least three of: lower case, upper case, digits, symbols."
    return None


def temp_password():
    return secrets.token_urlsafe(9) + "a7!"


# ------------------------------------------------------------------ TOTP (authenticator app)
def new_mfa_secret():
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def totp(secret, for_time=None, step=30, digits=6):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    counter = int((for_time if for_time is not None else time.time()) // step)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def check_totp(secret, code):
    code = (code or "").strip().replace(" ", "")
    if not secret or not code.isdigit():
        return False
    t = time.time()
    return any(hmac.compare_digest(totp(secret, t + w * 30), code) for w in (-1, 0, 1))


def otpauth_uri(secret, email):
    return f"otpauth://totp/{quote('MARSAD Insights')}:{quote(email)}?secret={secret}&issuer={quote('MARSAD Insights')}"


# ------------------------------------------------------------------ session helpers
def current_user():
    uid = session.get("uid")
    if not uid or not session.get("full"):
        return None
    u = db.q1("SELECT * FROM users WHERE id=? AND active=1", (uid,))
    if u is None:
        return None
    hours = float(os.environ.get("MARSAD_SESSION_HOURS", "8"))
    started = session.get("at", 0)
    if time.time() - started > hours * 3600:
        session.clear()
        return None
    return u


def login_required(view):
    @functools.wraps(view)
    def wrapped(*a, **kw):
        if g.user is None:
            return redirect(url_for("login", next=request.path))
        if g.user["must_change_pw"] and request.endpoint not in ("account", "logout", "set_lang"):
            return redirect(url_for("account"))
        return view(*a, **kw)
    return wrapped


def roles_required(*roles):
    def deco(view):
        @functools.wraps(view)
        @login_required
        def wrapped(*a, **kw):
            if g.user["role"] not in roles:
                abort(403)
            return view(*a, **kw)
        return wrapped
    return deco


def is_locked(u):
    return bool(u["locked_until"]) and u["locked_until"] > db.now()


def register_failure(u):
    n = (u["failed_logins"] or 0) + 1
    lock = ""
    if n >= MAX_FAILED:
        lock = (dt.datetime.now() + dt.timedelta(minutes=LOCK_MINUTES)).replace(microsecond=0).isoformat(sep=" ")
        n = 0
    db.update("users", u["id"], failed_logins=n, locked_until=lock)


def audit(action, detail=""):
    label = g.user["email"] if getattr(g, "user", None) else session.get("pending_email", "-")
    db.insert("audit", created_at=db.now(), user_label=label, action=action, detail=str(detail)[:500],
              ip=request.headers.get("X-Forwarded-For", request.remote_addr or "")[:64] if request else "")


# ------------------------------------------------------------------ CSRF
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_csrf():
    if request.method == "POST":
        sent = request.form.get("csrf") or request.headers.get("X-CSRF", "")
        if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
            abort(400)
