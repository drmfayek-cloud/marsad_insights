"""End-to-end checks on synthetic data. Run: python -m unittest discover -s tests"""
import datetime as dt
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

from openpyxl import Workbook, load_workbook

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="insights-test-")
os.environ.update(MARSAD_DATA=TMP, MARSAD_DEMO="0", MARSAD_HTTPS="0", MARSAD_REQUIRE_MFA="0",
                  MARSAD_ADMIN_EMAIL="admin@test.local", MARSAD_ADMIN_PASSWORD="First!Pass2026x")

import app as A  # noqa: E402
from insights import auth, config, db, kpi, store  # noqa: E402

NEW_PW = "Changed!Pass2026x"


def tok(html):
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def daily_register():
    """A minimal workbook with the same sheets and headers as the MARSAD Daily Record & Action Tracker."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Daily Intake"
    ws.append(["Daily Intake"]); ws.append([]); ws.append([])
    ws.append(["Date received", "Received by", "Source", "TPA", "Volume received", "Reviewed", "Outstanding"])
    for d in range(1, 11):
        ws.append([dt.date(2026, 9, d), "Someone", "Approval", "GlobeMed", 100, 100, 0])
    ws.append([dt.date(2026, 10, 1), "Someone", "Approval", "Nextcare", 50, 40, 10])
    rl = wb.create_sheet("Daily Review Log")
    rl.append(["x"]); rl.append([]); rl.append([])
    rl.append(["Date", "Reviewer", "Source", "TPA", "Records reviewed", "Confirmed", "Suspected", "Flag rate %",
               "Declared total", "Logged in Daily Log"])
    rl.append([dt.date(2026, 9, 1), "Dr Example", "Approval", "GlobeMed", 100, 3, 0, 0.03, 3, 3])
    dl = wb.create_sheet("Daily Log")
    dl.append(["Daily Log"]); dl.append([]); dl.append([])
    dl.append(["Log ID", "Date logged", "Reviewer", "Source", "Reference no.", "TPA", "Provider", "Flag code", "Flag type",
               "Flag description", "Flag status", "Severity", "Action level", "Amount at risk (SAR)", "Owner", "Owner type",
               "Due date", "Status", "Date closed", "Resolution / outcome", "Sent to CNHI on", "CNHI response"])
    rows = [("MRS-1", 2, "R1", "H1", "EMG-01", "Confirmed", 10000), ("MRS-2", 2, "R1", "H1", "DQ-10", "Confirmed", 4000),
            ("MRS-3", 3, "R2", "H2", "DQ-10", "Confirmed", 7000), ("MRS-4", 4, "R3", "H2", "BEN-02", "Cleared on review", 500)]
    for lid, day, ref, prov, code, st, amt in rows:
        dl.append([lid, dt.date(2026, 9, day), "Dr Example", "Approval", ref, "GlobeMed", prov, code, "t",
                   "Patient narrative must never be read", st, "High", "TPA level", amt, "Named owner", "CNHI Approvals",
                   dt.date(2026, 9, 20), "Open", None, "free text", None, None])
    cf = wb.create_sheet("Config")
    cf.append(["Configuration"]); cf.append([]); cf.append([])
    cf.append(["Flag code", "Flag type (English)", "نوع الملاحظة"])
    for code in ("EMG-01", "DQ-10", "BEN-02"):
        cf.append([code, "type", "نوع"])
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = A.app.test_client()
        r = cls.c.get("/login")
        r = cls.c.post("/login", data=dict(csrf=tok(r.text), email="admin@test.local", password="First!Pass2026x"))
        assert r.status_code == 302, r.status_code
        r = cls.c.get("/account")
        r = cls.c.post("/account", data=dict(csrf=tok(r.text), current="First!Pass2026x", new=NEW_PW, repeat=NEW_PW))
        assert r.status_code == 302

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def upload(self, kind, content, name, label=""):
        r = self.c.get("/data")
        r = self.c.post("/data", data=dict(csrf=tok(r.text), kind=kind, label=label, file=(io.BytesIO(content), name)),
                        content_type="multipart/form-data")
        return r

    def publish(self, loc):
        r = self.c.get(loc)
        return self.c.post(loc, data=dict(csrf=tok(r.text), act="publish"))

    # ---------------------------------------------------------------- tests
    def test_01_totp(self):
        s = auth.new_mfa_secret()
        self.assertTrue(auth.check_totp(s, auth.totp(s)))
        self.assertFalse(auth.check_totp(s, "000000" if auth.totp(s) != "000000" else "111111"))

    def test_02_csrf_required(self):
        r = self.c.post("/data", data=dict(kind="F1"))
        self.assertEqual(r.status_code, 400)

    def test_03_bad_file_rejected(self):
        r = self.upload("F1", b"not a workbook", "x.xlsx")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(db.val("SELECT COUNT(*) FROM uploads", default=0), 0)

    def test_04_daily_register_upload_and_kpis(self):
        r = self.upload("F1", daily_register(), "daily.xlsm")
        loc = r.headers["Location"]
        self.assertIn("/data/", loc)
        page = self.c.get(loc).text
        self.assertIn("Flags", page)
        self.publish(loc)
        data = store.current()
        flags = data["F1"]["flags"]
        # patient narrative, owner names and staff names are never stored
        blob = repr(data)
        self.assertNotIn("Patient narrative", blob)
        self.assertNotIn("Dr Example", blob)
        self.assertNotIn("Named owner", blob)
        self.assertNotEqual(flags[0]["ref"], "R1")                     # references are hashed
        self.assertEqual(data["F1"]["intake"][-1]["tpa"], "NextCare")   # TPA names normalised
        with A.app.test_request_context():
            from flask import g
            g.lang = "en"
            c = kpi.Ctx(data, "2026-09", "")
            self.assertEqual(kpi.compute("EX-01", c)["raw"], 1000)
            self.assertAlmostEqual(kpi.compute("EX-03", c)["raw"], 2 / 1000)      # 2 encounters (R1, R2) confirmed
            self.assertEqual(kpi.compute("EX-04", c)["raw"], 17000)               # R1 counted once at 10,000 (D-19)
            self.assertAlmostEqual(kpi.compute("FW-02", c)["raw"], 3 / 4)
            self.assertEqual(kpi.compute("EX-06", c)["state"], "nodata")          # column not present (D-09)
            c10 = kpi.Ctx(data, "2026-10", "")
            self.assertEqual(kpi.compute("DR-02", c10)["raw"], 10)
            self.assertAlmostEqual(kpi.compute("EX-02", c10)["raw"], 0.8)

    def test_05_disputes_template_upload(self):
        wb = load_workbook(os.path.join(ROOT, "static", "downloads", "CNHI_Hospital_Disputes_Tracker_v1.0.xlsx"))

        def put(ws, row, values):                                   # columns found by header text (row 4)
            cols = {c.value: c.column_letter for c in ws[4] if c.value}
            for k, v in values.items():
                ws[f"{cols[k]}{row}"] = v
        put(wb["Batches"], 5, {"Batch ID": "B01", "Hospital": "H1", "Received date": dt.date(2026, 9, 3),
                               "KPMG opinion date": dt.date(2026, 9, 6)})
        base = {"Batch ID": "B01", "Hospital": "H1", "Pathway": "Claim", "Dispute theme": "Coding or billing"}
        put(wb["Disputes"], 5, dict(base, **{"Dispute ID": "DSP-H1-001", "Claimed amount (SAR)": 10000,
                                             "Approved amount (SAR)": 0, "KPMG position": "Partially accepted",
                                             "Value to pay (SAR) - partial only": 6000}))
        put(wb["Disputes"], 6, dict(base, **{"Dispute ID": "DSP-H1-002", "KPMG position": "Not accepted"}))
        put(wb["Disputes"], 7, dict(base, **{"Dispute ID": "DSP-H1-003", "KPMG position": "Pending"}))
        put(wb["Actions"], 6, {"Action ID": "A-0001", "Date": dt.date(2026, 9, 3), "Dispute ID": "DSP-H1-001",
                               "Action type": "Clinical review", "Team member": "Someone", "Hours": 2.5,
                               "Estimated? (backfilled)": "Yes"})
        bio = io.BytesIO()
        wb.save(bio)                                                # saved without recalculation: the parser derives
        r = self.upload("F3", bio.getvalue(), "disputes.xlsx")
        self.publish(r.headers["Location"])
        data = store.current()
        self.assertEqual(len(data["F3"]["disputes"]), 3)                     # example action row ignored
        first = data["F3"]["disputes"][0]
        self.assertEqual((first["received"], first["value"], first["maintained"]), ("2026-09-03", 10000, 4000))
        self.assertIsNone(data["F3"]["disputes"][2]["closed"])                  # pending keeps no opinion date
        with A.app.test_request_context():
            from flask import g
            g.lang = "en"
            c = kpi.Ctx(data, "2026-09", "")
            self.assertEqual(kpi.compute("EX-07", c)["raw"], 2)
            self.assertAlmostEqual(kpi.compute("EX-08", c)["raw"], 0.5)
            self.assertEqual(kpi.compute("HD-05", c)["raw"], 4000)
            self.assertEqual(kpi.compute("HD-07", c)["raw"], 2.5)
            self.assertEqual(kpi.compute("HD-06", c)["raw"], 1)               # Thu 3 Sep -> Sun 6 Sep: Fri and Sat excluded

    def test_06_governance_template_round_trip(self):
        r = self.c.get("/data/template/governance.xlsx")
        self.assertEqual(r.status_code, 200)
        wb = load_workbook(io.BytesIO(r.data))
        ws = wb["Deliverables"]
        ws["A6"], ws["B6"], ws["C6"], ws["E6"] = "Monthly review report", "Aug-2026", dt.date(2026, 9, 10), dt.date(2026, 9, 9)
        te = wb["Team effort"]
        for i, (w, role, days) in enumerate([("MARSAD daily review (approvals and claims)", "Physician", 44),
                                             ("Hospital disputes", "Physician", 22), ("Financial and accounting review", "Finance consultant", 22),
                                             ("Reporting and governance", "Additional KPMG support", 5)], start=6):
            te[f"A{i}"], te[f"B{i}"], te[f"C{i}"], te[f"D{i}"] = w, role, "Sep-2026", days
        rq = wb["CNHI requests"]
        rq["A6"], rq["B6"], rq["C6"], rq["D6"], rq["F6"], rq["G6"] = "Q1", dt.date(2026, 9, 1), "CNHI Finance", "Case review", dt.date(2026, 9, 3), 5
        wb["Contract"]["B5"] = dt.date(2025, 10, 1)
        bio = io.BytesIO()
        wb.save(bio)
        r = self.upload("F5", bio.getvalue(), "gov.xlsx")
        self.publish(r.headers["Location"])
        with A.app.test_request_context():
            from flask import g
            g.lang = "en"
            c = kpi.Ctx(store.current(), "2026-09", "")
            self.assertEqual(kpi.compute("EX-10", c)["raw"], 1.0)
            self.assertEqual(kpi.compute("OP-03", c)["raw"], 93)                 # example row ignored, month typed as text
            self.assertAlmostEqual(kpi.compute("OP-04", c)["raw"], 66 / 88)      # reporting left out of the mix
            self.assertEqual(kpi.compute("OP-05", c)["raw"], 27)                 # disputes 22 + additional support 5
            self.assertEqual(kpi.compute("OP-06", c)["raw"], 1)
            self.assertEqual(kpi.compute("OP-07", c)["value"], "Month 12 of 24")
            self.assertAlmostEqual(kpi.compute("OP-08", c)["raw"], (66 + 22) / 22 / 4)   # 22 working days in Sep 2026 (Sun-Thu)
        # a CNHI viewer sees the page without the KPMG-only tiles
        db.insert("users", email="viewer@test.local", name="CNHI viewer", role="cnhi", pw_hash=auth.hash_pw(NEW_PW), must_change_pw=0)
        c2 = A.app.test_client()
        r = c2.get("/login")
        c2.post("/login", data=dict(csrf=tok(r.text), email="viewer@test.local", password=NEW_PW))
        page = c2.get("/p/delivery?period=2026-09").text
        self.assertIn("OP-05", page)
        self.assertNotIn("OP-08", page)
        self.assertIn("OP-08", self.c.get("/p/delivery?period=2026-09").text)

    def test_07_every_page_both_languages(self):
        for lg in ("en", "ar"):
            self.c.get(f"/lang/{lg}")
            for p in config.PAGES:
                r = self.c.get(f"/p/{p['slug']}?period=2026-09")
                self.assertEqual(r.status_code, 200, p["slug"])
                self.assertNotIn("Could not compute", r.text, p["slug"])
        self.c.get("/lang/en")

    def test_08_period_close_freezes_figures(self):
        r = self.c.get("/periods")
        self.c.post("/periods", data=dict(csrf=tok(r.text), month="2026-09", act="close", note="test"))
        self.assertIsNotNone(db.q1("SELECT * FROM snapshots WHERE month='2026-09'"))
        r = self.c.get("/p/executive?period=2026-09")
        self.assertIn("badge ok", r.text)
        r = self.c.get("/periods")
        self.c.post("/periods", data=dict(csrf=tok(r.text), month="2026-09", act="reopen"))
        self.assertIsNone(db.q1("SELECT * FROM snapshots WHERE month='2026-09'"))

    def test_09_cnhi_viewer_cannot_administer(self):
        r = self.c.get("/admin/users")
        r = self.c.post("/admin/users", data=dict(csrf=tok(r.text), act="add", email="cfo@test.local", name="CFO", role="cnhi"))
        temp = re.search(r"Temporary password: (\S+)", r.text if r.status_code == 200 else self.c.get("/admin/users").text)
        self.assertIsNotNone(temp)
        other = A.app.test_client()
        r = other.get("/login")
        r = other.post("/login", data=dict(csrf=tok(r.text), email="cfo@test.local", password=temp.group(1)))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(other.get("/data").status_code, 302)               # must change password first
        r = other.get("/account")
        other.post("/account", data=dict(csrf=tok(r.text), current=temp.group(1), new="Cfo!Pass2026xyz", repeat="Cfo!Pass2026xyz"))
        self.assertEqual(other.get("/data").status_code, 403)
        self.assertEqual(other.get("/p/executive").status_code, 200)

    def test_11_mfa_setup_with_qr_code(self):
        db.insert("users", email="mfa@test.local", name="MFA user", role="kpmg", pw_hash=auth.hash_pw(NEW_PW), must_change_pw=0)
        A.app.config["REQUIRE_MFA"] = True
        try:
            c = A.app.test_client()
            c.get("/lang/ar")
            r = c.get("/login")
            r = c.post("/login", data=dict(csrf=tok(r.text), email="mfa@test.local", password=NEW_PW))
            self.assertIn("/mfa/setup", r.headers["Location"])
            page = c.get("/mfa/setup").text
            uri = re.search(r'href="(otpauth://totp/[^"]+)"', page).group(1).replace("&amp;", "&")
            self.assertIn("issuer=MARSAD%20Insights", uri)
            try:
                import segno  # noqa: F401
                self.assertIn('class="qr"', page)                                   # QR code drawn on the page
                self.assertIn('viewBox="', page)
            except ImportError:
                self.assertIn('class="secret"', page)                              # falls back to the typed key
            secret = re.search(r"secret=([A-Z2-7]+)", uri).group(1)
            r = c.post("/mfa/setup", data=dict(csrf=tok(page), code=auth.totp(secret)))
            self.assertEqual(r.status_code, 302)
            self.assertIn("/p/executive", r.headers["Location"])
            self.assertIn('lang="ar"', c.get("/p/executive").text)                    # language chosen before sign-in kept
            self.assertEqual(db.q1("SELECT mfa_enabled FROM users WHERE email='mfa@test.local'")["mfa_enabled"], 1)
        finally:
            A.app.config["REQUIRE_MFA"] = False

    def test_12_governance_corrective_actions_register(self):
        r = self.c.get("/data/template/corrective-actions.xlsx")
        self.assertEqual(r.status_code, 200)
        wb = load_workbook(io.BytesIO(r.data))

        def put(ws, row, values):
            cols = {c.value: c.column_letter for c in ws[4] if c.value}
            for k, v in values.items():
                ws[f"{cols[k]}{row}"] = v
        put(wb["Policy & recommendations"], 6, {"Recommendation ID": "R1", "Type": "Policy or manual change", "Stage": "Issued",
                                                "Proposed date": dt.date(2026, 8, 1), "Approved date": dt.date(2026, 8, 21),
                                                "Issued or effective date": dt.date(2026, 9, 10)})
        dec = wb["Decisions"]
        put(dec, 6, {"Decision ID": "D1", "Date submitted": dt.date(2026, 9, 1), "Subject type": "TPA", "Subject name": "globemed",
                     "Topic": "Recovery", "Decision": "Approved", "Decision date": dt.date(2026, 9, 8)})
        put(dec, 7, {"Decision ID": "D2", "Date submitted": dt.date(2026, 9, 2), "Subject type": "Provider",
                     "Subject name": "Hospital Approved", "Topic": "Recovery", "Decision": "Approved", "Decision date": dt.date(2026, 9, 9)})
        put(dec, 8, {"Decision ID": "D3", "Date submitted": dt.date(2026, 9, 3), "Subject type": "Provider",
                     "Subject name": "Hospital Pending", "Topic": "Contract action", "Decision": "Pending"})
        act = wb["Corrective actions"]
        rows = [("A1", "D1", "TPA", "globemed", "Recover overpayment", dt.date(2026, 9, 9), dt.date(2026, 9, 20), None, 1000, 400),
                ("A2", "D2", "Provider", "Hospital Approved", "Recover overpayment", dt.date(2026, 9, 10), dt.date(2026, 10, 30),
                 dt.date(2026, 9, 25), 500, 500),
                ("A3", "D2", "Provider", "Hospital Referred", "Referral for investigation", dt.date(2026, 9, 10), dt.date(2026, 10, 30), None, 0, 0),
                ("A4", "D3", "Provider", "Hospital Pending", "Contract review", dt.date(2026, 9, 12), dt.date(2026, 10, 30), None, 0, 0)]
        for i, (aid, did, tt, name, typ, o, due, comp, ag, rc) in enumerate(rows, start=6):
            put(act, i, {"Action ID": aid, "Decision ID": did, "Target type": tt, "Target name": name, "Action type": typ,
                         "Opened date": o, "Due date": due, "Completed date": comp, "Value agreed for recovery (SAR)": ag,
                         "Value recovered (SAR)": rc, "Status": "Completed" if comp else "Open"})
        bio = io.BytesIO()
        wb.save(bio)
        r = self.upload("F6", bio.getvalue(), "f6.xlsx")
        self.assertIn("Provider names withheld", self.c.get(r.headers["Location"]).text)
        self.publish(r.headers["Location"])
        data = store.current()
        stored = json.dumps(data["F6"])
        self.assertIn("Hospital Approved", stored)
        self.assertNotIn("Hospital Referred", stored)                            # referral: never named
        self.assertNotIn("Hospital Pending", stored)                             # decision not approved: not named
        with A.app.test_request_context():
            from flask import g
            g.lang = "en"
            c = kpi.Ctx(data, "2026-09", "", today="2026-10-29")
            self.assertEqual(kpi.compute("GC-04", c)["raw"], 1)
            self.assertIn("1 overdue", kpi.compute("GC-04", c)["sub"])           # due 20 Sep, still open at 30 Sep
            self.assertEqual(kpi.compute("GC-04", c)["table"]["rows"][0][0], "GlobeMed Saudi")   # TPA name normalised
            g6 = kpi.compute("GC-06", c)
            self.assertIn("1 referral for investigation", g6["sub"])
            names = [row[0] for row in g6["table"]["rows"]]
            self.assertIn("Hospital Approved", names)
            self.assertTrue(any(n.startswith("Not named") for n in names))
            self.assertEqual(kpi.compute("GC-07", c)["raw"], 900)
            self.assertEqual(kpi.compute("GC-03", c)["raw"], 2)
            self.assertEqual(kpi.compute("GC-02", c)["raw"], None)               # approved in August, not September
            self.assertEqual(kpi.compute("GC-01", c)["raw"], 1)
            self.assertEqual(kpi.compute("EX-11", c)["raw"], 3)
            self.assertIn("1 implemented", kpi.compute("FW-08", c)["sub"])       # FW-08 now reads F6
        self.assertIn("GC-06", self.c.get("/p/governance?period=2026-09").text)

    def test_13_action_status_tracker_and_candidates(self):
        from insights import actions, candidates
        base = dict(status="Open", opened="2026-10-01", due="2026-10-20", completed=None, evidence="")
        S = actions.status
        self.assertEqual(S(dict(base, opened=None), "2026-10-10"), "not_started")
        self.assertEqual(S(base, "2026-10-12"), "on_track")                     # 8 days to due
        self.assertEqual(S(base, "2026-10-13"), "due_soon")                     # 7 days to due
        self.assertEqual(S(base, "2026-10-21"), "overdue")
        self.assertEqual(S(dict(base, completed="2026-10-18"), "2026-10-21"), "done_pending")
        self.assertEqual(S(dict(base, completed="2026-10-18", evidence="L-1"), "2026-10-21"), "done_verified")
        self.assertEqual(S(dict(base, completed="2026-10-25"), "2026-10-21"), "overdue")   # completed after the as-at date
        self.assertEqual(S(dict(base, status="Cancelled"), "2026-10-21"), "cancelled")
        # status note: a 10-digit number is never stored
        wb = load_workbook(io.BytesIO(self.c.get("/data/template/corrective-actions.xlsx").data))
        ws = wb["Corrective actions"]
        cols = {c.value: c.column_letter for c in ws[4] if c.value}
        for k, v in {"Action ID": "N1", "Target type": "TPA", "Target name": "NextCare", "Action type": "Formal notice",
                     "Opened date": dt.date(2026, 9, 1), "Due date": dt.date(2026, 9, 10),
                     "Status note (shown on dashboard)": "Called 1012345678 about the reply",
                     "Source reference": "F1:NextCare:DQ-10:2026-09"}.items():
            ws[f"{cols[k]}6"] = v
        bio = io.BytesIO()
        wb.save(bio)
        r = self.upload("F6", bio.getvalue(), "f6b.xlsx")
        self.assertIn("10-digit number", self.c.get(r.headers["Location"]).text)
        self.publish(r.headers["Location"])
        self.assertNotIn("1012345678", json.dumps(store.current()["F6"]))
        # tracker, detail and download for a CNHI viewer
        c2 = A.app.test_client()
        r = c2.get("/login")
        c2.post("/login", data=dict(csrf=tok(r.text), email="viewer@test.local", password=NEW_PW))
        page = c2.get("/p/governance/actions?status=overdue").text
        self.assertIn("N1", page)
        self.assertIn("Overdue", page)
        self.assertEqual(c2.get("/p/governance/actions/N1").status_code, 200)
        x = c2.get("/p/governance/actions.xlsx")
        self.assertEqual(x.status_code, 200)
        xs = load_workbook(io.BytesIO(x.data))["Action tracker"]
        self.assertEqual(xs["B7"].value, "N1")
        self.assertEqual(xs["A7"].value, "Overdue")
        self.assertTrue(db.q1("SELECT 1 AS x FROM audit WHERE action='download_actions'"))
        # changes since the previous version: A1-A4 of test 12 are gone, N1 is new
        self.assertIn("New since last upload", page)
        # candidates: administrators only; a key already in F6 is not offered again
        self.assertEqual(c2.get("/data/candidates.xlsx").status_code, 403)
        self.assertEqual(self.c.get("/data/candidates.xlsx").status_code, 200)
        fl = [dict(status="Confirmed", tpa="NextCare", code="DQ-10", date="2026-09-0%d" % i, action="TPA level", cnhi_response="",
                   ref=f"R{i}", log_id=f"L{i}", amount=60000) for i in range(1, 4)]
        fl.append(dict(fl[0], code="EMG-01", amount=5000, ref="R9"))                          # below SAR 100,000
        fl.append(dict(fl[0], code="BEN-02", cnhi_response="Endorse - route to TPA", ref="R8"))
        dec, act, _ = candidates.build({"F1": {"flags": fl}})
        self.assertEqual([r["Source reference"] for r in dec], ["F1:NextCare:DQ-10:2026-09"])   # grouped, 3 encounters
        self.assertEqual(dec[0]["Value at stake (SAR)"], 180000)
        self.assertEqual([r["Source reference"] for r in act], ["F1E:NextCare:BEN-02:2026-09"])
        dec, act, skipped = candidates.build({"F1": {"flags": fl}, "F6": store.current()["F6"]})
        self.assertEqual((dec, skipped), ([], 1))                                    # key already in F6: not offered
        # stale register: EX-11 warns
        db.ex("UPDATE uploads SET published_at='2026-01-01 08:00:00' WHERE id=?", (store.current_ids()["F6"],))
        with A.app.test_request_context():
            from flask import g
            g.lang = "en"
            ctx = kpi.Ctx(store.current(), "2026-09", "")
            ctx.meta = {"F6": actions.meta()}
            self.assertEqual(kpi.compute("EX-11", ctx)["state"], "partial")
            self.assertIn("last uploaded", kpi.compute("GC-09", ctx)["note"])
        self.assertIn("days ago", c2.get("/p/governance/actions").text)

    def test_14_documents_library(self):
        from insights import library, samplefiles
        from openpyxl import Workbook as WB

        def up(client, name, raw, **meta):
            r = client.get("/documents/upload")
            fields = dict(dict(csrf=tok(r.text), category="other", visibility="kpmg", title=""), **meta)
            fields["file"] = (io.BytesIO(raw), name)
            return client.post("/documents/upload", data=fields, content_type="multipart/form-data")

        # type checks: content must match the extension; legacy formats refused
        r = up(self.c, "report.pdf", b"MZ\x90\x00 not a pdf")
        self.assertIn("does not match its type", r.text)
        self.assertIn("save the file as .docx", up(self.c, "old.doc", b"\xd0\xcf\x11\xe0").text.lower())
        self.assertIn("Upload a PDF", up(self.c, "tool.exe", b"MZ").text)
        # patient identifiers: refused without confirmation, accepted with it (and audited)
        bad = samplefiles.docx(["Patient name: Example", "National ID 1098765432"])
        self.assertIn("patient identifiers", up(self.c, "ids.docx", bad).text)
        r = up(self.c, "ids.docx", bad, confirm="1")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(db.q1("SELECT 1 AS x FROM audit WHERE action='document_uploaded' AND detail LIKE '%confirmed no patient%'"))
        wbk = WB()
        wbk.active.append(["Claim", 2012345678])                          # an iqama-format number stored as a number
        bio = io.BytesIO()
        wbk.save(bio)
        self.assertIn("patient identifiers", up(self.c, "list.xlsx", bio.getvalue()).text)
        # a clean shared PDF linked to an action, and a KPMG-only Word file
        r = up(self.c, "Deduction letter.pdf", samplefiles.pdf(["Deduction confirmed for action N1", "Reference CNHI-L-900"]),
               category="evidence", visibility="shared", title="Deduction letter N1", link_action="N1")
        shared_id = int(r.headers["Location"].rsplit("/", 1)[1])
        r = up(self.c, "note.docx", samplefiles.docx(["Internal working note on N1"]), visibility="kpmg", title="Working note",
               link_action="N1")
        kpmg_id = int(r.headers["Location"].rsplit("/", 1)[1])
        self.assertTrue(os.path.exists(library.path(db.q1("SELECT * FROM documents WHERE id=?", (shared_id,)))))
        # search reads the file text
        self.assertIn("Deduction letter N1", self.c.get("/documents?q=CNHI-L-900").text)
        # CNHI viewer: sees and downloads only shared documents, cannot upload
        c2 = A.app.test_client()
        r = c2.get("/login")
        c2.post("/login", data=dict(csrf=tok(r.text), email="viewer@test.local", password=NEW_PW))
        lst = c2.get("/documents").text
        self.assertIn("Deduction letter N1", lst)
        self.assertNotIn("Working note", lst)
        self.assertEqual(c2.get(f"/documents/{kpmg_id}").status_code, 404)
        self.assertEqual(c2.get(f"/documents/{kpmg_id}/download").status_code, 404)
        dl = c2.get(f"/documents/{shared_id}/download")
        self.assertEqual(dl.status_code, 200)
        self.assertTrue(dl.data.startswith(b"%PDF-"))
        self.assertIn("attachment", dl.headers["Content-Disposition"])
        self.assertEqual(c2.get("/documents/upload").status_code, 403)
        detail = c2.get("/p/governance/actions/N1").text
        self.assertIn("Deduction letter N1", detail)                          # linked evidence on the action page
        self.assertNotIn("Working note", detail)
        self.assertIn("📎 1", c2.get("/p/governance/actions").text)            # one visible document for N1
        # new version supersedes the old one
        r = self.c.get(f"/documents/upload?parent={shared_id}")
        r = self.c.post("/documents/upload", data=dict(csrf=tok(r.text), parent=shared_id, category="evidence", visibility="shared",
                                                       title="Deduction letter N1", link_action="N1",
                                                       file=(io.BytesIO(samplefiles.pdf(["Deduction confirmed, version 2"])), "v2.pdf")),
                        content_type="multipart/form-data")
        new_id = int(r.headers["Location"].rsplit("/", 1)[1])
        self.assertEqual(db.q1("SELECT status FROM documents WHERE id=?", (shared_id,))["status"], "superseded")
        self.assertNotIn(f"/documents/{shared_id}\"", self.c.get("/documents").text)   # list shows the current version only
        self.assertIn("Earlier version", self.c.get(f"/documents/{shared_id}").text)
        # delete: administrators only, file removed
        r = self.c.get(f"/documents/{new_id}")
        self.c.post(f"/documents/{new_id}", data=dict(csrf=tok(r.text), act="delete"))
        self.assertEqual(db.q1("SELECT status FROM documents WHERE id=?", (new_id,))["status"], "deleted")
        self.assertFalse(os.path.exists(library.path(db.q1("SELECT * FROM documents WHERE id=?", (new_id,)))))
        self.assertEqual(self.c.get(f"/documents/{new_id}/download").status_code, 404)

    def test_10_lockout_after_failed_logins(self):
        other = A.app.test_client()
        for _ in range(auth.MAX_FAILED):
            r = other.get("/login")
            other.post("/login", data=dict(csrf=tok(r.text), email="cfo@test.local", password="wrong"))
        r = other.get("/login")
        r = other.post("/login", data=dict(csrf=tok(r.text), email="cfo@test.local", password="Cfo!Pass2026xyz"))
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
