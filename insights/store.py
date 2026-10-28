"""Versioned datasets. Each upload becomes one gzip JSON file; publishing makes it the current version for its kind.

Kinds:
  F1 daily register (MARSAD Daily Record & Action Tracker)
  F2 GSS Assurance Workbook
  F3 hospital disputes tracker
  F4 quarterly accounting report
  F5 governance register
"""
import gzip
import json
import os

from . import db

KINDS = {
    "F1": "Daily MARSAD register",
    "F2": "GSS Assurance Workbook",
    "F3": "Hospital disputes tracker",
    "F4": "Quarterly accounting report",
    "F5": "Governance register",
}
KINDS_AR = {
    "F1": "سجل مرصد اليومي",
    "F2": "مصنف ضمان GSS",
    "F3": "سجل اعتراضات المستشفيات",
    "F4": "التقرير المحاسبي الربعي",
    "F5": "سجل الحوكمة",
}
DATA_DIR = None
_cache = {}


def init(data_dir):
    global DATA_DIR
    DATA_DIR = os.path.join(data_dir, "datasets")
    os.makedirs(DATA_DIR, exist_ok=True)


def _path(upload_id):
    return os.path.join(DATA_DIR, f"{int(upload_id)}.json.gz")


def save(upload_id, data):
    with gzip.open(_path(upload_id), "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)


def load(upload_id):
    if upload_id in _cache:
        return _cache[upload_id]
    p = _path(upload_id)
    if not os.path.exists(p):
        return None
    with gzip.open(p, "rt", encoding="utf-8") as f:
        data = json.load(f)
    if len(_cache) > 20:
        _cache.clear()
    _cache[upload_id] = data
    return data


def delete(upload_id):
    _cache.pop(upload_id, None)
    p = _path(upload_id)
    if os.path.exists(p):
        os.remove(p)


def current_ids():
    """{kind: upload_id} of the published versions."""
    out = {}
    for k in KINDS:
        v = db.get_setting(f"current_{k}", "")
        if v:
            out[k] = int(v)
    return out


def current():
    """{kind: dataset} for every published kind (missing kinds are absent)."""
    out = {}
    for k, uid in current_ids().items():
        d = load(uid)
        if d is not None:
            out[k] = d
    return out


def publish(upload_id, user_label):
    up = db.q1("SELECT * FROM uploads WHERE id=?", (upload_id,))
    if up is None or load(upload_id) is None:
        raise ValueError("Upload not found")
    prev = db.get_setting(f"current_{up['kind']}", "")
    if prev and prev != str(upload_id):
        db.ex("UPDATE uploads SET status='superseded' WHERE id=?", (int(prev),))
    db.update("uploads", upload_id, status="published", published_at=db.now(), published_by=user_label)
    db.set_setting(f"current_{up['kind']}", upload_id)
    return up["kind"]


def discard(upload_id):
    db.update("uploads", upload_id, status="discarded")
    delete(upload_id)
