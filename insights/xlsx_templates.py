"""Builds the governance register template (F5) offered for download on the Data uploads page."""
import datetime as dt
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

F, NAVY = "Arial", "00338D"
thin = Side(style="thin", color="C8CED9")
B = Border(left=thin, right=thin, top=thin, bottom=thin)

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
    "Recommendations": (["Recommendation ID", "Title", "Root cause", "Owner", "Raised date", "Status", "Accepted date",
                         "Implemented date"], [16, 40, 24, 20, 13, 14, 13, 15],
                        ["EXAMPLE-R01", "Require bed-charge line on inpatient GSS claims", "TPA adjudication", "CNHI Claims",
                         dt.date(2026, 10, 1), "Raised", None, None],
                        {"F": ["Raised", "Accepted", "Implemented", "Rejected"]}),
    "Knowledge transfer": (["Item", "Type", "Planned date", "Delivered date", "Audience"], [40, 16, 13, 14, 24],
                           ["EXAMPLE Review methodology walkthrough", "Session", dt.date(2026, 11, 15), None, "CNHI PFPS team"],
                           {"B": ["Session", "Document", "Tool handover"]}),
}


def governance_template():
    wb = Workbook()
    gd = wb.active
    gd.title = "Guide"
    gd.column_dimensions["A"].width = 110
    lines = [
        ("Governance register - MARSAD Insights (F5)", True),
        ("Keep this file up to date and upload it under Data uploads. It feeds EX-10, GV-01 to GV-06 and FW-08.", False),
        ("Row 5 of each sheet is an example (its first cell starts with EXAMPLE): it is ignored on upload; replace it.", False),
        ("Deliverables: one row per deliverable and period. A deliverable is on time when Submitted date <= Due date.", False),
        ("Meetings: one row per planned meeting; enter the Held date when it takes place.", False),
        ("Recommendations: process-improvement recommendations to CNHI and their status.", False),
        ("Knowledge transfer: sessions and documents planned for CNHI, with delivery dates.", False),
        ("Dates: enter real Excel dates. Do not insert rows above the header row (row 4).", False),
    ]
    for i, (txt, bold) in enumerate(lines, start=1):
        c = gd.cell(row=i, column=1, value=txt)
        c.font = Font(name=F, size=14 if bold else 10, bold=bold, color=NAVY if bold else None)
        c.alignment = Alignment(wrap_text=True)
    for name, (cols, widths, example, lists) in SHEETS.items():
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
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()
