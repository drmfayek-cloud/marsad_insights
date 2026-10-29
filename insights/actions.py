"""Corrective-action tracker: the status of every action, calculated from its dates (never typed), its history across
published versions of the F6 register, and the Excel download.

Status rules (agreed 29 Oct 2026, thresholds in config/settings.yaml):
  Cancelled                      Status column = Cancelled
  Completed - verified           completed on or before the as-at date, with an evidence reference
  Completed - evidence pending   completed, no evidence reference
  Not started                    no opened date yet (or opened after the as-at date)
  Overdue                        open and past its due date
  Due soon                       open and due within 7 days
  On track                       open, due later (or no due date: flagged at upload)
"""
import datetime as dt
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import config, db, store
from .i18n import lang, pick

CA = config.SETTINGS.get("corrective_actions") or {}
DUE_SOON = int(CA.get("due_soon_days", 7))
STALE = int(CA.get("stale_days", 7))

# key -> (English, Arabic, tone, Excel fill)
STATUS = {
    "overdue": ("Overdue", "متأخر", "coral", "FDE2DA"),
    "due_soon": ("Due soon", "يستحق قريبا", "amber", "FFF1D6"),
    "on_track": ("On track", "في المسار", "green", "DDF3E3"),
    "not_started": ("Not started", "لم يبدأ", "slate", "ECEFF3"),
    "done_pending": ("Completed - evidence pending", "منجز - بانتظار الدليل", "amber", "FFF1D6"),
    "done_verified": ("Completed - verified", "منجز - موثق", "green", "DDF3E3"),
    "cancelled": ("Cancelled", "ملغى", "slate", "ECEFF3"),
}
OPEN = ("on_track", "due_soon", "overdue")
AGE_BANDS = ((30, "0-30"), (60, "31-60"), (90, "61-90"), (10 ** 6, ">90"))


def label(key):
    e, a = STATUS[key][0], STATUS[key][1]
    return pick(e, a)


