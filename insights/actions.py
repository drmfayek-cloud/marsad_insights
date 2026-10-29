"""Corrective actions, built automatically from the registers the team already keeps (decision of 29 Oct 2026):

  Daily register (F1)   confirmed flags of the Daily Log, grouped by target (the TPA, or the provider when the action
                        level is aimed at a provider), flag family and month logged. Each flag already carries its owner,
                        due date, status, date closed, sharing with the TPA and escalation to CNHI.
  GSS workbook (F2)     flagged claims of each GSS report (flag owner, due date, flag status, closed date).
  Disputes tracker (F3) hospital disputes with a fraud, waste or abuse indicator, per hospital and indicator, closed by
                        CNHI's final decision.

Nothing is typed into a separate register and nothing is downloaded and uploaded again. Status is calculated from the
dates (rules below, thresholds in config/settings.yaml), and recorded at every register upload so the dashboard can show
history and changes since the last upload.

  Completed - verified           every item closed, with evidence (Daily Log 'Evidence reference'; GSS closure and CNHI
                                 decisions are evidence in themselves)
  Completed - evidence pending   every item closed, some without an evidence reference
  Overdue                        an open item is past its due date
  Due soon                       the earliest open due date is within 7 days
  On track                       open, due later (or no due date recorded)
  Not started                    no item logged yet
Provider names follow D-23: a provider is named only once CNHI has endorsed or decided the case; investigation referrals
(disputes with a 'Suspected' indicator) are never named.
"""
import datetime as dt
import hashlib
import io
from collections import Counter, defaultdict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import config, db, store
from .i18n import lang, pick

CA = config.SETTINGS.get("corrective_actions") or {}
DUE_SOON = int(CA.get("due_soon_days", 7))
STALE = int(CA.get("stale_days", 7))
CLOSED = {str(x).strip().lower() for x in CA.get("closed_statuses", ["Closed", "Resolved", "Recovered", "Completed"])}
PROV_WORDS = [str(x).lower() for x in CA.get("provider_keywords", ["provider", "hospital"])]
P_TOP, P_MIN_N, P_MIN_SAR = int(CA.get("provider_top_per_month", 10)), int(CA.get("provider_min_flags", 3)), \
    float(CA.get("provider_min_sar", 100000))

