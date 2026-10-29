"""Builds the register templates offered on the Data uploads page: F5 project delivery register and F6 governance &
corrective-action register."""
import datetime as dt
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

F, NAVY = "Arial", "00338D"
thin = Side(style="thin", color="C8CED9")
B = Border(left=thin, right=thin, top=thin, bottom=thin)

WORKSTREAMS = ["MARSAD daily review (approvals and claims)", "GSS claims assurance", "Hospital disputes",
               "Financial and accounting review", "Reporting and governance", "CNHI ad-hoc requests"]
ROLES = ["Physician", "Finance consultant", "Additional KPMG support"]
REQUEST_TYPES = ["Data extract or analysis", "Case review", "Report or presentation", "Meeting or workshop", "Other"]

SHEETS = {
    "Deliverables": (["Deliverable type", "Period", "Due date", "QA sign-off date", "Submitted date", "CNHI approval date", "Reference"],
                     [22, 14, 13, 14, 13, 15, 24],
                     ["EXAMPLE Monthly review report", "Sep-2026", dt.date(2026, 10, 10), dt.date(2026, 10, 8),
                      dt.date(2026, 10, 9), dt.date(2026, 10, 20), "MRR-2026-09"],
                     {"A": ["Monthly review report", "Quarterly financial report", "Annual consolidated report",
                            "GSS assurance report"]}),
    "Meetings": (["Meeting type", "Planned date", "Held date", "Note"], [26, 13, 13, 40],
                 ["EXAMPLE Weekly project meeting", dt.date(2026, 10, 5), dt.date(2026, 10, 5), ""],
                 {"A": ["Weekly project meeting", "Monthly management review", "Daily coordination"]}),
    "Knowledge transfer": (["Item", "Type", "Planned date", "Delivered date", "Audience"], [40, 16, 13, 14, 24],
                           ["EXAMPLE Review methodology walkthrough", "Session", dt.date(2026, 11, 15), None, "CNHI PFPS team"],
                           {"B": ["Session", "Document", "Tool handover"]}),
    "Team effort": (["Workstream", "Role", "Month", "Person-days", "Note"], [44, 26, 13, 13, 40],
                    ["EXAMPLE MARSAD daily review (approvals and claims)", "Physician", dt.date(2026, 10, 1), 40,
                     "One row per workstream and role each month"],
                    {"A": WORKSTREAMS, "B": ROLES}),
    "CNHI requests": (["Request ID", "Date received", "Requesting unit", "Request type", "Due date", "Delivered date",
                       "Hours", "Status", "Note"], [14, 14, 26, 26, 13, 14, 9, 13, 40],
                      ["EXAMPLE-Q01", dt.date(2026, 10, 5), "CNHI Finance", "Data extract or analysis", dt.date(2026, 10, 8),
                       dt.date(2026, 10, 7), 6, "Delivered", "Unit names only, no personal names"],
                      {"D": REQUEST_TYPES, "H": ["Open", "Delivered", "Cancelled"]}),
}

# Contract baseline (sheet 'Contract'): item -> (default, note)
CONTRACT = [
    ("Contract start date", None, "First day of the 24-month engagement. Needed for contract-to-date totals and month n of 24."),
    ("Contract duration (months)", 24, ""),
    ("Physicians (FTE)", 3, "Contracted physician reviewers: pre-authorizations and claims"),
    ("Finance consultants (FTE)", 1, "Contracted finance consultant: financial and accounting review"),
    ("Hours per person-day", 8, "Converts dispute and request hours into person-days"),
]


