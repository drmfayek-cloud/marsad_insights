"""The 55 KPIs. Each function takes the context and returns a result dict.

Rules applied throughout (see the Decisions sheet of the KPI dictionary):
  D-01 activity is dated by when the work happened (intake date, date logged, report issued, closure date);
  D-02 an encounter with several flags counts once; D-19 its amount counts once (highest amount);
  D-04 pre-authorization and claims values are never added together; D-09 a stage with no data reads
  'data capture in progress', never zero; D-17/D-20 the claims headline comes from the GSS sample.
"""
import calendar
import datetime as dt
import statistics
from collections import Counter, defaultdict

from markupsafe import Markup

from . import charts, config
from .i18n import lang, pick, t


# ------------------------------------------------------------------ context and helpers
class Ctx:
    def __init__(self, data, period="all", tpa="", internal=False, today=None):
        self.d = data
        self.period = period
        self.tpa = tpa
        self.internal = internal
        self.today = today or dt.date.today().isoformat()
        if period == "all":
            self.start, self.end = "0000-00-00", self.today
        else:
            y, m = int(period[:4]), int(period[5:7])
            self.start, self.end = f"{period}-01", f"{period}-{calendar.monthrange(y, m)[1]:02d}"

    def inp(self, d):
        return bool(d) and self.start <= d <= self.end

    def upto(self, d):
        return bool(d) and d <= self.end

    def tpa_ok(self, x):
        return not self.tpa or x.get("tpa") == self.tpa

    def get(self, kind):
        return self.d.get(kind)


def R(value=None, sub="", chart=None, table=None, state="ok", note="", raw=None):
    return dict(value=value, sub=sub, chart=chart, table=table, state=state, note=note, raw=raw)


def nodata(note):
    return R(value=None, state="nodata", note=note)


def num(v):
    return charts.fmt(v)


def sar(v):
    return "SAR " + charts.fmt(v, money=True) if v is not None else "-"


def pct(v):
    return charts.fmt(v, pct=True) if v is not None else "-"


def median(xs):
    return statistics.median(xs) if xs else None