def days(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def status(a, asof):
    """Status of one action as at a date (ISO)."""
    if (a.get("status") or "").strip().lower() == "cancelled":
        return "cancelled"
    if a.get("completed") and a["completed"] <= asof:
        return "done_verified" if (a.get("evidence") or "").strip() else "done_pending"
    if not a.get("opened") or a["opened"] > asof:
        return "not_started"
    if a.get("due") and a["due"] < asof:
        return "overdue"
    if a.get("due") and days(asof, a["due"]) <= DUE_SOON:
        return "due_soon"
    return "on_track"


def age_band(a, asof):
    n = days(a["opened"], asof)
    return next(lab for lim, lab in AGE_BANDS if n <= lim)


# ------------------------------------------------------------------ published versions (history, staleness)
def versions(limit=24):
    """Published F6 versions, oldest first: [(upload_id, published_at)]. Rolled-back versions stay in the history."""
    rows = db.q("SELECT id, published_at FROM uploads WHERE kind='F6' AND published_at != '' ORDER BY published_at DESC, id DESC "
                "LIMIT ?", (limit,))
    return [(r["id"], r["published_at"]) for r in reversed(rows)]


def meta():
    """{'published': 'YYYY-MM-DD HH:MM:SS', 'age_days': n, 'stale': bool} of the current F6 register, or {}."""
    uid = store.current_ids().get("F6")
    if not uid:
        return {}
    row = db.q1("SELECT published_at FROM uploads WHERE id=?", (uid,))
    pub = (row["published_at"] if row else "") or ""
    if not pub:
        return {}
    age = (dt.date.today() - dt.date.fromisoformat(pub[:10])).days
    return {"published": pub[:16], "age_days": age, "stale": age > STALE}


def history():
    """{action_id: [(date, status_key)]} across published versions, each status as at that version's publish date,
    keeping only the points where the status changed."""
    out = {}
    for uid, pub in versions():
        d = store.load(uid)
        if not d:
            continue
        for a in d["actions"]:
            st = status(a, pub[:10])
            h = out.setdefault(a["id"], [])
            if not h or h[-1][1] != st:
                h.append((pub[:10], st))
    return out


def previous_statuses(current_uid):
    """Statuses in the version published before the current one: {action_id: status_key} (None if there is none)."""
    vs = [v for v in versions() if v[0] != current_uid]
    if not vs:
        return None
    uid, pub = vs[-1]
    d = store.load(uid)
    return {a["id"]: status(a, pub[:10]) for a in (d or {}).get("actions", [])}


# ------------------------------------------------------------------ tracker rows
def rows(f6, asof, tpa="", target="", st="", atype="", prev=None):
    decisions = {d["id"]: d for d in f6["decisions"]}
    out = []
    for a in f6["actions"]:
        if a.get("opened") and a["opened"] > asof:
            continue                                   # opened after the as-at date: not yet in the tracker
        if tpa and a["tpa"] != tpa:
            continue
        if target and a["target_type"] != target:
            continue
        if atype and a["type"] != atype:
            continue
        s = status(a, asof)
        if st == "open" and s not in OPEN:
            continue
        if st and st != "open" and s != st:
            continue
        dec = decisions.get(a["decision_id"]) or {}
        over = days(a["due"], asof) if s == "overdue" else None
        to_due = days(asof, a["due"]) if s in ("on_track", "due_soon") and a.get("due") else None
        changed = None
        if prev is not None:
            if a["id"] not in prev:
                changed = "new"
            elif prev[a["id"]] != s:
                changed = prev[a["id"]]
        out.append(dict(a, st=s, decision=dec, days_over=over, days_to_due=to_due, changed=changed,
                        age=age_band(a, asof) if s in OPEN else ""))
    order = {k: i for i, k in enumerate(STATUS)}
    out.sort(key=lambda r: (order[r["st"]], -(r["days_over"] or 0), r.get("due") or "9999", r["id"]))
    return out


def summary(rs):
    counts = {k: 0 for k in STATUS}
    ages = {lab: 0 for _, lab in AGE_BANDS}
    for r in rs:
        counts[r["st"]] += 1
        if r["age"]:
            ages[r["age"]] += 1
    return counts, ages


def target_name(r):
    if r["target"]:
        return r["target"]
    return pick("Provider (not named)", "مقدم خدمة (غير مسمى)")


# ------------------------------------------------------------------ Excel download
HEAD = [("Status", "الحالة"), ("Action ID", "رقم الإجراء"), ("Target type", "نوع الجهة"), ("Target", "الجهة"), ("TPA", "الشركة"),
        ("Action type", "نوع الإجراء"), ("Decision ID", "رقم القرار"), ("Decision", "القرار"), ("Decision date", "تاريخ القرار"),
        ("Minutes reference", "مرجع المحضر"), ("Flag code", "رمز الملاحظة"), ("Opened", "تاريخ الفتح"), ("Due", "تاريخ الاستحقاق"),
        ("Completed", "تاريخ الإنجاز"), ("Days overdue", "أيام التأخير"), ("Action owner (unit)", "الجهة المسؤولة"),
        ("Recovery agreed (SAR)", "الاسترداد المتفق عليه"), ("Recovered (SAR)", "المسترد"), ("Evidence reference", "مرجع الدليل"),
        ("Last update", "آخر تحديث"), ("Status note", "ملاحظة الحالة"), ("Change since last upload", "التغير منذ آخر تحميل")]


def to_xlsx(rs, asof, filters, published, by):
    wb = Workbook()
    ws = wb.active
    ws.title = "Action tracker"
    ws.sheet_view.rightToLeft = lang() == "ar"
    ws["A1"] = pick("Corrective-action tracker - CNHI audit project", "متابعة الإجراءات التصحيحية - مشروع تدقيق المركز")
    ws["A1"].font = Font(size=14, bold=True, color="0B6E70")
    ws["A2"] = pick(f"Status as at {asof} · register uploaded {published} · filters: {filters or 'none'}",
                    f"الحالة حتى {asof} · آخر تحميل للسجل {published} · التصفية: {filters or 'لا يوجد'}")
    ws["A3"] = pick(f"Exported {dt.datetime.now():%Y-%m-%d %H:%M} by {by}. Status is calculated from the dates. Provider names follow "
                    "decision D-23 (approved decisions only; referrals for investigation are never named).",
                    f"صدر في {dt.datetime.now():%Y-%m-%d %H:%M} بواسطة {by}. الحالة محسوبة من التواريخ. أسماء مقدمي الخدمة وفق القرار D-23.")
    for c in ("A2", "A3"):
        ws[c].font = Font(size=9, italic=True)
    for j, (en, ar) in enumerate(HEAD, start=1):
        ws.cell(row=5, column=j, value=en).font = Font(bold=True, color="FFFFFF")
        ws.cell(row=5, column=j).fill = PatternFill("solid", fgColor="0B6E70")
        ws.cell(row=6, column=j, value=ar).font = Font(bold=True, color="0B6E70")
        ws.column_dimensions[get_column_letter(j)].width = 14
    for col, w in (("A", 26), ("D", 28), ("F", 24), ("U", 50), ("V", 22)):
        ws.column_dimensions[col].width = w
    for i, r in enumerate(rs, start=7):
        d = r["decision"]
        ch = "" if r["changed"] is None else pick("New", "جديد") if r["changed"] == "new" else pick(f"was {STATUS[r['changed']][0]}", f"كان {STATUS[r['changed']][1]}")
        from .kpi import gl
        vals = [label(r["st"]), r["id"], gl(r["target_type"]), target_name(r), r["tpa"], gl(r["type"]), r["decision_id"],
                gl(d.get("decision", ""), True), d.get("decided"), d.get("minutes", ""), r["code"], r["opened"], r["due"], r["completed"],
                r["days_over"], r.get("owner", ""), r["agreed"], r["recovered"], r.get("evidence", ""), r.get("updated"),
                r.get("note", ""), ch]
        for j, v in enumerate(vals, start=1):
            if isinstance(v, str) and len(v) == 10 and v[4] == "-" and v[7] == "-":
                v = dt.date.fromisoformat(v)
            c = ws.cell(row=i, column=j, value=v)
            if isinstance(v, dt.date):
                c.number_format = "dd-mmm-yyyy"
            if j in (17, 18):
                c.number_format = "#,##0"
            if j == 21:
                c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=i, column=1).fill = PatternFill("solid", fgColor=STATUS[r["st"]][3])
    ws.freeze_panes = "C7"
    if rs:
        ws.auto_filter.ref = f"A6:{get_column_letter(len(HEAD))}{6 + len(rs)}"
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()