def governance_template():
    wb = Workbook()
    gd = wb.active
    gd.title = "Guide"
    gd.column_dimensions["A"].width = 110
    lines = [
        ("Project delivery register - MARSAD Insights (F5)", True),
        ("Keep this file up to date and upload it under Data uploads. It feeds EX-10 and the 'KPMG delivery & effort' page (OP-01 to OP-09, GV-01 to GV-06).", False),
        ("Row 5 of each sheet is an example (its first cell starts with EXAMPLE): it is ignored on upload; replace it.", False),
        ("Deliverables: one row per deliverable and period. A deliverable is on time when Submitted date <= Due date.", False),
        ("Meetings: one row per planned meeting; enter the Held date when it takes place.", False),
        ("Recommendations to CNHI now live in the governance & corrective-action register (F6).", False),
        ("Knowledge transfer: sessions and documents planned for CNHI, with delivery dates.", False),
        ("Team effort: each month, the person-days spent per workstream and role (monthly totals, no timesheets). "
         "'Additional KPMG support' is effort from outside the contracted team (management, QA, specialists).", False),
        ("CNHI requests: ad-hoc requests from CNHI outside the routine deliverables. Record the requesting unit, never a person's name. "
         "The Note column is not read by the dashboard.", False),
        ("Contract: the contract baseline (start date, duration, contracted team). Enter the start date once.", False),
        ("Dates: enter real Excel dates. Do not insert rows above the header row (row 4).", False),
    ]
    for i, (txt, bold) in enumerate(lines, start=1):
        c = gd.cell(row=i, column=1, value=txt)
        c.font = Font(name=F, size=14 if bold else 10, bold=bold, color=NAVY if bold else None)
        c.alignment = Alignment(wrap_text=True)
    _sheets(wb, SHEETS)
    ws = wb.create_sheet("Contract")
    ws["A1"] = "Contract"
    ws["A1"].font = Font(name=F, size=13, bold=True, color=NAVY)
    ws["A2"] = "Contract baseline used by the 'KPMG delivery & effort' page. Yellow = to complete."
    ws["A2"].font = Font(name=F, size=9, italic=True)
    for j, (h, w) in enumerate(zip(["Item", "Value", "Note"], [30, 16, 80]), start=1):
        c = ws.cell(row=4, column=j, value=h)
        c.font = Font(name=F, size=10, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=NAVY)
        c.border = B
        ws.column_dimensions[get_column_letter(j)].width = w
    for i, (item, val, note) in enumerate(CONTRACT, start=5):
        ws.cell(row=i, column=1, value=item).font = Font(name=F, size=10, bold=True)
        v = ws.cell(row=i, column=2, value=val)
        v.font = Font(name=F, size=10, color="0000FF")
        if "date" in item.lower():
            v.number_format = "dd-mmm-yyyy"
        if val is None:
            v.fill = PatternFill("solid", fgColor="FFF2CC")
        ws.cell(row=i, column=3, value=note).font = Font(name=F, size=9, italic=True)
        for j in (1, 2, 3):
            ws.cell(row=i, column=j).border = B
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()

# ------------------------------------------------------------------ F6 governance & corrective-action register
REC_TYPES = ["Policy or manual change", "Process improvement", "Contract or pricing change", "System or control"]
SOURCE_TYPES = ["Daily review flag", "GSS report", "Hospital dispute", "Financial review", "Trend analysis"]
STAGES = ["Proposed", "Under CNHI review", "Approved", "Issued", "Rejected", "Withdrawn"]
SUBJECTS = ["TPA", "Provider", "Policy", "Other"]
TOPICS = ["Recovery", "Corrective action plan", "Contract action", "Investigation referral", "Policy approval", "Other"]
FORUMS = ["Executive committee", "Monthly management review", "Weekly project meeting", "Correspondence"]
DECISIONS = ["Pending", "Approved", "Approved with changes", "Rejected", "Deferred"]
ACTION_TYPES = ["Reprocess claims", "Recover overpayment", "Formal notice", "Service-level penalty", "Process or system fix",
                "Corrective action plan", "Provider education", "Pre-authorization restriction", "Contract review",
                "Referral for investigation"]
ACTION_STATUS = ["Open", "In progress", "Completed", "Cancelled"]

F6_SHEETS = {
    "Policy & recommendations": (
        ["Recommendation ID", "Title", "Type", "Document or policy affected", "Source type", "Source reference", "Root cause",
         "Stage", "Proposed date", "Approved date", "Issued or effective date", "CNHI owner (unit)", "Note"],
        [16, 44, 24, 32, 18, 18, 22, 18, 13, 13, 15, 22, 36],
        ["EXAMPLE-R01", "Require a bed-charge line on inpatient claims", "Policy or manual change",
         "Claims Management Operational Manual", "GSS report", "GSS-07-26-014", "TPA adjudication", "Under CNHI review",
         dt.date(2026, 10, 1), None, None, "CNHI Claims", ""],
        {"C": REC_TYPES, "E": SOURCE_TYPES, "H": STAGES}),
    "Decisions": (
        ["Decision ID", "Date submitted", "Subject type", "Subject name", "Topic", "Source reference", "Value at stake (SAR)",
         "Forum", "Decision", "Decision date", "Minutes reference", "Note"],
        [14, 14, 13, 30, 22, 20, 16, 24, 20, 13, 18, 36],
        ["EXAMPLE-D01", dt.date(2026, 10, 5), "TPA", "GlobeMed Saudi", "Recovery", "Flag EMG-01, Sep-2026", 250000,
         "Monthly management review", "Approved", dt.date(2026, 10, 12), "MMR-2026-10", ""],
        {"C": SUBJECTS, "E": TOPICS, "H": FORUMS, "I": DECISIONS}),
    "Corrective actions": (
        ["Action ID", "Decision ID", "Target type", "Target name", "TPA", "Action type", "Flag code", "Source reference",
         "Opened date", "Due date", "Completed date", "Status", "Value agreed for recovery (SAR)", "Value recovered (SAR)",
         "Evidence reference", "Action owner (unit)", "Last update date", "Status note (shown on dashboard)", "Note"],
        [13, 13, 12, 30, 18, 26, 11, 24, 13, 13, 14, 13, 18, 16, 20, 22, 14, 44, 36],
        ["EXAMPLE-A01", "EXAMPLE-D01", "TPA", "GlobeMed Saudi", "GlobeMed Saudi", "Recover overpayment", "EMG-01",
         "F1:GlobeMed Saudi:EMG-01:2026-09", dt.date(2026, 10, 13), dt.date(2026, 11, 12), None, "Open", 250000, None, "",
         "GlobeMed claims unit", dt.date(2026, 10, 20), "Reprocessing list sent to the TPA; reply expected by 5 Nov", ""],
        {"C": ["TPA", "Provider"], "F": ACTION_TYPES, "L": ACTION_STATUS}),
}