def days(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def working_days(a, b):
    """Working days after date a up to and including date b (weekend from settings: Friday and Saturday)."""
    d0, d1 = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    n, step = 0, dt.timedelta(days=1)
    while d0 < d1:
        d0 += step
        if d0.weekday() not in config.WEEKEND:
            n += 1
    return n


def fam_name(code):
    f = config.FAMILIES.get(code)
    return pick(f["en"], f["ar"]) if f else code


def once_per_ref(flags):
    """D-19: amount at risk once per encounter (highest amount among its flags)."""
    m = {}
    for f in flags:
        k = f["ref"] or f["log_id"]
        m[k] = max(m.get(k, 0), f["amount"] or 0)
    return m


def table(headers, rows):
    return dict(headers=headers, rows=rows)


MISSING = {
    "F1": "Upload the daily MARSAD register.",
    "F2": "Upload the GSS Assurance Workbook.",
    "F3": "Upload the hospital disputes tracker.",
    "F4": "Upload the quarterly accounting report.",
    "F5": "Upload the governance register.",
}


# ------------------------------------------------------------------ F1 selections
def intake(c):
    return [x for x in c.get("F1")["intake"] if c.inp(x["date"]) and c.tpa_ok(x)]


def flags(c, confirmed=True, period=True):
    out = []
    for f in c.get("F1")["flags"]:
        if confirmed and f["status"] != "Confirmed":
            continue
        if period and not c.inp(f["date"]):
            continue
        if c.tpa_ok(f):
            out.append(f)
    return out


def is_approval(f):
    return not f["source"] or f["source"].lower().startswith("approv") or f["source"].lower().startswith("pre")


def is_claim(f):
    return f["source"].lower().startswith("claim")


def gss_by_id(c):
    return {g["gss_id"]: g for g in c.get("F2")["gss"]}


def gss_issued(c):
    return [g for g in c.get("F2")["gss"] if c.inp(g["issued"]) and c.tpa_ok(g)]


def sample_rows(c, period=True):
    gmap = gss_by_id(c)
    out = []
    for s in c.get("F2")["sample"]:
        g = gmap.get(s["gss_id"], {})
        if c.tpa and g.get("tpa") != c.tpa:
            continue
        if period and not c.inp(s["review_date"]):
            continue
        out.append(s)
    return out


def disputes(c):
    return [d for d in c.get("F3")["disputes"] if c.tpa_ok(d)]


# ------------------------------------------------------------------ Executive overview
def ex01(c):
    rows = intake(c)
    rev = sum(x["reviewed"] for x in rows)
    nd = len({x["date"] for x in rows})
    return R(num(rev), f"{num(rev / nd if nd else 0)} {t('per_day')}" if nd else "", raw=rev)


def ex02(c):
    rows = intake(c)
    rec, rev = sum(x["received"] for x in rows), sum(x["reviewed"] for x in rows)
    if not rec:
        return nodata("No encounters received in this period.")
    return R(pct(rev / rec), f"{num(rev)} {t('of')} {num(rec)}", raw=rev / rec)


def ex03(c):
    rev = sum(x["reviewed"] for x in intake(c))
    refs = {f["ref"] or f["log_id"] for f in flags(c)}
    if not rev:
        return nodata("No encounters reviewed in this period.")
    return R(pct(len(refs) / rev), f"{num(len(refs))} {pick('encounters with a confirmed flag', 'حالة عليها ملاحظة مؤكدة')}",
             raw=len(refs) / rev)


def ex04(c):
    m = once_per_ref([f for f in flags(c) if is_approval(f)])
    v = sum(m.values())
    return R(sar(v), f"{num(len(m))} {pick('encounters, counted once each', 'حالة، تحسب مرة واحدة')}", raw=v)


def ex05(c):
    if not c.get("F2"):
        return nodata(MISSING["F2"])
    gv = sum(s["at_issue"] for s in sample_rows(c))
    daily = sum(once_per_ref([f for f in flags(c) if is_claim(f)]).values()) if c.get("F1") else 0
    if daily:
        sub = pick(f"GSS pre-payment assurance {sar(gv)} · daily claims review {sar(daily)}",
                   f"ضمان GSS قبل الصرف {sar(gv)} · المراجعة اليومية للمطالبات {sar(daily)}")
    else:
        sub = pick("GSS pre-payment assurance · identified stage", "ضمان GSS قبل الصرف · مرحلة التحديد")
    return R(sar(gv + daily), sub, raw=gv + daily)


def ex06(c):
    if not c.get("F1")["has"].get("shared_tpa"):
        return nodata("Add the column 'Shared with TPA on' to the Daily Log.")
    fl = [f for f in flags(c, period=False) if f["action"] == "TPA level" and c.inp(f["shared_tpa"])]
    m = once_per_ref(fl)
    return R(num(len(m)), sar(sum(m.values())), raw=len(m))


def ex07(c):
    if not c.get("F3"):
        return nodata(MISSING["F3"])
    closed = [d for d in disputes(c) if c.inp(d["closed"])]
    tl = [x for x in c.get("F3")["time"] if c.inp(x["date"])]
    h, est = sum(x["hours"] for x in tl), sum(x["hours"] for x in tl if x["estimated"])
    sub = f"{num(h)} {t('hours')}" + (f" ({num(est)} {t('estimated')})" if est else "") if tl else ""
    return R(num(len(closed)), sub, raw=len(closed))


def ex08(c):
    if not c.get("F3"):
        return nodata(MISSING["F3"])
    closed = [d for d in disputes(c) if c.inp(d["closed"])]
    if not closed:
        return R("-", pick("No disputes closed in this period", "لا توجد اعتراضات مغلقة في هذه الفترة"))
    kept = sum(1 for d in closed if d["outcome"] == "Maintained")
    return R(pct(kept / len(closed)), f"{kept} {t('of')} {len(closed)}", raw=kept / len(closed))


def ex09(c):
    if not c.get("F2"):
        return nodata(MISSING["F2"])
    iss = [g for g in gss_issued(c) if g["opinion"] != "Review incomplete"]
    if not iss:
        return R("0", pick("No GSS report issued in this period", "لم يصدر تقرير GSS في هذه الفترة"), raw=0)
    uns = sum(1 for g in iss if g["opinion"] == "Unsatisfactory")
    return R(num(len(iss)), pick(f"{sar(sum(g['claimed'] for g in iss))} claimed · {pct(uns / len(iss))} unsatisfactory",
                                 f"{sar(sum(g['claimed'] for g in iss))} مطالب بها · {pct(uns / len(iss))} غير مرض"),
             raw=len(iss))


def ex10(c):
    if not c.get("F5"):
        return nodata(MISSING["F5"])
    due = [x for x in c.get("F5")["deliverables"] if c.inp(x["due"])]
    if not due:
        return R("-", pick("No deliverable due in this period", "لا توجد مخرجات مستحقة في هذه الفترة"))
    ok = sum(1 for x in due if x["submitted"] and x["submitted"] <= x["due"])
    return R(pct(ok / len(due)), f"{ok} {t('of')} {len(due)}", raw=ok / len(due))


# ------------------------------------------------------------------ MARSAD daily review
def dr01(c):
    rows = intake(c)
    by = defaultdict(float)
    monthly = c.period == "all"
    for x in rows:
        by[x["date"][:7] if monthly else x["date"]] += x["reviewed"]
    keys = sorted(by)
    labels = [k if monthly else k[8:] for k in keys]
    nd = len({x["date"] for x in rows})
    total = sum(by.values())
    tab = None
    if c.internal:
        rv = defaultdict(lambda: [0, 0])
        for x in c.get("F1")["review"]:
            if c.inp(x["date"]) and c.tpa_ok(x):
                rv[x["reviewer"]][0] += x["records"]
                rv[x["reviewer"]][1] += x["confirmed"]
        tab = table([pick("Reviewer (KPMG only)", "المراجع (داخلي)"), t("reviewed"), t("flags"), pick("Flag rate", "نسبة الملاحظات")],
                    [[k, num(a), num(b), pct(b / a if a else 0)] for k, (a, b) in sorted(rv.items())])
    return R(num(total / nd if nd else 0), pick("average per working day", "المتوسط لكل يوم عمل"),
             chart=charts.columns(labels, [(t("reviewed"), [by[k] for k in keys])], tones=["teal"]), table=tab, raw=total)


def dr02(c):
    rows = [x for x in c.get("F1")["intake"] if c.upto(x["date"]) and c.tpa_ok(x)]
    v = sum(x["received"] for x in rows) - sum(x["reviewed"] for x in rows)
    return R(num(max(0, v)), pick(f"at {c.end}", f"حتى {c.end}"), raw=v)


def dr03(c):
    return nodata("Needs received and reviewed timestamps for each encounter (the intake is recorded per day).")


def dr04(c):
    fl = flags(c)
    if not fl:
        return R("0", "", raw=0)
    by = defaultdict(list)
    for f in fl:
        by[f["family"]].append(f)
    rows = sorted(((k, len(v), sum(once_per_ref(v).values())) for k, v in by.items()), key=lambda r: -r[1])
    return R(num(len(fl)), pick(f"confirmed flags in {len(by)} families", f"ملاحظة مؤكدة في {len(by)} عائلات"),
             chart=charts.hbar([(fam_name(k), n) for k, n, _ in rows], rtl=lang() == "ar"),
             table=table([pick("Flag family", "عائلة الملاحظة"), t("count"), t("amount")],
                         [[fam_name(k), num(n), sar(v)] for k, n, v in rows]), raw=len(fl))


def dr05(c):
    if not c.get("F1")["has"].get("selection"):
        return nodata("Add the column 'Selection reason' to the Daily Log.")
    kw = config.SETTINGS.get("outlier_keyword", "outlier").lower()
    lim = config.SETTINGS.get("outlier_threshold_sar", 50000)
    fl = [f for f in flags(c, confirmed=False) if kw in f["selection"].lower() and (f["amount"] or 0) < lim]
    refs = {f["ref"] for f in fl}
    conf = {f["ref"] for f in fl if f["status"] == "Confirmed"}
    return R(num(len(refs)), pick(f"{len(conf)} with a confirmed flag", f"{len(conf)} عليها ملاحظة مؤكدة"), raw=len(refs))


def dr06(c):
    rev = sum(x["reviewed"] for x in intake(c))
    v = sum(once_per_ref([f for f in flags(c) if is_approval(f)]).values())
    sub = ""
    if c.get("F2"):
        s = sample_rows(c)
        if s:
            sub = pick(f"GSS claims: {sar(sum(x['at_issue'] for x in s) / len(s))} per sampled claim",
                       f"مطالبات GSS: {sar(sum(x['at_issue'] for x in s) / len(s))} لكل مطالبة في العينة")
    if not rev:
        return nodata("No encounters reviewed in this period.")
    return R(sar(v / rev), (pick("pre-authorization, per encounter", "الموافقات المسبقة، لكل حالة") + (" · " + sub if sub else "")),
             raw=v / rev)


def dr07(c):
    by = defaultdict(list)
    for f in flags(c):
        by[f["provider"] or "-"].append(f)
    vals = sorted(((p, sum(once_per_ref(v).values())) for p, v in by.items()), key=lambda r: -r[1])
    total = sum(v for _, v in vals)
    if not total:
        return R("-", "", raw=None)
    top = vals[:10]
    share = sum(v for _, v in top) / total
    return R(pct(share), pick(f"of value at issue sits with the top {len(top)} providers",
                              f"من القيمة لدى أعلى {len(top)} مقدمي خدمة"),
             chart=charts.hbar([(p, v) for p, v in top], money=True, rtl=lang() == "ar"), raw=share)


def dr08(c):
    if not c.get("F1")["has"].get("evidence"):
        return nodata("Add the column 'Evidence reference' to the Daily Log.")
    fl = flags(c)
    if not fl:
        return R("-", "")
    ok = sum(1 for f in fl if f["evidence"])
    return R(pct(ok / len(fl)), f"{ok} {t('of')} {len(fl)}", raw=ok / len(fl))


# ------------------------------------------------------------------ Hospital disputes
def _hd(c):
    return None if c.get("F3") else nodata(MISSING["F3"])


def hd01(c):
    if _hd(c):
        return _hd(c)
    ds = disputes(c)
    rec = [d for d in ds if c.inp(d["received"])]
    by_h = Counter(d["hospital"] or "-" for d in rec)
    by_t = Counter(d["type"] or "-" for d in rec)
    undated = sum(1 for d in ds if not d["received"])
    res = R(num(len(rec)), pick(f"{len(by_h)} hospitals", f"{len(by_h)} مستشفيات") if rec else "",
            chart=charts.hbar(by_h.most_common(), rtl=lang() == "ar"),
            table=table([pick("Dispute theme", "موضوع الاعتراض"), t("count")], [[k, num(n)] for k, n in by_t.most_common()]),
            raw=len(rec))
    if undated:
        res["state"], res["note"] = "partial", pick(f"{undated} dispute(s) have no received date yet: enter it on their batch in the tracker.",
                                               f"{undated} اعتراض بلا تاريخ استلام: أدخله على الدفعة في سجل الاعتراضات.")
    return res


def hd02(c):
    if _hd(c):
        return _hd(c)
    b1, b2, b3 = config.SETTINGS.get("dispute_age_bands", [5, 10, 20])
    open_ = [d for d in disputes(c) if c.upto(d["received"]) and d.get("position") in (None, "", "Pending")
             and not (d["closed"] and d["closed"] <= c.end)]
    bands = {f"0-{b1}": 0, f"{b1 + 1}-{b2}": 0, f"{b2 + 1}-{b3}": 0, f">{b3}": 0}
    for d in open_:
        a = days(d["received"], c.end)
        k = f"0-{b1}" if a <= b1 else f"{b1 + 1}-{b2}" if a <= b2 else f"{b2 + 1}-{b3}" if a <= b3 else f">{b3}"
        bands[k] += 1
    pend = sum(1 for d in disputes(c) if d.get("position") == "Pending")
    return R(num(len(open_)), pick(f"open at {c.end}", f"مفتوحة حتى {c.end}") + (pick(f" · {pend} pending review", f" · {pend} بانتظار المراجعة") if pend else ""),
             chart=charts.columns(list(bands), [(pick("Days since receipt", "أيام منذ الاستلام"), list(bands.values()))], tones=["amber"]),
             raw=len(open_))


def _missing_amounts(ds):
    n = sum(1 for d in ds if d["value"] is None and d.get("position") != "Pending")
    return pick(f"{n} of {len(ds)} disputes have no approved amount yet, so their value is not included.",
                f"{n} من {len(ds)} اعتراضا بلا مبلغ معتمد بعد، لذلك لم تدخل قيمتها.") if n else ""


def hd03(c):
    if _hd(c):
        return _hd(c)
    ds = [d for d in disputes(c) if c.inp(d["received"]) or (not d["received"] and c.inp(d["closed"]))]
    known = [d["value"] for d in ds if d["value"] is not None]
    v = sum(known)
    claimed = sum(d.get("claimed") or 0 for d in ds)
    res = R(sar(v) if known or not ds else "-", pick(f"claimed value of these claims {sar(claimed)}", f"القيمة المطالب بها لهذه المطالبات {sar(claimed)}") if claimed else "",
            raw=v)
    note = _missing_amounts(ds)
    if note:
        res["state"], res["note"] = "partial", note
    return res


def _kept(d):
    if d["maintained"] is not None:
        return d["maintained"]
    if d["value"] is None:
        return 0
    if d["outcome"] in ("Maintained", "Withdrawn by hospital"):
        return d["value"]
    return 0


def hd04(c):
    if _hd(c):
        return _hd(c)
    closed = [d for d in disputes(c) if c.inp(d["closed"])]
    by = defaultdict(lambda: [0, 0.0])
    for d in closed:
        by[d["outcome"] or "-"][0] += 1
        by[d["outcome"] or "-"][1] += d["value"] or 0
    order = ["Maintained", "Partially maintained", "Reversed", "Withdrawn by hospital"]
    keys = [k for k in order if k in by] + [k for k in by if k not in order]
    fwa = sum(1 for d in closed if d.get("fwa") not in (None, "", "None"))
    return R(num(len(closed)), pick(f"KPMG opinions issued · {fwa} with an FWA indicator", f"آراء صادرة · {fwa} عليها مؤشر احتيال أو هدر"),
             chart=charts.donut([(k, by[k][0]) for k in keys]),
             table=table([pick("Outcome", "النتيجة"), t("count"), pick("Amount disputed", "المبلغ محل الاعتراض")],
                         [[k, num(by[k][0]), sar(by[k][1]) if any(d["value"] is not None for d in closed if (d["outcome"] or "-") == k) else "-"]
                          for k in keys]), raw=len(closed))


def hd05(c):
    if _hd(c):
        return _hd(c)
    closed = [d for d in disputes(c) if c.inp(d["closed"])]
    v, disputed = sum(_kept(d) for d in closed), sum(d["value"] or 0 for d in closed)
    known = any(d["value"] is not None or d["maintained"] is not None for d in closed)
    res = R(sar(v) if known or not closed else "-", f"{pct(v / disputed)} {t('of')} {sar(disputed)}" if disputed else "", raw=v)
    note = _missing_amounts(closed)
    if note:
        res["state"], res["note"] = "partial", note
    return res


def hd06(c):
    if _hd(c):
        return _hd(c)
    xs = [working_days(d["received"], d["response"]) for d in disputes(c) if c.inp(d["response"]) and d["received"]]
    m = median(xs)
    if not xs and any(c.inp(d["response"]) for d in disputes(c)):
        return nodata(pick("Needs the received date of the disputes answered in this period: enter it on their batch in the tracker.",
                           "يتطلب تاريخ استلام الاعتراضات التي تم الرد عليها في هذه الفترة: أدخله على الدفعة في السجل."))
    return R(num(m) if m is not None else "-", pick(f"working days, median of {len(xs)}", f"أيام عمل، الوسيط من {len(xs)}"),
             raw=m)


def hd07(c):
    if _hd(c):
        return _hd(c)
    tl = [x for x in c.get("F3")["time"] if c.inp(x["date"])]
    if not tl:
        return nodata(pick("No hours logged for this period in the tracker's Actions sheet.",
                           "لم تسجل ساعات لهذه الفترة في ورقة الإجراءات في سجل الاعتراضات."))
    h, est = sum(x["hours"] for x in tl), sum(x["hours"] for x in tl if x["estimated"])
    by = defaultdict(float)
    for x in tl:
        by[x["activity"] or "-"] += x["hours"]
    return R(f"{num(h)} {t('hours')}", (f"{num(est)} {t('estimated')}" if est else ""),
             chart=charts.hbar(sorted(by.items(), key=lambda r: -r[1]), rtl=lang() == "ar"), raw=h)


# ------------------------------------------------------------------ GSS assurance
def _gs(c):
    return None if c.get("F2") else nodata(MISSING["F2"])


def gs01(c):
    if _gs(c):
        return _gs(c)
    iss = [g for g in gss_issued(c) if g["opinion"] != "Review incomplete"]
    by = defaultdict(lambda: [0, 0.0])
    for g in iss:
        by[g["opinion"]][0] += 1
        by[g["opinion"]][1] += g["claimed"]
    order = ["Satisfactory", "Satisfactory with exceptions", "Unsatisfactory"]
    keys = [k for k in order if k in by] + [k for k in by if k not in order]
    return R(num(len(iss)), pick("reports issued", "تقارير صادرة"), chart=charts.donut([(k, by[k][0]) for k in keys]),
             table=table([pick("Opinion", "الرأي"), t("count"), pick("Claimed (SAR)", "المطالب به (ريال)")],
                         [[k, num(by[k][0]), sar(by[k][1])] for k in keys]), raw=len(iss))


def gs02(c):
    if _gs(c):
        return _gs(c)
    f2 = c.get("F2")
    regd = {g["gss_id"] for g in f2["gss"]}
    stages = defaultdict(lambda: [0, 0.0])
    for q in f2["queue"]:
        if q["gss_id"] not in regd and c.tpa_ok(q):
            stages["Not registered"][0] += 1
            stages["Not registered"][1] += q["claimed"]
    for g in f2["gss"]:
        if not g["issued"] and g["status"] in ("Not started", "Sampling", "Under review") and c.tpa_ok(g):
            stages[g["status"]][0] += 1
            stages[g["status"]][1] += g["claimed"]
    n, v = sum(x[0] for x in stages.values()), sum(x[1] for x in stages.values())
    keys = [k for k in ("Not registered", "Not started", "Sampling", "Under review") if k in stages]
    return R(num(n), f"{sar(v)} · {pick('as of last upload', 'حتى آخر تحميل')}",
             chart=charts.hbar([(k, stages[k][0]) for k in keys], rtl=lang() == "ar"), raw=n)


def gs03(c):
    if _gs(c):
        return _gs(c)
    iss = gss_issued(c)
    cl, sc = sum(g["claims"] for g in iss), sum(g["sampled"] for g in iss)
    cv, sv = sum(g["claimed"] for g in iss), sum(g["sample_value"] for g in iss)
    if not cl:
        return R("-", pick("No GSS report issued in this period", "لم يصدر تقرير GSS في هذه الفترة"))
    return R(pct(sv / cv if cv else 0), pick(f"of claimed value · {pct(sc / cl)} of claims", f"من القيمة · {pct(sc / cl)} من المطالبات"),
             raw=sv / cv if cv else None)


def gs04(c):
    if _gs(c):
        return _gs(c)
    iss = gss_issued(c)
    rv, fl = sum(g["reviewed"] for g in iss), sum(g["flagged"] for g in iss)
    if not rv:
        return R("-", pick("No GSS report issued in this period", "لم يصدر تقرير GSS في هذه الفترة"))
    return R(pct(fl / rv), f"{num(fl)} {t('of')} {num(rv)}", raw=fl / rv)


def gs05(c):
    if _gs(c):
        return _gs(c)
    s = [x for x in sample_rows(c) if x["at_issue"]]
    by_o, by_c = defaultdict(float), defaultdict(float)
    for x in s:
        by_o[x["outcome"] or "-"] += x["at_issue"]
        by_c[x["category"] or "-"] += x["at_issue"]
    v = sum(x["at_issue"] for x in s)
    return R(sar(v), pick(f"{len(s)} sampled claims", f"{len(s)} مطالبة في العينة"),
             chart=charts.donut(sorted(by_o.items(), key=lambda r: -r[1]), money=True),
             table=table([pick("Finding category", "فئة الملاحظة"), t("amount")],
                         [[k, sar(val)] for k, val in sorted(by_c.items(), key=lambda r: -r[1])]), raw=v)


def gs06(c):
    if _gs(c):
        return _gs(c)
    iss = gss_issued(c)
    crit = set(config.SETTINGS.get("gss_critical", ["K1", "K2", "K3", "K4"]))
    fails, parts = Counter(), Counter()
    for g in iss:
        for k, v in g["k"].items():
            if v == "Fail":
                fails[k] += 1
            elif v == "Partial":
                parts[k] += 1
    cf = sum(n for k, n in fails.items() if k in crit)
    keys = [f"K{i}" for i in range(1, 13)]
    return R(num(sum(fails.values()) + sum(parts.values())),
             pick(f"{sum(fails.values())} fail, {sum(parts.values())} partial · {cf} critical fail",
                  f"{sum(fails.values())} إخفاق، {sum(parts.values())} جزئي · {cf} إخفاق حرج"),
             chart=charts.columns(keys, [(pick("Fail", "إخفاق"), [fails[k] for k in keys]),
                                         (pick("Partial", "جزئي"), [parts[k] for k in keys])], tones=["coral", "amber"]),
             raw=sum(fails.values()) + sum(parts.values()))


def gs07(c):
    if _gs(c):
        return _gs(c)
    # same rule as the GSS workbook: a flagged claim is open until its flag status reads Closed (blank = not started)
    s = [x for x in sample_rows(c, period=False) if x["flag"].lower() == "yes" and x["flag_status"] != "Closed"]
    od = [x for x in s if x["due"] and x["due"] < c.today]
    by = defaultdict(lambda: [0, 0])
    for x in s:
        by[x["owner"] or pick("Not assigned", "غير محدد")][0] += 1
        if x in od:
            by[x["owner"] or pick("Not assigned", "غير محدد")][1] += 1
    return R(num(len(s)), pick(f"{len(od)} past due · as of last upload", f"{len(od)} متأخرة · حتى آخر تحميل"),
             table=table([pick("Flag owner", "الجهة المسؤولة"), pick("Open", "مفتوحة"), pick("Past due", "متأخرة")],
                         [[k, num(a), num(b)] for k, (a, b) in sorted(by.items(), key=lambda r: -r[1][0])]), raw=len(s))


def gs08(c):
    if _gs(c):
        return _gs(c)
    xs = [days(g["start"], g["issued"]) for g in gss_issued(c) if g["start"]]
    m = median(xs)
    if not xs and any(c.inp(d["response"]) for d in disputes(c)):
        return nodata(pick("Needs the received date of the disputes answered in this period: enter it on their batch in the tracker.",
                           "يتطلب تاريخ استلام الاعتراضات التي تم الرد عليها في هذه الفترة: أدخله على الدفعة في السجل."))
    return R(num(m) if m is not None else "-", pick(f"days, median of {len(xs)}", f"يوم، الوسيط من {len(xs)}"), raw=m)


# ------------------------------------------------------------------ Financial review (quarterly)
def _fr(c):
    return None if c.get("F4") else nodata(MISSING["F4"])


def qlabel(c):
    return f"{t('quarter')} {c.get('F4')['quarter']}" + (f" · {t('not_split')}" if c.tpa else "")


def fr01(c):
    if _fr(c):
        return _fr(c)
    po = c.get("F4")["po"]
    by = {r: [sum(p["claimed"] for p in po if p["referral"] == r), sum(p["approved"] for p in po if p["referral"] == r)]
          for r in ("inside", "outside")}
    cl, ap = sum(v[0] for v in by.values()), sum(v[1] for v in by.values())
    labels = [pick("Inside the Kingdom", "داخل المملكة"), pick("Outside the Kingdom", "خارج المملكة")]
    return R(sar(ap), f"{pick('approved of', 'معتمد من')} {sar(cl)} · {qlabel(c)}",
             chart=charts.columns(labels, [(pick("Claimed", "المطالب به"), [by["inside"][0], by["outside"][0]]),
                                           (pick("Approved", "المعتمد"), [by["inside"][1], by["outside"][1]])], money=True),
             raw=ap)


def fr02(c):
    if _fr(c):
        return _fr(c)
    po = c.get("F4")["po"]
    cl, ap = sum(p["claimed"] for p in po), sum(p["approved"] for p in po)
    return R(sar(cl - ap), f"{pct((cl - ap) / cl if cl else 0)} {pick('of claimed', 'من المطالب به')} · {qlabel(c)}", raw=cl - ap)


def fr03(c):
    if _fr(c):
        return _fr(c)
    v = c.get("F4")["carried"].get("duplicates")
    if v is None:
        return nodata("Duplicate-payment deductions line not found in the carried-forward tracking sheet.")
    return R(sar(v), qlabel(c), raw=v)


def fr04(c):
    if _fr(c):
        return _fr(c)
    po = c.get("F4")["po"]
    rows = []
    for r, lab in (("inside", pick("Inside the Kingdom", "داخل المملكة")), ("outside", pick("Outside the Kingdom", "خارج المملكة"))):
        ap = sum(p["approved"] for p in po if p["referral"] == r)
        pd = sum(p["payment_order"] for p in po if p["referral"] == r)
        rows.append([lab, sar(ap), sar(pd), pct(pd / ap if ap else 0)])
    ap, pd = sum(p["approved"] for p in po), sum(p["payment_order"] for p in po)
    return R(pct(pd / ap if ap else 0), f"{sar(ap - pd)} {pick('awaiting a payment order', 'بانتظار أمر دفع')} · {qlabel(c)}",
             table=table([pick("Referral", "الإحالة"), pick("Approved", "المعتمد"), pick("Payment orders", "أوامر الدفع"),
                          pick("Coverage", "النسبة")], rows), raw=pd / ap if ap else None)


def fr05(c):
    if _fr(c):
        return _fr(c)
    k = c.get("F4")["carried"]
    if not k.get("unpaid_prior"):
        return nodata("Prior-year unpaid total not found in the carried-forward tracking sheet.")
    paid = k.get("paid_to_qe") or 0
    return R(pct(paid / k["unpaid_prior"]), f"{sar(paid)} {t('of')} {sar(k['unpaid_prior'])} · {qlabel(c)}",
             raw=paid / k["unpaid_prior"])


def fr06(c):
    if _fr(c):
        return _fr(c)
    ex = c.get("F4")["exceptions"]
    by = Counter(e["type"] for e in ex)
    diff = sum(abs(e["difference"]) for e in ex)
    return R(num(len(ex)), f"{pick('net difference', 'صافي الفرق')} {sar(diff)} · {qlabel(c)}",
             table=table([pick("Exception", "الاستثناء"), t("count")], [[k, num(n)] for k, n in by.most_common()]), raw=len(ex))


def fr07(c):
    if _fr(c):
        return _fr(c)
    acc = [a for a in c.get("F4")["accrued"] if a["not_received"]]
    v = sum(a["not_received"] for a in acc)
    return R(sar(v), pick(f"{len(acc)} GSS without an invoice · {qlabel(c)}", f"{len(acc)} ملف GSS دون فاتورة · {qlabel(c)}"), raw=v)


def fr08(c):
    if _fr(c):
        return _fr(c)
    b = c.get("F4")["budget"]
    if not b:
        return nodata("Budget allocation table not found in the budget sheet.")
    al, sp = sum(x["allocation"] for x in b), sum(x["spend"] for x in b)
    return R(pct(sp / al if al else 0), f"{sar(sp)} {t('of')} {sar(al)} · {qlabel(c)}",
             chart=charts.hbar([(x["line"], x["spend"] / x["allocation"] if x["allocation"] else 0) for x in b], pct=True,
                               max_value=1, rtl=lang() == "ar"), raw=sp / al if al else None)


# ------------------------------------------------------------------ FWA, trends and root causes
def fw01(c):
    fl = flags(c, confirmed=False)
    by = defaultdict(set)
    for f in fl:
        by[f["code"] or "-"].add(f["ref"] or f["log_id"])
    rows = sorted(((k, len(v)) for k, v in by.items()), key=lambda r: -r[1])
    return R(num(len({f["ref"] or f["log_id"] for f in fl})), pick(f"encounters, {len(by)} rules triggered", f"حالة، {len(by)} قاعدة"),
             chart=charts.hbar(rows[:12], rtl=lang() == "ar"), raw=len(fl))


def fw02(c):
    fl = flags(c, confirmed=False)
    conf = sum(1 for f in fl if f["status"] == "Confirmed")
    clr = sum(1 for f in fl if f["status"].lower().startswith("cleared"))
    if not conf + clr:
        return R("-", "")
    return R(pct(conf / (conf + clr)), pick(f"{clr} cleared on review", f"{clr} أزيلت بعد المراجعة"), raw=conf / (conf + clr))


def _code_map(c, field):
    return {x["code"]: x[field] for x in c.get("F1")["codes"] if x[field]}


def fw03(c):
    if not c.get("F1")["has"].get("fwa"):
        return nodata("Add an 'FWA level' column to the flag codes in Config.")
    m = _code_map(c, "fwa")
    by = defaultdict(lambda: [0, 0.0])
    for f in flags(c):
        lvl = m.get(f["code"], "Unclassified")
        by[lvl][0] += 1
        by[lvl][1] += f["amount"]
    order = ["Error", "Waste", "Abuse", "Suspected fraud", "Unclassified"]
    return R(num(sum(v[0] for v in by.values())), "", chart=charts.donut([(k, by[k][0]) for k in order if k in by]),
             raw=sum(v[0] for v in by.values()))


def fw04(c):
    fl = [f for f in flags(c, confirmed=False, period=False) if c.inp(f["sent_cnhi"])]
    by = Counter(f["cnhi_response"] or pick("Awaiting response", "بانتظار الرد") for f in fl)
    return R(num(len(fl)), "", chart=charts.hbar(by.most_common(), rtl=lang() == "ar"), raw=len(fl))


def fw05(c):
    has = c.get("F1")["has"]
    fl = flags(c)
    ident = sum(once_per_ref(fl).values())
    sent = sum(once_per_ref([f for f in fl if f["sent_cnhi"]]).values()) if has.get("cnhi") else None
    endorsed = sum(once_per_ref([f for f in fl if f["cnhi_response"].lower().startswith("endorse")]).values()) if has.get("cnhi") else None
    shared = sum(once_per_ref([f for f in fl if f["shared_tpa"]]).values()) if has.get("shared_tpa") else None
    closed = sum(once_per_ref([f for f in fl if f["closed"]]).values()) if has.get("closed") else None
    steps = [(pick("Identified", "محددة"), ident), (pick("Shared with TPA", "محالة للشركة"), shared),
             (pick("Escalated to CNHI", "مصعدة إلى المركز"), sent), (pick("Endorsed by CNHI", "مؤيدة من المركز"), endorsed),
             (pick("Closed or recovered", "مغلقة أو مستردة"), closed)]
    return R(sar(ident), pick("identified on confirmed flags, counted once per encounter", "القيمة المحددة على الملاحظات المؤكدة"),
             chart=charts.funnel(steps, pending_label=t("capture")), raw=ident)


def fw06(c):
    if not c.get("F1")["has"].get("root"):
        return nodata("Add a default 'Root cause' per flag code in Config.")
    m = _code_map(c, "root")
    by = defaultdict(lambda: [0, 0.0])
    for f in flags(c):
        r = m.get(f["code"], "Undetermined")
        by[r][0] += 1
        by[r][1] += f["amount"]
    rows = sorted(by.items(), key=lambda r: -r[1][0])
    return R(num(sum(v[0] for v in by.values())), "", chart=charts.hbar([(k, v[0]) for k, v in rows], rtl=lang() == "ar"),
             raw=sum(v[0] for v in by.values()))


def fw07(c):
    allc = [f for f in c.get("F1")["flags"] if f["status"] == "Confirmed" and c.tpa_ok(f)]
    if not allc:
        return R("-", "")
    first = min(f["date"] for f in allc)
    hist = defaultdict(list)
    for f in allc:
        hist[(f["provider"], f["family"])].append(f["date"])
    cur = [f for f in allc if c.inp(f["date"])]
    if not cur:
        return R("-", "")
    rep = 0
    for f in cur:
        d0 = (dt.date.fromisoformat(f["date"]) - dt.timedelta(days=90)).isoformat()
        if any(d0 <= d < f["date"] for d in hist[(f["provider"], f["family"])]):
            rep += 1
    span = days(first, max(f["date"] for f in cur))
    res = R(pct(rep / len(cur)), f"{rep} {t('of')} {len(cur)}", raw=rep / len(cur))
    if span < 90:
        res["state"], res["note"] = "partial", f"Only {span} days of history loaded; the three-month look-back is incomplete."
    return res


def fw08(c):
    if not c.get("F5"):
        return nodata(MISSING["F5"])
    rs = [r for r in c.get("F5")["recommendations"] if c.upto(r["raised"]) or not r["raised"]]
    acc = sum(1 for r in rs if r["status"] in ("Accepted", "Implemented"))
    imp = sum(1 for r in rs if r["status"] == "Implemented")
    return R(num(len(rs)), pick(f"{acc} accepted · {imp} implemented", f"{acc} معتمدة · {imp} منفذة"), raw=len(rs))


# ------------------------------------------------------------------ Governance and deliverables
def _gv(c):
    return None if c.get("F5") else nodata(MISSING["F5"])


def gv01(c):
    if _gv(c):
        return _gv(c)
    due = [x for x in c.get("F5")["deliverables"] if c.inp(x["due"])]
    by = defaultdict(lambda: [0, 0])
    for x in due:
        by[x["type"]][0] += 1
        by[x["type"]][1] += 1 if x["submitted"] else 0
    sub = sum(v[1] for v in by.values())
    return R(f"{sub} / {len(due)}", pick("submitted / due", "مسلم / مستحق"),
             table=table([pick("Deliverable", "المخرج"), pick("Due", "مستحق"), pick("Submitted", "مسلم")],
                         [[k, num(a), num(b)] for k, (a, b) in by.items()]), raw=sub)


def gv02(c):
    if _gv(c):
        return _gv(c)
    sub = [x for x in c.get("F5")["deliverables"] if c.inp(x["submitted"])]
    if not sub:
        return R("-", pick("No deliverable submitted in this period", "لم يسلم أي مخرج في هذه الفترة"))
    ok = sum(1 for x in sub if x["approved"])
    return R(pct(ok / len(sub)), f"{ok} {t('of')} {len(sub)}", raw=ok / len(sub))


def gv03(c):
    if _gv(c):
        return _gv(c)
    xs = [days(x["submitted"], x["approved"]) for x in c.get("F5")["deliverables"] if c.inp(x["approved"]) and x["submitted"]]
    m = median(xs)
    if not xs and any(c.inp(d["response"]) for d in disputes(c)):
        return nodata(pick("Needs the received date of the disputes answered in this period: enter it on their batch in the tracker.",
                           "يتطلب تاريخ استلام الاعتراضات التي تم الرد عليها في هذه الفترة: أدخله على الدفعة في السجل."))
    return R(num(m) if m is not None else "-", pick(f"days, median of {len(xs)}", f"يوم، الوسيط من {len(xs)}"), raw=m)


def gv04(c):
    if _gv(c):
        return _gv(c)
    sub = [x for x in c.get("F5")["deliverables"] if c.inp(x["submitted"])]
    if not sub:
        return R("-", "")
    ok = sum(1 for x in sub if x["qa"] and x["qa"] <= x["submitted"])
    return R(pct(ok / len(sub)), f"{ok} {t('of')} {len(sub)}", raw=ok / len(sub))


def gv05(c):
    if _gv(c):
        return _gv(c)
    ms = [m for m in c.get("F5")["meetings"] if c.inp(m["planned"])]
    if not ms:
        return R("-", "")
    held = sum(1 for m in ms if m["held"])
    return R(pct(held / len(ms)), f"{held} {t('of')} {len(ms)}", raw=held / len(ms))


def gv06(c):
    if _gv(c):
        return _gv(c)
    kt = [k for k in c.get("F5")["kt"] if c.upto(k["planned"])]
    if not kt:
        return R("-", "")
    done = sum(1 for k in kt if k["delivered"] and k["delivered"] <= c.end)
    return R(pct(done / len(kt)), f"{done} {t('of')} {len(kt)}", raw=done / len(kt))


FUNCS = {
    "EX-01": ex01, "EX-02": ex02, "EX-03": ex03, "EX-04": ex04, "EX-05": ex05, "EX-06": ex06, "EX-07": ex07,
    "EX-08": ex08, "EX-09": ex09, "EX-10": ex10,
    "DR-01": dr01, "DR-02": dr02, "DR-03": dr03, "DR-04": dr04, "DR-05": dr05, "DR-06": dr06, "DR-07": dr07, "DR-08": dr08,
    "HD-01": hd01, "HD-02": hd02, "HD-03": hd03, "HD-04": hd04, "HD-05": hd05, "HD-06": hd06, "HD-07": hd07,
    "GS-01": gs01, "GS-02": gs02, "GS-03": gs03, "GS-04": gs04, "GS-05": gs05, "GS-06": gs06, "GS-07": gs07, "GS-08": gs08,
    "FR-01": fr01, "FR-02": fr02, "FR-03": fr03, "FR-04": fr04, "FR-05": fr05, "FR-06": fr06, "FR-07": fr07, "FR-08": fr08,
    "FW-01": fw01, "FW-02": fw02, "FW-03": fw03, "FW-04": fw04, "FW-05": fw05, "FW-06": fw06, "FW-07": fw07, "FW-08": fw08,
    "GV-01": gv01, "GV-02": gv02, "GV-03": gv03, "GV-04": gv04, "GV-05": gv05, "GV-06": gv06,
}
NEEDS = {"EX-01": "F1", "EX-02": "F1", "EX-03": "F1", "EX-04": "F1", "EX-06": "F1", "DR": "F1", "FW": "F1"}


def compute(kid, c):
    need = NEEDS.get(kid) or NEEDS.get(kid[:2])
    if kid == "FW-08":
        need = None
    if need and not c.get(need):
        return nodata(MISSING[need])
    try:
        return FUNCS[kid](c)
    except Exception as e:  # noqa: BLE001 - one bad KPI must not break the page
        return R(None, state="error", note=f"Could not compute: {type(e).__name__}: {e}")


def compute_page(page_code, c):
    return {k["id"]: compute(k["id"], c) for k in config.kpis_for(page_code)}


def months(data):
    ms = set()
    if data.get("F1"):
        ms |= {x["date"][:7] for x in data["F1"]["intake"]}
        ms |= {f["date"][:7] for f in data["F1"]["flags"]}
    if data.get("F2"):
        ms |= {g["issued"][:7] for g in data["F2"]["gss"] if g["issued"]}
    if data.get("F3"):
        ms |= {(d["received"] or d["closed"])[:7] for d in data["F3"]["disputes"] if d["received"] or d["closed"]}
    if data.get("F5"):
        ms |= {x["due"][:7] for x in data["F5"]["deliverables"] if x["due"]}
    cur = dt.date.today().isoformat()[:7]
    return sorted(m for m in ms if m and m[:4].isdigit() and m <= cur)


def default_month(data):
    """Latest month with daily review activity, else the latest month with any activity."""
    if data.get("F1"):
        ms = sorted({x["date"][:7] for x in data["F1"]["intake"]})
        if ms:
            return ms[-1]
    ms = months(data)
    return ms[-1] if ms else "all"


def tpas(data):
    s = set()
    if data.get("F1"):
        s |= {x["tpa"] for x in data["F1"]["intake"] if x["tpa"]}
    if data.get("F2"):
        s |= {g["tpa"] for g in data["F2"]["gss"] if g["tpa"]}
    return sorted(s)


def exec_trend(c, selected=None):
    """Two monthly charts (all months, current TPA filter): encounters reviewed, and the finding rate."""
    if not c.get("F1"):
        return None
    rev, flg = defaultdict(float), defaultdict(set)
    for x in c.get("F1")["intake"]:
        if c.tpa_ok(x):
            rev[x["date"][:7]] += x["reviewed"]
    for f in c.get("F1")["flags"]:
        if f["status"] == "Confirmed" and c.tpa_ok(f):
            flg[f["date"][:7]].add(f["ref"] or f["log_id"])
    ms = [m for m in sorted(rev) if rev[m]]
    return dict(volume=charts.columns(ms, [(t("encounters"), [rev[m] for m in ms])], tones=["teal"], highlight_last=True, highlight=selected),
                rate=charts.columns(ms, [(pick("Finding rate", "نسبة الحالات ذات الملاحظات"),
                                          [len(flg[m]) / rev[m] for m in ms])], pct=True, tones=["indigo"], highlight_last=True, highlight=selected))


def history(kids, data, period, tpa, n=6):
    """Raw values of each KPI over the last n months up to the period, for tile sparklines."""
    ms = [m for m in months(data) if period == "all" or m <= period][-n:]
    out = {k: [] for k in kids}
    for m in ms:
        c = Ctx(data, m, tpa)
        for k in kids:
            r = compute(k, c)
            v = r.get("raw")
            out[k].append(v if isinstance(v, (int, float)) and r.get("state") == "ok" else None)
    return out


def serialise(results):
    """For snapshots: Markup -> str so the result can be stored as JSON."""
    out = {}
    for k, r in results.items():
        out[k] = {key: (str(v) if isinstance(v, Markup) else v) for key, v in r.items()}
    return out


def deserialise(results):
    out = {}
    for k, r in results.items():
        r = dict(r)
        if r.get("chart"):
            r["chart"] = Markup(r["chart"])
        out[k] = r
    return out