STATUS = {   # key -> (English, Arabic, tone, Excel fill)
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
SOURCES = {"F1": ("Daily review flags", "ملاحظات المراجعة اليومية"), "F2": ("GSS claim flags", "ملاحظات مطالبات GSS"),
           "F3": ("Dispute indicator review", "مراجعة مؤشرات الاعتراضات")}


def label(key):
    return pick(STATUS[key][0], STATUS[key][1])


def days(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def short(text, n=4):
    t = "".join(ch for ch in (text or "") if ch.isalnum()).upper()
    return (t[:n] or "X") + hashlib.sha1((text or "").encode()).hexdigest()[:2].upper()


# ------------------------------------------------------------------ status of one action as at a date
def status(a, asof):
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


def _group(items, asof):
    """Dates of a group of items: opened = first item; due = earliest due of the items still open at the as-at date;
    completed = last closure when every item is closed by then."""
    live = [i for i in items if i["opened"] and i["opened"] <= asof]
    if not live:
        return None, None, None, 0, 0, 0
    opened = min(i["opened"] for i in live)
    open_ = [i for i in live if not (i["closed"] and i["closed"] <= asof)]
    due = min((i["due"] for i in open_ if i["due"]), default=None)
    overdue = sum(1 for i in open_ if i["due"] and i["due"] < asof)
    completed = None if open_ else max(i["closed"] for i in live)
    return opened, due, completed, len(live), len(open_), overdue


# ------------------------------------------------------------------ derive the actions from the registers
_cache, _keep = {}, {}


def derive(data, asof=None):
    """List of corrective actions (dicts) built from F1, F2 and F3 as at a date (default today)."""
    asof = asof or dt.date.today().isoformat()
    key = (id(data.get("F1")), id(data.get("F2")), id(data.get("F3")), asof)
    if key in _cache:
        return _cache[key]
    out = []
    out += _from_f1(data.get("F1"), asof)
    out += _from_f2(data.get("F2"), asof)
    out += _from_f3(data.get("F3"), asof)
    if len(_cache) > 12:
        _cache.clear()
        _keep.clear()
    _cache[key] = out
    _keep[key] = (data.get("F1"), data.get("F2"), data.get("F3"))   # keeps the objects alive so their ids stay unique
    return out


def _finish(a, items, asof, evidence_ok):
    a["opened"], a["due"], a["completed"], a["total"], a["open_items"], a["overdue_items"] = _group(items, asof)
    a["evidence"] = ("Recorded in the register" if evidence_ok else "") if a["completed"] else ""
    a["status"] = ""
    return a


def _from_f1(f1, asof):
    if not f1:
        return []
    from . import deid
    from .parsers import norm
    groups = defaultdict(list)
    for f in f1["flags"]:
        if f["status"] != "Confirmed" or not f["date"]:
            continue
        lvl = (f.get("action") or "").lower()
        prov = any(w in lvl for w in PROV_WORDS) and f.get("provider")
        tkey = ("P", deid.ref(norm(f["provider"]))) if prov else ("T", f["tpa"] or "")
        if not tkey[1]:
            continue
        groups[(tkey, f["family"], f["date"][:7])].append(f)
    has_ev = (f1.get("has") or {}).get("evidence")
    prov_keep = defaultdict(list)
    out = []
    for (tkey, fam, month), fl in groups.items():
        refs = {}
        for f in fl:
            k = f["ref"] or f["log_id"]
            refs[k] = max(refs.get(k, 0), f["amount"] or 0)
        value = sum(refs.values())
        items = [dict(opened=f["date"], due=f.get("due"),
                      closed=f.get("closed") or (f["date"] if (f.get("state") or "").strip().lower() in CLOSED else None))
                 for f in fl]
        endorsed = any((f.get("cnhi_response") or "").lower().startswith("endorse") for f in fl)
        sent = min((f["sent_cnhi"] for f in fl if f.get("sent_cnhi")), default=None)
        responses = Counter(f["cnhi_response"] for f in fl if f.get("cnhi_response"))
        tpa = Counter(f["tpa"] for f in fl if f["tpa"]).most_common(1)
        rec = [f.get("recovered") for f in fl if f.get("recovered") is not None]
        a = dict(source="F1", family=fam, code=fam, month=month, value=value, recovered=sum(rec) if rec else None,
                 tpa=tpa[0][0] if tpa else "", owner=Counter(f.get("owner_type") or "" for f in fl).most_common(1)[0][0],
                 shared=min((f["shared_tpa"] for f in fl if f.get("shared_tpa")), default=None),
                 decision=dict(submitted=sent, decision=", ".join(f"{k} ({n})" for k, n in responses.most_common(3)),
                               decided=None, minutes=""),
                 decision_id="", flags=len(fl), encounters=len(refs))
        if tkey[0] == "T":
            a.update(id=f"DR-{month.replace('-', '')}-{fam}-{short(tkey[1])}", target_type="TPA", target=tkey[1], key="")
        else:
            prov_name = fl[0]["provider"]
            a.update(id=f"DR-{month.replace('-', '')}-{fam}-P{tkey[1][:5].upper()}", target_type="Provider",
                     target=prov_name if endorsed else "", key=tkey[1])
        a["type"] = fam
        a["updated"] = max([x for f in fl for x in (f.get("closed"), f.get("shared_tpa"), f.get("sent_cnhi"), f["date"]) if x])
        a = _finish(a, items, asof, has_ev and all((f.get("evidence") or "").strip() for f in fl))
        if a["target_type"] == "Provider":
            prov_keep[month].append(a)
        else:
            out.append(a)
    for month, acts in prov_keep.items():           # materiality for provider actions (escalated ones always kept)
        acts.sort(key=lambda x: -x["value"])
        kept = 0
        for a in acts:
            big = a["flags"] >= P_MIN_N or a["value"] >= P_MIN_SAR
            if a["decision"]["submitted"] or (big and kept < P_TOP):
                out.append(a)
                kept += 0 if a["decision"]["submitted"] else 1
    return out


def _from_f2(f2, asof):
    if not f2:
        return []
    gss = {g["gss_id"]: g for g in f2["gss"]}
    groups = defaultdict(list)
    for s in f2["sample"]:
        if (s.get("flag") or "").lower() == "yes":
            groups[s["gss_id"]].append(s)
    out = []
    for gid, ss in groups.items():
        g = gss.get(gid, {})
        items = [dict(opened=s.get("review_date") or g.get("issued"), due=s.get("due"),
                      closed=(s.get("closed") or s.get("review_date")) if (s.get("flag_status") or "") == "Closed" else None)
                 for s in ss]
        a = dict(source="F2", id=f"GSS-{gid}", family="", code="", month=(g.get("issued") or "")[:7], target_type="TPA",
                 target=g.get("tpa") or "", tpa=g.get("tpa") or "", key="", type="GSS claim flags",
                 value=sum(s.get("at_issue") or 0 for s in ss), recovered=None,
                 owner=Counter(s.get("owner") or "" for s in ss).most_common(1)[0][0], shared=None,
                 decision=dict(submitted=None, decision=g.get("opinion", ""), decided=g.get("issued"), minutes=gid),
                 decision_id="", flags=len(ss), encounters=len(ss),
                 updated=max([x for s in ss for x in (s.get("closed"), s.get("review_date")) if x], default=None))
        a = _finish(a, items, asof, True)
        out.append(a)
    return out


def _from_f3(f3, asof):
    if not f3:
        return []
    from . import deid
    from .parsers import norm
    groups = defaultdict(list)
    for d in f3["disputes"]:
        if d.get("fwa") not in (None, "", "None") and d.get("hospital"):
            groups[(d["hospital"], d["fwa"])].append(d)
    out = []
    for (hosp, fwa), ds in groups.items():
        items = [dict(opened=d.get("closed") or d.get("received"), due=None,
                      closed=(d.get("cnhi_date") or d.get("closed")) if d.get("cnhi") else None) for d in ds]
        referral = fwa.lower().startswith("suspected")
        decided = all(d.get("cnhi") for d in ds)
        k = deid.ref(norm(hosp))
        a = dict(source="F3", id=f"HD-P{k[:5].upper()}-{short(fwa, 3)}", family="", code="", month="",
                 target_type="Provider", target=hosp if (decided and not referral) else "", tpa="", key=k,
                 type=("Referral for investigation" if referral else "Dispute indicator review") + f": {fwa}",
                 value=sum((d.get("value") if d.get("value") is not None else d.get("claimed")) or 0 for d in ds), recovered=None,
                 owner="CNHI", shared=None,
                 decision=dict(submitted=min((d["closed"] for d in ds if d.get("closed")), default=None),
                               decision=", ".join(sorted({d["cnhi"] for d in ds if d.get("cnhi")})), decided=None, minutes=""),
                 decision_id="", flags=len(ds), encounters=len(ds), referral=referral,
                 updated=max([x for d in ds for x in (d.get("cnhi_date"), d.get("closed")) if x], default=None))
        a = _finish(a, items, asof, True)
        out.append(a)
    return out


def note_text(a):
    """Automatic status note from the register counts, in the page language (no free text is read)."""
    if not a["total"]:
        return ""
    unit = {"F1": ("flags", "ملاحظة"), "F2": ("flagged claims", "مطالبة عليها ملاحظة"), "F3": ("disputes", "اعتراض")}[a["source"]]
    closed = a["total"] - a["open_items"]
    en = f"{a['total']} {unit[0]}: {closed} closed, {a['open_items']} open" + (f" ({a['overdue_items']} past due)" if a["overdue_items"] else "")
    ar = f"{a['total']} {unit[1]}: {closed} مغلقة، {a['open_items']} مفتوحة" + (f" ({a['overdue_items']} متأخرة)" if a["overdue_items"] else "")
    return pick(en, ar)


# ------------------------------------------------------------------ status log (history, changes), staleness
def record(batch, data, at=None):
    """Writes the status of every action after a register is published; only changes are stored."""
    at = at or db.now()
    last = {r["action_id"]: r["status"] for r in db.q(
        "SELECT action_id, status FROM action_log l WHERE action_id != '__upload__' AND "
        "batch = (SELECT MAX(batch) FROM action_log m WHERE m.action_id=l.action_id)")}
    db.ex("INSERT INTO action_log(batch, at, action_id, status) VALUES(?,?,'__upload__','')", (batch, at))   # marks the upload
    n = 0
    for a in derive(data, at[:10]):
        st = status(a, at[:10])
        if last.get(a["id"]) != st:
            db.ex("INSERT INTO action_log(batch, at, action_id, status) VALUES(?,?,?,?)", (batch, at, a["id"], st))
            n += 1
    return n


def changes():
    """{action_id: previous status key, or 'new'} for the actions whose status changed at the latest recorded upload."""
    b = db.val("SELECT MAX(batch) FROM action_log", default=None)
    if b is None or db.val("SELECT COUNT(DISTINCT batch) FROM action_log", default=0) < 2:
        return None
    out = {}
    for r in db.q("SELECT action_id FROM action_log WHERE batch=? AND action_id != '__upload__'", (b,)):
        prev = db.q1("SELECT status FROM action_log WHERE action_id=? AND batch<? ORDER BY batch DESC LIMIT 1", (r["action_id"], b))
        out[r["action_id"]] = prev["status"] if prev else "new"
    return out


def history(action_id):
    return [(r["at"][:10], r["status"]) for r in db.q("SELECT at, status FROM action_log WHERE action_id=? ORDER BY batch", (action_id,))]


def meta():
    """Age of the daily register, which feeds most actions: {'published', 'age_days', 'stale'} or {}."""
    uid = store.current_ids().get("F1")
    row = db.q1("SELECT published_at FROM uploads WHERE id=?", (uid,)) if uid else None
    pub = (row["published_at"] if row else "") or ""
    if not pub:
        return {}
    age = (dt.date.today() - dt.date.fromisoformat(pub[:10])).days
    return {"published": pub[:16], "age_days": age, "stale": age > STALE}


# ------------------------------------------------------------------ tracker rows
def rows(acts, asof, tpa="", target="", st="", atype="", src="", prev=None):
    out = []
    for a in acts:
        if not a.get("opened") or a["opened"] > asof:
            continue
        if tpa and a["tpa"] != tpa:
            continue
        if target and a["target_type"] != target:
            continue
        if atype and a["type"] != atype:
            continue
        if src and a["source"] != src:
            continue
        s = status(a, asof)
        if st == "open" and s not in OPEN:
            continue
        if st and st != "open" and s != st:
            continue
        over = days(a["due"], asof) if s == "overdue" else None
        to_due = days(asof, a["due"]) if s in ("on_track", "due_soon") and a.get("due") else None
        changed = None if prev is None else prev.get(a["id"])
        out.append(dict(a, st=s, days_over=over, days_to_due=to_due, changed=changed,
                        age=age_band(a, asof) if s in OPEN else ""))
    order = {k: i for i, k in enumerate(STATUS)}
    out.sort(key=lambda r: (order[r["st"]], -(r["days_over"] or 0), -(r["value"] or 0), r["id"]))
    return out


def age_band(a, asof):
    n = days(a["opened"], asof)
    return next(lab for lim, lab in AGE_BANDS if n <= lim)


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


def type_label(r):
    from .kpi import fam_name, gl
    if r["source"] == "F1":
        return fam_name(r["family"])
    if r["source"] == "F2":
        return pick("GSS claim flags", "ملاحظات مطالبات GSS")
    base, _, ind = r["type"].partition(": ")
    return f"{gl(base)}: {ind}" if ind else gl(base)


# ------------------------------------------------------------------ Excel download
HEAD = [("Status", "الحالة"), ("Action", "الإجراء"), ("Source", "المصدر"), ("Target type", "نوع الجهة"), ("Target", "الجهة"),
        ("TPA", "الشركة"), ("Issue", "الموضوع"), ("Month", "الشهر"), ("Items", "العدد"), ("Open", "المفتوح"),
        ("Past due", "المتأخر"), ("Opened", "تاريخ البدء"), ("Earliest open due date", "أقرب استحقاق مفتوح"),
        ("Completed", "تاريخ الإنجاز"), ("Days overdue", "أيام التأخير"), ("Owner", "الجهة المسؤولة"),
        ("Amount at risk (SAR)", "القيمة محل الملاحظة"), ("Recovered (SAR)", "المسترد"), ("Escalated to CNHI", "تصعيد للمركز"),
        ("CNHI response", "رد المركز"), ("Last update", "آخر تحديث"), ("Change since last upload", "التغير منذ آخر تحميل")]


def to_xlsx(rs, asof, filters, published, by):
    from .kpi import gl
    wb = Workbook()
    ws = wb.active
    ws.title = "Action tracker"
    ws.sheet_view.rightToLeft = lang() == "ar"
    ws["A1"] = pick("Corrective-action tracker - CNHI audit project", "متابعة الإجراءات التصحيحية - مشروع تدقيق المركز")
    ws["A1"].font = Font(size=14, bold=True, color="0B6E70")
    ws["A2"] = pick(f"Status as at {asof} · daily register uploaded {published} · filters: {filters or 'none'}",
                    f"الحالة حتى {asof} · آخر تحميل للسجل اليومي {published} · التصفية: {filters or 'لا يوجد'}")
    ws["A3"] = pick(f"Exported {dt.datetime.now():%Y-%m-%d %H:%M} by {by}. Built from the daily register, GSS workbook and disputes "
                    "tracker; status calculated from the dates. Provider names follow decision D-23.",
                    f"صدر في {dt.datetime.now():%Y-%m-%d %H:%M} بواسطة {by}. مبني من السجل اليومي ومصنف GSS وسجل الاعتراضات؛ الحالة محسوبة من التواريخ.")
    for c in ("A2", "A3"):
        ws[c].font = Font(size=9, italic=True)
    for j, (en, ar) in enumerate(HEAD, start=1):
        ws.cell(row=5, column=j, value=en).font = Font(bold=True, color="FFFFFF")
        ws.cell(row=5, column=j).fill = PatternFill("solid", fgColor="0B6E70")
        ws.cell(row=6, column=j, value=ar).font = Font(bold=True, color="0B6E70")
        ws.column_dimensions[get_column_letter(j)].width = 14
    for col, w in (("A", 26), ("B", 24), ("E", 26), ("G", 26), ("T", 26), ("V", 22)):
        ws.column_dimensions[col].width = w
    for i, r in enumerate(rs, start=7):
        d = r["decision"]
        ch = "" if r["changed"] is None else pick("New", "جديد") if r["changed"] == "new" else pick(f"was {STATUS[r['changed']][0]}", f"كان {STATUS[r['changed']][1]}")
        vals = [label(r["st"]), r["id"], pick(*SOURCES[r["source"]]), gl(r["target_type"]), target_name(r), r["tpa"], type_label(r),
                r["month"], r["total"], r["open_items"], r["overdue_items"], r["opened"], r["due"], r["completed"], r["days_over"],
                r["owner"], r["value"], r["recovered"], d.get("submitted"), d.get("decision", ""), r.get("updated"), ch]
        for j, v in enumerate(vals, start=1):
            if isinstance(v, str) and len(v) == 10 and v[4] == "-" and v[7] == "-":
                v = dt.date.fromisoformat(v)
            c = ws.cell(row=i, column=j, value=v)
            if isinstance(v, dt.date):
                c.number_format = "dd-mmm-yyyy"
            if j in (17, 18):
                c.number_format = "#,##0"
            if j == 20:
                c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=i, column=1).fill = PatternFill("solid", fgColor=STATUS[r["st"]][3])
    ws.freeze_panes = "C7"
    if rs:
        ws.auto_filter.ref = f"A6:{get_column_letter(len(HEAD))}{6 + len(rs)}"
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()