def corrective_template():
    wb = Workbook()
    gd = wb.active
    gd.title = "Guide"
    gd.column_dimensions["A"].width = 120
    lines = [
        ("Governance & corrective-action register - MARSAD Insights (F6)", True),
        ("Tracks the loop from findings to change: recommendation or escalation -> CNHI decision -> corrective action on a TPA "
         "or provider, or a policy or manual change -> completed -> effect on later findings. Feeds the Governance page "
         "(GC-01 to GC-08), EX-11 and FW-08.", False),
        ("Maintained by KPMG from CNHI decision minutes and correspondence. Record the minutes reference for every decision.", False),
        ("Policy & recommendations: one row per recommendation to CNHI (policy, manual, contract or pricing, process, system). "
         "Move it through the stages and date each stage.", False),
        ("Decisions: one row per item submitted to CNHI for a decision, with the outcome and its date.", False),
        ("Corrective actions: one row per action on a TPA or a provider, linked to its Decision ID. Enter the Flag code when the "
         "action addresses a flag of the daily register: the dashboard then compares findings before and after the action.", False),
        ("Provider names: the dashboard keeps a provider's name only when the linked decision is Approved (or Approved with "
         "changes) and the action is not a referral for investigation. Otherwise the name is discarded at upload and the "
         "provider is counted without a name. TPA names are always shown.", False),
        ("Status is calculated by the dashboard from the dates, never typed: Not started (no opened date), On track, Due soon "
         "(due within 7 days), Overdue (past the due date), Completed - evidence pending (no evidence reference), Completed - "
         "verified, Cancelled. Use the Status column only for Cancelled; enter a Completed date only with evidence.", False),
        ("Evidence reference: the document that proves completion or recovery (letter number, payment-order or deduction "
         "reference). Value recovered only on evidence of a deduction, credit note or payment, never on a promise.", False),
        ("Status note: up to 200 characters, shown on the dashboard to CNHI and KPMG users. Write it as KPMG. Never include "
         "a person's name, a patient detail or an ID number: a note containing a 10-digit number is dropped at upload.", False),
        ("Source reference: when a row comes from the candidate list, keep its key (for example F1:GlobeMed Saudi:EMG-01:2026-09) "
         "so the candidate is not offered again.", False),
        ("Row 5 of each sheet is an example (first cell starts with EXAMPLE) and is ignored. Note columns are never read. "
         "Do not insert rows above the header row (row 4).", False),
    ]
    for i, (txt, bold) in enumerate(lines, start=1):
        c = gd.cell(row=i, column=1, value=txt)
        c.font = Font(name=F, size=14 if bold else 10, bold=bold, color=NAVY if bold else None)
        c.alignment = Alignment(wrap_text=True)
    _sheets(wb, F6_SHEETS)
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def _sheets(wb, sheets):
    """One sheet per entry: navy header on row 4, a grey example on row 5, 500 blue input rows, drop-down lists."""
    for name, (cols, widths, example, lists) in sheets.items():
        ws = wb.create_sheet(name)
        ws["A1"] = name
        ws["A1"].font = Font(name=F, size=13, bold=True, color=NAVY)
        ws["A2"] = "Blue text: you enter. Row 5 is an example."
        ws["A2"].font = Font(name=F, size=9, italic=True)
        for j, (h, w) in enumerate(zip(cols, widths), start=1):
            c = ws.cell(row=4, column=j, value=h)
            c.font = Font(name=F, size=10, bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor=NAVY)
            c.border = B
            ws.column_dimensions[get_column_letter(j)].width = w
        for j, v in enumerate(example, start=1):
            c = ws.cell(row=5, column=j, value=v)
            c.font = Font(name=F, size=10, italic=True, color="808080")
            if isinstance(v, dt.date):
                c.number_format = "dd-mmm-yyyy"
        for r in range(6, 506):
            for j, h in enumerate(cols, start=1):
                c = ws.cell(row=r, column=j)
                c.font = Font(name=F, size=10, color="0000FF")
                c.border = B
                if "date" in h.lower():
                    c.number_format = "dd-mmm-yyyy"
        for col, vals in lists.items():
            dv = DataValidation(type="list", formula1='"' + ",".join(vals) + '"', allow_blank=True)
            ws.add_data_validation(dv)
            dv.add(f"{col}5:{col}505")
        ws.freeze_panes = "A5"
