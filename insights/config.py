"""Loads config/settings.yaml and config/kpis.yaml (the KPI dictionary)."""
import os

import yaml

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")

with open(os.path.join(BASE, "settings.yaml"), encoding="utf-8") as f:
    SETTINGS = yaml.safe_load(f)
with open(os.path.join(BASE, "kpis.yaml"), encoding="utf-8") as f:
    _K = yaml.safe_load(f)

TPA_MAP = {str(k).strip().lower(): v for k, v in (SETTINGS.get("tpa_names") or {}).items()}
FAMILIES = SETTINGS.get("flag_families") or {}
WEEKEND = set(SETTINGS.get("weekend_days") or [4, 5])

PAGES = _K["pages"]                      # [{code, slug, en, ar}]
KPIS = {k["id"]: k for k in _K["kpis"]}  # id -> definition
DECISIONS_VERSION = _K.get("version", "")
PAGE_BY_SLUG = {p["slug"]: p for p in PAGES}


def kpis_for(page_code):
    return [k for k in _K["kpis"] if k["page"] == page_code]
