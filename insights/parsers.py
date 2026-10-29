"""Read the team's Excel workbooks into de-identified datasets.

Columns are found by their header text, not by letter, so inserting a column in a workbook does not break the
upload. Only the columns listed here are read: patient identifiers and free-text narratives are never read.
Each parser returns {"data": ..., "summary": ..., "warnings": [...]} or raises ParseError with a plain message.
"""
import datetime as dt
import re
import warnings as _warnings

from openpyxl import load_workbook

from . import config, deid

_warnings.filterwarnings("ignore", module="openpyxl")


class ParseError(Exception):
    pass


# ------------------------------------------------------------------ cell helpers
def norm(s):
    if s is None:
        return ""
    s = str(s).replace("\xa0", " ").replace("‏", "").replace("‎", "")
    return re.sub(r"\s+", " ", s).strip().lower()


def to_date(v):
    if v is None or v == "":
        return None
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, (int, float)) and 20000 < v < 80000:          # Excel serial date
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(v))).isoformat()
    s = str(v).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def to_num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if not s or s.startswith("#"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def to_text(v):
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.startswith("#") else s


def open_book(path):
    try:
        return load_workbook(path, read_only=True, data_only=True, keep_links=False)
    except Exception as e:  # noqa: BLE001 - surface any workbook error as a plain message
        raise ParseError(f"The file could not be opened as an Excel workbook ({type(e).__name__}).")


def find_sheet(wb, *names, required=True):
    wanted = [norm(n) for n in names]
    for ws in wb.worksheets:
        t = norm(ws.title)
        if any(t == w or t.startswith(w) or w in t for w in wanted):
            return ws
    if required:
        raise ParseError(f"Sheet '{names[0]}' was not found in the workbook.")
    return None


class Table:
    """Rows of one sheet, with columns located by header text."""

    def __init__(self, ws, must, max_col=80, scan=15, max_rows=None):
        self.title = ws.title
        rows = ws.iter_rows(values_only=True, max_col=max_col, max_row=max_rows)
        self.header_row = None
        self.cols = {}
        self.rows = []
        must_n = [norm(m) for m in must]
        for i, r in enumerate(rows, start=1):
            if self.header_row is None:
                names = [norm(c) for c in r]
                if all(any(n == m for n in names) for m in must_n):
                    self.header_row = i
                    for j, n in enumerate(names):
                        if n and n not in self.cols:
                            self.cols[n] = j
                    continue
                if i >= scan:
                    break
            else:
                self.rows.append(r)
        if self.header_row is None:
            raise ParseError(f"Sheet '{ws.title}': header row with {', '.join(must)} not found in the first {scan} rows.")

    def has(self, name):
        return norm(name) in self.cols

    def get(self, row, *names):
        for n in names:
            j = self.cols.get(norm(n))
            if j is not None and j < len(row):
                return row[j]
        return None


def tpa_name(raw):
    s = to_text(raw)
    return config.TPA_MAP.get(norm(s), s) if s else ""


def month_range(dates):
    ds = sorted(d for d in dates if d)
    return (ds[0], ds[-1]) if ds else (None, None)


# ------------------------------------------------------------------ F1 daily register
def parse_f1(path):
    wb = open_book(path)
    warn = []
    # daily intake
    t = Table(find_sheet(wb, "Daily Intake"), ["Date received", "Volume received", "Reviewed"], max_col=14)
    intake = []
    for r in t.rows:
        d = to_date(t.get(r, "Date received"))
        if not d:
            continue
        intake.append(dict(date=d, source=to_text(t.get(r, "Source")), tpa=tpa_name(t.get(r, "TPA")),
                           received=to_num(t.get(r, "Volume received")) or 0, reviewed=to_num(t.get(r, "Reviewed")) or 0,
                           outstanding=to_num(t.get(r, "Outstanding")) or 0))
    # review log
    review = []
    ws = find_sheet(wb, "Daily Review Log", required=False)
    if ws is not None:
        t = Table(ws, ["Date", "Records reviewed"], max_col=15)
        for r in t.rows:
            d = to_date(t.get(r, "Date"))
            if not d:
                continue
            review.append(dict(date=d, reviewer=deid.person(t.get(r, "Reviewer")), tpa=tpa_name(t.get(r, "TPA")),
                               records=to_num(t.get(r, "Records reviewed")) or 0, confirmed=to_num(t.get(r, "Confirmed")) or 0,
                               declared=to_num(t.get(r, "Declared total")), logged=to_num(t.get(r, "Logged in Daily Log"))))
        bad = [x for x in review if x["declared"] is not None and x["logged"] is not None and x["declared"] != x["logged"]]
        if bad:
            warn.append(f"Daily Review Log: {len(bad)} reviewer-day row(s) where the declared total differs from the flags logged.")
    # config: flag taxonomy, optional FWA level and root cause per code, NPHIES approvals
    codes, nphies = [], []
    ws = find_sheet(wb, "Config", required=False)
    if ws is not None:
        t = Table(ws, ["Flag code"], max_col=40)
        for r in t.rows:
            c = to_text(t.get(r, "Flag code"))
            if re.match(r"^[A-Z]{2,4}-\d{1,3}$", c):
                codes.append(dict(code=c, family=c.split("-")[0], type_en=to_text(t.get(r, "Flag type (English)")),
                                  type_ar=to_text(t.get(r, "نوع الملاحظة")), fwa=to_text(t.get(r, "FWA level")),
                                  root=to_text(t.get(r, "Root cause", "Default root cause"))))
            m = to_date(t.get(r, "Month"))
            if m and t.has("Approved amount (SAR)"):
                nphies.append(dict(month=m[:7], tpa=tpa_name(t.get(r, "TPA")),
                                   approvals=to_num(t.get(r, "NPHIES approvals (Approved + Partial)")),
                                   approved=to_num(t.get(r, "Approved amount (SAR)"))))
    known = {c["code"] for c in codes}
    # daily log: one row per flag
    t = Table(find_sheet(wb, "Daily Log"), ["Log ID", "Reference no.", "Flag code", "Flag status"], max_col=60)
    has = dict(shared_tpa=t.has("Shared with TPA on"), selection=t.has("Selection reason"),
               evidence=t.has("Evidence reference"), fwa=any(c["fwa"] for c in codes), root=any(c["root"] for c in codes),
               closed=False, cnhi=t.has("Sent to CNHI on"))
    flags, skipped, unknown = [], 0, set()
    for r in t.rows:
        lid = to_text(t.get(r, "Log ID"))
        d = to_date(t.get(r, "Date logged"))
        if not lid or not d:
            if lid:
                skipped += 1
            continue
        code = to_text(t.get(r, "Flag code"))
        if code and known and code not in known:
            unknown.add(code)
        f = dict(log_id=lid, date=d, source=to_text(t.get(r, "Source")), ref=deid.ref(t.get(r, "Reference no.")),
                 tpa=tpa_name(t.get(r, "TPA")), provider=to_text(t.get(r, "Provider")), code=code,
                 family=code.split("-")[0] if "-" in code else (code or "Unclassified"),
                 status=to_text(t.get(r, "Flag status")), severity=to_text(t.get(r, "Severity")),
                 action=to_text(t.get(r, "Action level")), amount=to_num(t.get(r, "Amount at risk (SAR)")) or 0,
                 owner_type=to_text(t.get(r, "Owner type")), due=to_date(t.get(r, "Due date")),
                 state=to_text(t.get(r, "Status")), closed=to_date(t.get(r, "Date closed")),
                 shared_tpa=to_date(t.get(r, "Shared with TPA on")), selection=to_text(t.get(r, "Selection reason")),
                 evidence=to_text(t.get(r, "Evidence reference")), sent_cnhi=to_date(t.get(r, "Sent to CNHI on")),
                 cnhi_response=to_text(t.get(r, "CNHI response")), cnhi_status=to_text(t.get(r, "CNHI status")))
        flags.append(f)
    has["closed"] = any(f["closed"] for f in flags)
    if skipped:
        warn.append(f"Daily Log: {skipped} row(s) with a Log ID but no valid date were skipped.")
    if unknown:
        warn.append(f"Daily Log: flag code(s) not in Config: {', '.join(sorted(unknown)[:10])}.")
    blank_state = sum(1 for f in flags if not f["state"])
    if flags and blank_state / len(flags) > 0.2:
        warn.append(f"Daily Log: Status is blank for {blank_state} of {len(flags)} flags; resolution KPIs will show 'data capture in progress'.")
    for col, label in (("shared_tpa", "Shared with TPA on"), ("selection", "Selection reason"), ("evidence", "Evidence reference")):
        if not has[col]:
            warn.append(f"Daily Log: optional column '{label}' not found; the KPIs that need it show 'data capture in progress'.")
    tpas = sorted({x["tpa"] for x in intake + flags if x["tpa"]})
    lo, hi = month_range([x["date"] for x in intake])
    summary = {"Intake rows": len(intake), "Review log rows": len(review), "Flags": len(flags),
               "Confirmed flags": sum(1 for f in flags if f["status"] == "Confirmed"),
               "Distinct references (hashed)": len({f["ref"] for f in flags}), "Flag codes in Config": len(codes),
               "Intake dates": f"{lo} to {hi}" if lo else "-", "TPAs": ", ".join(tpas)}
    if not intake:
        raise ParseError("Daily Intake has no dated rows.")
    return dict(data=dict(intake=intake, review=review, flags=flags, codes=codes, nphies=nphies, has=has),
                summary=summary, warnings=warn)


# ------------------------------------------------------------------ F2 GSS Assurance Workbook
def parse_f2(path):
    wb = open_book(path)
    warn = []
    t = Table(find_sheet(wb, "GSS Register"), ["GSS ID", "Assurance opinion"], max_col=60)
    gss = []
    for r in t.rows:
        gid = to_text(t.get(r, "GSS ID"))
        if not gid or norm(gid) == "gss id":
            continue
        gss.append(dict(gss_id=gid, hospital=to_text(t.get(r, "Hospital")), tpa=tpa_name(t.get(r, "TPA")),
                        billing_month=(to_date(t.get(r, "Billing month")) or "")[:7], claims=to_num(t.get(r, "Claims in GSS")) or 0,
                        claimed=to_num(t.get(r, "Claimed (SAR)")) or 0, start=to_date(t.get(r, "Review start date")),
                        status=to_text(t.get(r, "Status")), k={f"K{i}": to_text(t.get(r, f"K{i}")) for i in range(1, 13)},
                        critical_fails=to_num(t.get(r, "Critical fails")) or 0, issued=to_date(t.get(r, "Report issued date")),
                        closed=to_date(t.get(r, "Closed date")), sampled=to_num(t.get(r, "Sampled claims")) or 0,
                        sample_value=to_num(t.get(r, "Sample value (SAR)")) or 0, reviewed=to_num(t.get(r, "Claims reviewed")) or 0,
                        flagged=to_num(t.get(r, "Claims flagged")) or 0, opinion=to_text(t.get(r, "Assurance opinion"))))
    t = Table(find_sheet(wb, "Sample Register"), ["GSS ID", "Claim bundle ID", "Amount at issue (SAR)"], max_col=40)
    sample = []
    for r in t.rows:
        gid = to_text(t.get(r, "GSS ID"))
        if not gid or norm(gid) == "gss id":
            continue
        sample.append(dict(gss_id=gid, bundle=deid.ref(t.get(r, "Claim bundle ID")), claim_type=to_text(t.get(r, "Claim type")),
                           amount=to_num(t.get(r, "Claim amount (SAR)")) or 0, basis=to_text(t.get(r, "Selection basis")),
                           outcome=to_text(t.get(r, "Outcome")), category=to_text(t.get(r, "Finding category")),
                           recommendation=to_text(t.get(r, "Recommendation")), at_issue=to_num(t.get(r, "Amount at issue (SAR)")) or 0,
                           review_date=to_date(t.get(r, "Review date")), flag=to_text(t.get(r, "Flag")),
                           severity=to_text(t.get(r, "Flag severity")), owner=to_text(t.get(r, "Flag owner")),
                           due=to_date(t.get(r, "Due date")), flag_status=to_text(t.get(r, "Flag status")),
                           closed=to_date(t.get(r, "Closed date"))))
    queue = []
    ws = find_sheet(wb, "Priority Queue", required=False)
    if ws is not None:
        try:
            t = Table(ws, ["GSS ID", "Review status"], max_col=32)
            for r in t.rows:
                gid = to_text(t.get(r, "GSS ID"))
                if gid and norm(gid) != "gss id":
                    queue.append(dict(gss_id=gid, tier=to_text(t.get(r, "Tier")), claimed=to_num(t.get(r, "Claimed (SAR)")) or 0,
                                      status=to_text(t.get(r, "Review status")), tpa=tpa_name(t.get(r, "TPA"))))
        except ParseError as e:
            warn.append(str(e))
    issued = [g for g in gss if g["issued"]]
    incomplete_issued = [g for g in issued if g["opinion"] == "Review incomplete"]
    if incomplete_issued:
        warn.append(f"{len(incomplete_issued)} GSS have a report issued date but the opinion reads 'Review incomplete'.")
    no_date = [s for s in sample if s["at_issue"] and not s["review_date"]]
    if no_date:
        warn.append(f"Sample Register: {len(no_date)} claim(s) with an amount at issue but no review date; they are excluded from monthly figures.")
    summary = {"GSS registered": len(gss), "Reports issued": len(issued), "Sampled claims": len(sample),
               "Claims with amount at issue": sum(1 for s in sample if s["at_issue"]), "GSS in queue": len(queue),
               "Report dates": "{} to {}".format(*month_range([g["issued"] for g in issued])) if issued else "-"}
    if not gss:
        raise ParseError("GSS Register has no GSS rows.")
    return dict(data=dict(gss=gss, sample=sample, queue=queue, as_of=dt.date.today().isoformat()), summary=summary, warnings=warn)


# ------------------------------------------------------------------ F3 hospital disputes tracker
# Reads tracker v1.0 (Batches, Disputes, Actions) and the earlier v0.1 template (Disputes, Time Log).
def parse_f3(path):
    wb = open_book(path)
    warn = []
    # batch dates (v1.0): disputes inherit them unless their own row overrides
    batches = {}
    ws = find_sheet(wb, "Batches", required=False)
    if ws is not None:
        bt = Table(ws, ["Batch ID", "Received date"], max_col=14)
        for r in bt.rows:
            bid = to_text(bt.get(r, "Batch ID"))
            if bid:
                batches[bid] = (to_date(bt.get(r, "Received date")), to_date(bt.get(r, "KPMG opinion date")))
    OUTCOME = {"Not accepted": "Maintained", "Partially accepted": "Partially maintained", "Accepted": "Reversed",
               "Withdrawn by hospital": "Withdrawn by hospital"}
    t = Table(find_sheet(wb, "Disputes"), ["Dispute ID", "Received date"], max_col=45)
    disputes, no_date, no_amount = [], 0, 0
    for r in t.rows:
        did = to_text(t.get(r, "Dispute ID"))
        if not did or did.upper().startswith("EXAMPLE"):
            continue
        position = to_text(t.get(r, "KPMG position"))
        b_rec, b_op = batches.get(to_text(t.get(r, "Batch ID")), (None, None))
        # calculated columns are re-derived when the file was saved without recalculation (same rules as the workbook)
        rec = to_date(t.get(r, "Received date")) or to_date(t.get(r, "Received date (if different from batch)")) or b_rec
        no_date += 0 if rec else 1
        claimed, approved = to_num(t.get(r, "Claimed amount (SAR)")), to_num(t.get(r, "Approved amount (SAR)"))
        value = to_num(t.get(r, "Amount disputed (SAR)", "Value disputed (SAR)"))
        if value is None and claimed is not None and approved is not None:
            value = claimed - approved
        kept = to_num(t.get(r, "Value maintained (SAR)"))
        pay = to_num(t.get(r, "Value to pay (SAR) - partial only"))
        if kept is None and value is not None:
            kept = (value if position in ("Not accepted", "Withdrawn by hospital") else 0 if position == "Accepted"
                    else value - pay if position == "Partially accepted" and pay is not None else None)
        opinion = to_date(t.get(r, "KPMG opinion date", "Response date"))
        if not opinion and position and position != "Pending":
            opinion = to_date(t.get(r, "KPMG opinion date (if different from batch)")) or b_op
        outcome = to_text(t.get(r, "Outcome")) or OUTCOME.get(position, "")
        closed = to_date(t.get(r, "Closure date")) or (opinion if outcome else None)
        if value is None and position != "Pending":
            no_amount += 1
        if kept is not None and value is not None and kept > value:
            warn.append(f"Dispute {did}: value maintained exceeds the amount disputed.")
        disputes.append(dict(
            id=did, batch=to_text(t.get(r, "Batch ID")), received=rec, hospital=to_text(t.get(r, "Hospital")),
            tpa=tpa_name(t.get(r, "TPA")), pathway=to_text(t.get(r, "Pathway")), round=to_text(t.get(r, "Round")),
            type=to_text(t.get(r, "Dispute theme", "Dispute type")), claimed=claimed,
            value=value, response=opinion, status=to_text(t.get(r, "Status")),
            closed=closed, outcome=outcome, maintained=kept,
            position=position, action=to_text(t.get(r, "Recommended action")), fwa=to_text(t.get(r, "FWA indicator")) or "None",
            cnhi=to_text(t.get(r, "CNHI final decision"))))
    if no_date:
        warn.append(f"{no_date} dispute(s) have no received date (enter it on the batch); they are left out of monthly intake and ageing.")
    if no_amount:
        warn.append(f"{no_amount} dispute(s) reviewed without an approved amount; value disputed and value maintained exclude them.")
    undated = sum(1 for d in disputes if d["position"] not in ("", "Pending") and not d["closed"])
    if undated:
        warn.append(f"{undated} KPMG opinion(s) have no opinion date (enter it on the batch); they are left out of EX-07, EX-08 and the outcome KPIs.")
    time_log = []
    ws = find_sheet(wb, "Actions", required=False) or find_sheet(wb, "Time Log", required=False)
    if ws is not None:
        t = Table(ws, ["Date", "Hours"], max_col=12)
        for r in t.rows:
            d, h = to_date(t.get(r, "Date")), to_num(t.get(r, "Hours"))
            did = to_text(t.get(r, "Dispute ID"))
            if not d or not h or did.upper().startswith("EXAMPLE"):
                continue
            time_log.append(dict(date=d, member=deid.person(t.get(r, "Team member")), dispute=did,
                                 activity=to_text(t.get(r, "Action type", "Activity")), hours=h,
                                 estimated=norm(t.get(r, "Estimated? (backfilled)")) == "yes"))
    ids = {d["id"] for d in disputes}
    if len(ids) != len(disputes):
        warn.append("Duplicate Dispute IDs found; each is counted as recorded.")
    hosp = sorted({d["hospital"] for d in disputes if d["hospital"]})
    summary = {"Disputes": len(disputes), "Hospitals": ", ".join(hosp),
               "KPMG opinions issued": sum(1 for d in disputes if d["position"] and d["position"] != "Pending"),
               "Of which dated": sum(1 for d in disputes if d["closed"]),
               "Pending KPMG review": sum(1 for d in disputes if d["position"] == "Pending"),
               "With an FWA indicator": sum(1 for d in disputes if d["fwa"] not in ("", "None")),
               "Action / time-log rows": len(time_log), "Hours logged": round(sum(x["hours"] for x in time_log), 1),
               "Of which estimated": round(sum(x["hours"] for x in time_log if x["estimated"]), 1)}
    return dict(data=dict(disputes=disputes, time=time_log), summary=summary, warnings=warn)


# ------------------------------------------------------------------ F4 quarterly accounting report
AR_Q = {"الاول": 1, "الأول": 1, "الثاني": 2, "الثالث": 3, "الرابع": 4}


def quarter_from_titles(wb):
    for ws in wb.worksheets:
        m = re.search(r"الربع\s+(\S+)\s+(\d{4})", ws.title)
        if m and m.group(1) in AR_Q:
            return f"{m.group(2)}-Q{AR_Q[m.group(1)]}"
    return ""


def _label_rows(ws, max_col=18, max_rows=60):
    return [r for r in ws.iter_rows(values_only=True, max_col=max_col, max_row=max_rows)]


def parse_f4(path, label=""):
    wb = open_book(path)
    warn = []
    quarter = label.strip() or quarter_from_titles(wb)
    if not re.match(r"^\d{4}-Q[1-4]$", quarter):
        raise ParseError("Enter the quarter (for example 2026-Q1): it could not be read from the sheet names.")
    # purchase-order detail (read columns A-P only: the sheet carries thousands of formatted columns)
    t = Table(find_sheet(wb, "مطالبات الربع"), ["Hospital Name (Arabic)", "Total Claimed Amount"], max_col=16, scan=5)
    po = []
    for r in t.rows:
        claimed = to_num(t.get(r, "Total Claimed Amount"))
        if claimed is None:
            continue
        ref = to_text(r[0]) if r else ""
        po.append(dict(referral="outside" if "خارج" in ref else "inside", hospital=to_text(t.get(r, "Hospital Name (Arabic)")),
                       billing_month=(to_date(t.get(r, "Billing Month")) or "")[:7], claims=to_num(t.get(r, "Count of Claim Name")) or 0,
                       claimed=claimed, approved=to_num(t.get(r, "Total Approved Amount")) or 0,
                       payment_order=to_num(t.get(r, "قيمة صافي أمر الدفع بالريال")) or 0))
    # provider summary: approved, payment orders, value without payment order
    ws = find_sheet(wb, "تقرير الربع")
    rows = _label_rows(ws, max_col=16, max_rows=600)
    summary_rows = [r for r in rows[8:] if isinstance(r[0], (int, float))]
    approved_total = sum(to_num(r[9]) or 0 for r in summary_rows)
    paid_total = sum(to_num(r[13]) or 0 for r in summary_rows)
    without_po = sum(to_num(r[14]) or 0 for r in summary_rows)
    # carried-forward tracking: prior-year unpaid, paid to latest quarter end, duplicate deductions
    carried = dict(unpaid_prior=None, paid_to_qe=None, paid_label="", duplicates=None)
    ws = find_sheet(wb, "تتبع المطالبات المرحلة", required=False)
    if ws is not None:
        for r in _label_rows(ws, max_col=16, max_rows=40):
            lab, tot = norm(r[0]), to_num(r[13]) if len(r) > 13 else None
            if lab.startswith("اجمالي المطالبات غير المدفوعة"):
                carried["unpaid_prior"] = tot
            elif lab.startswith("المبالغ اصدر لها امر دفع لغاية") and tot:
                carried["paid_to_qe"], carried["paid_label"] = tot, to_text(r[0])
            elif "دفعات مكررة" in lab and carried["duplicates"] is None:
                carried["duplicates"] = tot
    else:
        warn.append("Carried-forward tracking sheet not found: FR-03 and FR-05 will show no data.")
    # accrued expenses by GSS
    accrued = []
    ws = find_sheet(wb, "تتبع المصاريف المستحقة", required=False)
    if ws is not None:
        t = Table(ws, ["GSS_ID", "TOTAL APPROVED"], max_col=18)
        nr_col = next((j for n, j in t.cols.items() if n.startswith("المطالبات غير المستلمة")), None)
        for r in t.rows:
            gid = to_text(t.get(r, "GSS_ID"))
            if not gid:
                continue
            accrued.append(dict(gss_id=gid, status=to_text(t.get(r, "STATUS")), total_claim=to_num(t.get(r, "TOTAL CLAIM")) or 0,
                                total_approved=to_num(t.get(r, "TOTAL APPROVED")) or 0,
                                not_received=(to_num(r[nr_col]) or 0) if nr_col is not None and nr_col < len(r) else 0))
    # reconciliation exceptions
    exceptions = []
    ws = find_sheet(wb, "ملاحظات المدخلات", required=False)
    if ws is not None:
        t = Table(ws, ["الوصف", "الفرق"], max_col=10, scan=5)
        for r in t.rows:
            desc = to_text(t.get(r, "الوصف"))
            if desc:
                exceptions.append(dict(type=desc, po_value=to_num(t.get(r, "قيمة أمر الدفع")) or 0,
                                       claim_value=to_num(t.get(r, "قيمة المطالبة")) or 0,
                                       difference=to_num(t.get(r, "الفرق")) or 0))
    # budget: allocation and spend by treatment line
    budget = []
    ws = find_sheet(wb, "الموازنة", required=False)
    if ws is not None:
        rows = _label_rows(ws, max_col=10, max_rows=40)
        hdr = next((i for i, r in enumerate(rows) if any(norm(c) == "الإعتماد الحالي" for c in r)), None)
        if hdr is not None:
            names = [norm(c) for c in rows[hdr]]
            ci = {n: j for j, n in enumerate(names) if n}
            for r in rows[hdr + 1:]:
                line = to_text(r[ci.get("اسم البند", 2)])
                alloc = to_num(r[ci.get("الإعتماد الحالي", 3)])
                spend = to_num(r[ci.get("الجملة", 6)])
                if not line or alloc is None or not line.startswith("نفقات"):
                    if line and line.startswith("جملة"):
                        break
                    continue
                budget.append(dict(line=line, allocation=alloc, spend=spend or 0))
        if not budget:
            warn.append("Budget sheet: allocation table (الإعتماد الحالي) not found; FR-08 will show spend only if available.")
    summary = {"Quarter": quarter, "Purchase-order rows": len(po), "Claimed (SAR)": f"{sum(p['claimed'] for p in po):,.0f}",
               "Approved (SAR)": f"{sum(p['approved'] for p in po):,.0f}", "Providers in summary": len(summary_rows),
               "Accrued GSS rows": len(accrued), "Reconciliation exceptions": len(exceptions), "Budget lines": len(budget)}
    if not po:
        raise ParseError("No purchase-order rows were found in the quarterly claims sheet.")
    return dict(data=dict(quarter=quarter, po=po, totals=dict(approved=approved_total, paid=paid_total, without_po=without_po),
                          carried=carried, accrued=accrued, exceptions=exceptions, budget=budget),
                summary=summary, warnings=warn)


# ------------------------------------------------------------------ F5 governance register
MONTH_FORMATS = ("%Y-%m", "%b-%Y", "%b %Y", "%B %Y", "%B-%Y", "%m/%Y", "%Y/%m")


def to_month(v):
    """A month typed as a date, '2026-10', 'Oct-2026' or '10/2026' -> '2026-10'."""
    d = to_date(v)
    if d:
        return d[:7]
    txt = to_text(v)
    for f in MONTH_FORMATS:
        try:
            return dt.datetime.strptime(txt, f).strftime("%Y-%m")
        except ValueError:
            pass
    return ""


def sheet_rows(wb, warn, sheet, must, fields, optional=False):
    """Rows of a register sheet as dicts. fields: key -> (header, kind) with kind d(ate), n(umber) or t(ext).
    The example row (first field starting with EXAMPLE) and blank rows are skipped."""
    ws = find_sheet(wb, sheet, required=False)
    if ws is None:
        if not optional:
            warn.append(f"Sheet '{sheet}' not found.")
        return []
    t = Table(ws, must, max_col=24)
    out = []
    for r in t.rows:
        rec = {}
        for key, (col, kind) in fields.items():
            v = t.get(r, col)
            rec[key] = to_date(v) if kind == "d" else to_num(v) if kind == "n" else to_text(v)
        if any(v not in (None, "") for v in rec.values()) and not str(rec.get(list(fields)[0], "")).upper().startswith("EXAMPLE"):
            out.append(rec)
    return out


def parse_f5(path):
    wb = open_book(path)
    warn = []

    def rows(sheet, must, fields, optional=False):
        return sheet_rows(wb, warn, sheet, must, fields, optional)

    deliverables = rows("Deliverables", ["Deliverable type", "Due date"], {
        "type": ("Deliverable type", "t"), "period": ("Period", "t"), "due": ("Due date", "d"), "qa": ("QA sign-off date", "d"),
        "submitted": ("Submitted date", "d"), "approved": ("CNHI approval date", "d"), "ref": ("Reference", "t")})
    meetings = rows("Meetings", ["Meeting type", "Planned date"], {
        "type": ("Meeting type", "t"), "planned": ("Planned date", "d"), "held": ("Held date", "d")})
    recs = rows("Recommendations", ["Recommendation ID", "Status"], optional=True, fields={   # moved to F6; older registers still read
        "id": ("Recommendation ID", "t"), "title": ("Title", "t"), "root": ("Root cause", "t"), "owner": ("Owner", "t"),
        "raised": ("Raised date", "d"), "status": ("Status", "t"), "accepted": ("Accepted date", "d"),
        "implemented": ("Implemented date", "d")})
    kt = rows("Knowledge transfer", ["Item", "Planned date"], {
        "item": ("Item", "t"), "type": ("Type", "t"), "planned": ("Planned date", "d"), "delivered": ("Delivered date", "d")})
    effort = []
    for e in rows("Team effort", ["Workstream", "Person-days"], {
            "workstream": ("Workstream", "t"), "role": ("Role", "t"), "month": ("Month", "t"), "days": ("Person-days", "n")}):
        e["month"] = to_month(e["month"])
        if not e["month"] or not e["days"]:
            warn.append(f"Team effort: a row for '{e['workstream'] or '-'}' has no month or no person-days; it was skipped.")
            continue
        effort.append(e)
    requests = rows("CNHI requests", ["Request ID", "Date received"], {
        "id": ("Request ID", "t"), "received": ("Date received", "d"), "unit": ("Requesting unit", "t"),
        "type": ("Request type", "t"), "due": ("Due date", "d"), "delivered": ("Delivered date", "d"),
        "hours": ("Hours", "n"), "status": ("Status", "t")})
    contract = {}
    ws = find_sheet(wb, "Contract", required=False)
    if ws is not None:
        keys = {"contract start date": "start", "contract duration (months)": "months", "physicians (fte)": "physicians",
                "finance consultants (fte)": "finance", "hours per person-day": "hours_per_day"}
        for r in ws.iter_rows(min_row=5, max_row=40, max_col=2, values_only=True):
            k = keys.get(norm(r[0])) if r and r[0] else None
            if k:
                contract[k] = to_date(r[1]) if k == "start" else to_num(r[1])
    if not contract.get("start"):
        warn.append("Contract sheet: the contract start date is blank; contract-to-date figures start from the earliest data.")
    summary = {"Deliverables": len(deliverables), "Meetings": len(meetings),
               "Knowledge-transfer items": len(kt), "Team effort rows": len(effort),
               "Person-days recorded": round(sum(e["days"] for e in effort), 1), "CNHI requests": len(requests),
               "Contract start": contract.get("start") or "-"}
    return dict(data=dict(deliverables=deliverables, meetings=meetings, recommendations=recs, kt=kt, effort=effort,
                          requests=requests, contract=contract), summary=summary, warnings=warn)


# ------------------------------------------------------------------ F6 governance & corrective-action register
APPROVED = ("approved", "approved with changes")
NOTE_MAX = int((config.SETTINGS.get("corrective_actions") or {}).get("status_note_max", 200))


def parse_f6(path):
    """Recommendations, CNHI decisions and corrective actions. Provider names are kept only for approved decisions and
    never for investigation referrals (decision of 29 Oct 2026); otherwise they are discarded here and never stored."""
    wb = open_book(path)
    warn = []
    recs = sheet_rows(wb, warn, "Policy & recommendations", ["Recommendation ID", "Stage"], {
        "id": ("Recommendation ID", "t"), "title": ("Title", "t"), "type": ("Type", "t"),
        "document": ("Document or policy affected", "t"), "source_type": ("Source type", "t"), "source": ("Source reference", "t"),
        "root": ("Root cause", "t"), "stage": ("Stage", "t"), "proposed": ("Proposed date", "d"), "approved": ("Approved date", "d"),
        "issued": ("Issued or effective date", "d"), "owner": ("CNHI owner (unit)", "t")})
    raw_dec = sheet_rows(wb, warn, "Decisions", ["Decision ID", "Decision"], {
        "id": ("Decision ID", "t"), "submitted": ("Date submitted", "d"), "subject_type": ("Subject type", "t"),
        "subject": ("Subject name", "t"), "topic": ("Topic", "t"), "source": ("Source reference", "t"),
        "value": ("Value at stake (SAR)", "n"), "forum": ("Forum", "t"), "decision": ("Decision", "t"),
        "decided": ("Decision date", "d"), "minutes": ("Minutes reference", "t")})
    raw_act = sheet_rows(wb, warn, "Corrective actions", ["Action ID", "Target type"], {
        "id": ("Action ID", "t"), "decision_id": ("Decision ID", "t"), "target_type": ("Target type", "t"),
        "target": ("Target name", "t"), "tpa": ("TPA", "t"), "type": ("Action type", "t"), "code": ("Flag code", "t"),
        "source": ("Source reference", "t"), "opened": ("Opened date", "d"), "due": ("Due date", "d"),
        "completed": ("Completed date", "d"), "status": ("Status", "t"),
        "agreed": ("Value agreed for recovery (SAR)", "n"), "recovered": ("Value recovered (SAR)", "n"),
        "evidence": ("Evidence reference", "t"), "owner": ("Action owner (unit)", "t"), "updated": ("Last update date", "d"),
        "note": ("Status note (shown on dashboard)", "t")})
    withheld = 0
    decisions = []
    for d in raw_dec:
        d["decision"] = d["decision"] or "Pending"
        if norm(d["subject_type"]) == "tpa":
            d["subject"] = tpa_name(d["subject"])
        elif norm(d["subject_type"]) == "provider":
            ok = norm(d["decision"]) in APPROVED and norm(d["topic"]) != "investigation referral"
            if not ok and d["subject"]:
                withheld += 1
            d["subject"] = d["subject"] if ok else ""
        if d["decided"] and d["decision"] == "Pending":
            warn.append(f"Decision {d['id']}: has a decision date but the decision is Pending.")
        decisions.append(d)
    dmap = {d["id"]: d for d in decisions}
    actions = []
    for a in raw_act:
        dec = dmap.get(a["decision_id"])
        if a["decision_id"] and dec is None:
            warn.append(f"Action {a['id']}: Decision ID {a['decision_id']} is not in the Decisions sheet.")
        is_tpa = norm(a["target_type"]) == "tpa"
        a["target_type"] = "TPA" if is_tpa else "Provider"
        a["tpa"] = tpa_name(a["tpa"] or (a["target"] if is_tpa else ""))
        a["key"] = ""
        if is_tpa:
            a["target"] = tpa_name(a["target"])
        else:
            a["key"] = deid.ref(norm(a["target"])) if a["target"] else ""      # matches the provider in the daily register
            ok = (dec is not None and norm(dec["decision"]) in APPROVED and norm(a["type"]) != "referral for investigation"
                  and norm(a["status"]) != "cancelled")
            if not ok and a["target"]:
                withheld += 1
            a["target"] = a["target"] if ok else ""
        a["status"] = a["status"] or ("Completed" if a["completed"] else "Open")
        if norm(a["status"]) == "completed" and not a["completed"]:
            warn.append(f"Action {a['id']}: status Completed without a completed date; it is left out of on-time and effect KPIs.")
        if not a["due"] and norm(a["status"]) not in ("completed", "cancelled"):
            warn.append(f"Action {a['id']}: no due date, so it cannot be shown as overdue.")
        a["code"] = (a["code"] or "").upper()
        note = re.sub(r"\s+", " ", a.get("note") or "").strip()
        if re.search(r"\d{10}", note):                     # looks like a national ID or phone number: never stored
            warn.append(f"Action {a['id']}: the status note contains a 10-digit number and was not kept.")
            note = ""
        if len(note) > NOTE_MAX:
            warn.append(f"Action {a['id']}: status note shortened to {NOTE_MAX} characters.")
            note = note[:NOTE_MAX - 1] + "…"
        a["note"] = note
        if a["completed"] and not a.get("evidence"):
            warn.append(f"Action {a['id']}: completed without an evidence reference; shown as 'Completed - evidence pending'.")
        actions.append(a)
    summary = {"Recommendations": len(recs), "Decisions": len(decisions),
               "Corrective actions": len(actions),
               "on TPAs": sum(1 for a in actions if a["target_type"] == "TPA"),
               "on providers": sum(1 for a in actions if a["target_type"] == "Provider"),
               "Provider names withheld (not approved or investigation referral)": withheld}
    return dict(data=dict(recommendations=recs, decisions=decisions, actions=actions), summary=summary, warnings=warn)


PARSERS = {"F1": parse_f1, "F2": parse_f2, "F3": parse_f3, "F4": parse_f4, "F5": parse_f5, "F6": parse_f6}


def parse(kind, path, label=""):
    if kind == "F4":
        return parse_f4(path, label)
    return PARSERS[kind](path)
