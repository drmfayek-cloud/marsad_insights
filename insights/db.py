"""SQLite storage for users, audit, uploads, settings, approved period snapshots and the documents library index.

Uploaded register workbooks are never stored (documents deliberately added to the library are, see insights/library.py). Each upload is parsed into a de-identified dataset (gzip JSON on disk);
this database only records who uploaded what, when, and which version is published.
Change the schema by appending to MIGRATIONS, never by editing an earlier entry.
"""
import datetime as dt
import json
import os
import sqlite3
import threading

_local = threading.local()
DB_PATH = None

MIGRATIONS = [
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE, name TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('admin','kpmg','cnhi')),
        pw_hash TEXT NOT NULL, mfa_secret TEXT DEFAULT '', mfa_enabled INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1, failed_logins INTEGER DEFAULT 0, locked_until TEXT DEFAULT '',
        must_change_pw INTEGER DEFAULT 0, lang TEXT DEFAULT 'en', created_at TEXT, last_login TEXT DEFAULT '');

    CREATE TABLE audit (
        id INTEGER PRIMARY KEY, created_at TEXT, user_label TEXT, action TEXT, detail TEXT, ip TEXT);

    CREATE TABLE uploads (
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL, filename TEXT, sha256 TEXT, size INTEGER,
        label TEXT DEFAULT '', status TEXT DEFAULT 'staged', summary TEXT DEFAULT '{}', warnings TEXT DEFAULT '[]',
        created_by TEXT, created_at TEXT, published_at TEXT DEFAULT '', published_by TEXT DEFAULT '');
    CREATE INDEX ix_uploads_kind ON uploads(kind, status);

    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);

    CREATE TABLE snapshots (
        month TEXT PRIMARY KEY, data TEXT NOT NULL, datasets TEXT DEFAULT '{}', note TEXT DEFAULT '',
        created_by TEXT, created_at TEXT);

    CREATE TABLE pseudonyms (hash TEXT PRIMARY KEY, label TEXT NOT NULL, kind TEXT DEFAULT 'person');
    """,
    # v2 (1.7): documents library. Files are kept on disk under <data>/library; this records who, what and who may see it.
    """
    CREATE TABLE documents (
        id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL, period TEXT DEFAULT '', description TEXT DEFAULT '',
        visibility TEXT NOT NULL CHECK (visibility IN ('kpmg','shared')), filename TEXT NOT NULL, ext TEXT NOT NULL,
        size INTEGER, sha256 TEXT, text TEXT DEFAULT '', id_check TEXT DEFAULT '', id_count INTEGER DEFAULT 0,
        parent_id INTEGER DEFAULT NULL, status TEXT DEFAULT 'active', uploaded_by TEXT, uploaded_at TEXT);
    CREATE INDEX ix_documents_status ON documents(status, category);
    CREATE TABLE doc_links (doc_id INTEGER NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL, PRIMARY KEY (doc_id, kind, ref));
    CREATE INDEX ix_doc_links_ref ON doc_links(kind, ref);
    """,
    # v3 (1.8): status of each corrective action recorded at every register upload (history and 'changed since last upload')
    """
    CREATE TABLE action_log (batch INTEGER NOT NULL, at TEXT NOT NULL, action_id TEXT NOT NULL, status TEXT NOT NULL);
    CREATE INDEX ix_action_log ON action_log(action_id, batch);
    """,
]


def now():
    return dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")


def init(path):
    global DB_PATH
    DB_PATH = path
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE IF NOT EXISTS schema_version (v INTEGER)")
    row = con.execute("SELECT v FROM schema_version").fetchone()
    v = row[0] if row else 0
    for i, sql in enumerate(MIGRATIONS[v:], start=v + 1):
        con.executescript(sql)
        con.execute("DELETE FROM schema_version")
        con.execute("INSERT INTO schema_version VALUES (?)", (i,))
    con.commit()
    con.close()


def conn():
    c = getattr(_local, "con", None)
    if c is None or getattr(_local, "path", None) != DB_PATH or getattr(_local, "pid", None) != os.getpid():
        c = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=30000")
        _local.con, _local.path, _local.pid = c, DB_PATH, os.getpid()
    return c


def q(sql, args=()):
    return conn().execute(sql, args).fetchall()


def q1(sql, args=()):
    return conn().execute(sql, args).fetchone()


def val(sql, args=(), default=None):
    r = q1(sql, args)
    return default if r is None or r[0] is None else r[0]


def ex(sql, args=()):
    return conn().execute(sql, args).lastrowid


def insert(table, **kw):
    cols = ", ".join(kw)
    marks = ", ".join("?" for _ in kw)
    return ex(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(kw.values()))


def update(table, id_, **kw):
    if kw:
        sets = ", ".join(f"{k}=?" for k in kw)
        ex(f"UPDATE {table} SET {sets} WHERE id=?", tuple(kw.values()) + (id_,))


def get_setting(key, default=""):
    return val("SELECT value FROM settings WHERE key=?", (key,), default)


def set_setting(key, value):
    ex("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
       (key, str(value)))


def loads(s, default=None):
    try:
        return json.loads(s) if s else (default if default is not None else {})
    except ValueError:
        return default if default is not None else {}


def dumps(o):
    return json.dumps(o, ensure_ascii=False, default=str)
