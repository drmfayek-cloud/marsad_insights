"""Synthetic demo data and demo accounts (MARSAD_DEMO=1 only). Every name and number here is made up."""
import datetime as dt
import random

from insights import auth, db, store

DEMO_PASSWORD = "Demo@Insights2026"
TPAS = ["GlobeMed Saudi", "NextCare"]
PROVIDERS = [f"Demo Hospital {c}" for c in "ABCDEFGHIJKLMN"]
CODES = [("ELG", 3), ("EMG", 8), ("TRG", 4), ("PRV", 2), ("BEN", 6), ("DOC", 5), ("DQ", 9), ("CLM", 2)]
TYPES = {"ELG": "Eligibility not confirmed", "EMG": "Emergency criteria not met", "TRG": "Triage level inconsistent",
         "PRV": "Provider channel mismatch", "BEN": "Benefit limit or duration exceeded", "DOC": "Documentation missing",
         "DQ": "Data inconsistent", "CLM": "Billed above authorised amount"}



def _valid(y, m, d):
    try:
        dt.date(y, m, d)
        return True
    except ValueError:
        return False

def _days(start, end):
    d = start
    while d <= end:
        if d.weekday() not in (4, 5):
            yield d
        d += dt.timedelta(days=1)


def build(today=None):
    r = random.Random(2026)
    today = today or dt.date.today()
    start = (today.replace(day=1) - dt.timedelta(days=75)).replace(day=1)
    # ---- F1 daily register
    intake, review, fl, n = [], [], [], 0
    for d in _days(start, today - dt.timedelta(days=1)):
        for tpa in TPAS:
            rec = r.randint(180, 420) if tpa == TPAS[0] else r.randint(60, 160)
            rev = rec - (r.randint(0, 6) if d > today - dt.timedelta(days=4) else 0)
            intake.append(dict(date=d.isoformat(), source="Approval", tpa=tpa, received=rec, reviewed=rev, outstanding=rec - rev))
            conf = 0
            for _ in range(int(rev * r.uniform(0.03, 0.08))):
                fam, k = r.choice(CODES)
                n += 1
                status = "Confirmed" if r.random() > 0.04 else "Cleared on review"
                conf += status == "Confirmed"
                sent = d + dt.timedelta(days=r.randint(1, 5)) if r.random() < 0.05 else None
                fl.append(dict(log_id=f"DEMO-{n:05d}", date=d.isoformat(), source="Approval", ref=f"demo{n % 9000:05d}",
                               tpa=tpa, provider=r.choice(PROVIDERS), code=f"{fam}-{r.randint(1, k):02d}", family=fam,
                               status=status, severity=r.choice(["Low", "Medium", "Medium", "High"]),
                               action=r.choice(["TPA level", "TPA level", "Provider level"]),
                               amount=round(r.choice([0, r.uniform(2000, 60000), r.uniform(20000, 250000)]), 2),
                               owner_type="CNHI Approvals", due=(d + dt.timedelta(days=7)).isoformat(),
                               state=r.choice(["Open", ""]), closed=None,
                               shared_tpa=(d + dt.timedelta(days=2)).isoformat() if r.random() < 0.6 else None,
                               selection="", evidence="", sent_cnhi=sent.isoformat() if sent else None,
                               cnhi_response=r.choice(["", "Endorse - route to TPA", "Not endorsed"]) if sent else "",
                               cnhi_status=""))
            review.append(dict(date=d.isoformat(), reviewer=f"Reviewer {1 if tpa == TPAS[0] else 2}", tpa=tpa, records=rev,
                               confirmed=conf, declared=conf, logged=conf))
    codes = [dict(code=f"{fam}-{i:02d}", family=fam, type_en=TYPES[fam], type_ar="", fwa="", root="")
             for fam, k in CODES for i in range(1, k + 1)]
    f1 = dict(intake=intake, review=review, flags=fl, codes=codes, nphies=[],
              has=dict(shared_tpa=True, selection=False, evidence=False, fwa=False, root=False, closed=False, cnhi=True))
    # ---- F2 GSS workbook
    gss, sample = [], []
    ops = ["Satisfactory", "Satisfactory with exceptions", "Unsatisfactory", "Unsatisfactory"]
    for i in range(1, 25):
        st = start + dt.timedelta(days=r.randint(5, 70))
        issued = st + dt.timedelta(days=r.randint(4, 12))
        done = issued < today
        claims = r.randint(20, 400)
        claimed = claims * r.uniform(8000, 25000)
        sampled = max(5, int(claims * r.uniform(0.08, 0.3)))
        flagged = int(sampled * r.uniform(0.1, 0.9))
        gid = f"DEMO-GSS-{i:03d}"
        k = {f"K{j}": r.choice(["Pass", "Pass", "Pass", "Partial", "Fail"]) if done else "" for j in range(1, 13)}
        gss.append(dict(gss_id=gid, hospital=r.choice(PROVIDERS), tpa=TPAS[0], billing_month=start.isoformat()[:7], claims=claims,
                        claimed=round(claimed, 2), start=st.isoformat(), status="Report issued" if done else "Sampling", k=k,
                        critical_fails=sum(1 for j in range(1, 5) if k[f"K{j}"] == "Fail"), issued=issued.isoformat() if done else None,
                        closed=None, sampled=sampled, sample_value=round(claimed * r.uniform(0.2, 0.5), 2), reviewed=sampled if done else 0,
                        flagged=flagged if done else 0, opinion=r.choice(ops) if done else "Review incomplete"))
        for s in range(sampled if done else 0):
            out = r.choice(["No issue identified", "No issue identified", "Documentation gap", "Clinical concern", "Financial discrepancy"])
            amt = r.uniform(3000, 90000)
            sample.append(dict(gss_id=gid, bundle=f"b{i}{s}", claim_type=r.choice(["Inpatient", "Outpatient"]), amount=round(amt, 2),
                               basis=r.choice(["Mandatory", "Risk score", "Statistical sample"]), outcome=out,
                               category="" if out.startswith("No") else r.choice(["Coding inconsistency", "Missing documentation",
                                                                                 "Length of stay or level of care", "Tariff or pricing"]),
                               recommendation="Accept" if out.startswith("No") else "Query provider",
                               at_issue=0 if out.startswith("No") else round(amt * r.uniform(0.1, 1), 2),
                               review_date=(st + dt.timedelta(days=r.randint(1, 3))).isoformat(), flag="" if out.startswith("No") else "Yes",
                               severity="" if out.startswith("No") else r.choice(["Critical", "High", "Medium"]),
                               owner="" if out.startswith("No") else r.choice(["Provider", "TPA"]),
                               due=(st + dt.timedelta(days=10)).isoformat(),
                               flag_status="" if out.startswith("No") else r.choice(["Open", "In progress", "Closed"]), closed=None))
    queue = [dict(gss_id=f"DEMO-Q-{i}", tier=r.choice(["Tier 1", "Tier 2"]), claimed=round(r.uniform(5e5, 2e7), 2),
                  status="Not registered", tpa=TPAS[0]) for i in range(5)]
    f2 = dict(gss=gss, sample=sample, queue=queue, as_of=today.isoformat())
    # ---- F3 disputes tracker
    disputes, tl = [], []
    for i in range(1, 31):
        rec = start + dt.timedelta(days=r.randint(30, 85))
        if rec >= today:
            continue
        resp = rec + dt.timedelta(days=r.randint(2, 9))
        closed = resp + dt.timedelta(days=r.randint(1, 6))
        val = round(r.uniform(8000, 180000), 2)
        oc = r.choice(["Maintained", "Maintained", "Maintained", "Partially maintained", "Reversed", "Withdrawn by hospital"])
        done = closed < today
        disputes.append(dict(id=f"DSP-{i:04d}", received=rec.isoformat(), hospital=r.choice(PROVIDERS), tpa=r.choice(TPAS),
                             pathway="Pre-authorization", type=r.choice(["Medical necessity", "Coding", "Documentation",
                                                                         "Length of stay or level of care"]),
                             value=val, response=resp.isoformat() if resp < today else None,
                             status="Closed" if done else "Response sent", closed=closed.isoformat() if done else None,
                             outcome=oc if done else "", maintained=round(val * 0.6, 2) if oc == "Partially maintained" else None))
        for _ in range(r.randint(1, 4)):
            d = rec + dt.timedelta(days=r.randint(0, 5))
            if d < today:
                tl.append(dict(date=d.isoformat(), member=f"Reviewer {r.randint(1, 3)}", dispute=f"DSP-{i:04d}",
                               activity=r.choice(["Clinical review", "Response drafting", "Case retrieval", "Meeting with hospital or TPA"]),
                               hours=r.choice([0.5, 1, 1.5, 2, 3]), estimated=d < dt.date(today.year, today.month, 1)))
    f3 = dict(disputes=disputes, time=tl)
    # ---- F4 quarterly accounting report
    po = []
    for i in range(140):
        cl = r.uniform(2e5, 4e7)
        ap = cl * r.uniform(0.85, 1)
        ref = "outside" if i % 9 == 0 else "inside"
        po.append(dict(referral=ref, hospital=r.choice(PROVIDERS), billing_month=start.isoformat()[:7], claims=r.randint(1, 200),
                       claimed=round(cl, 2), approved=round(ap, 2), payment_order=round(ap if (ref == "outside" or r.random() < 0.3) else 0, 2)))
    f4 = dict(quarter=f"{today.year}-Q{(today.month - 1) // 3}" if today.month > 3 else f"{today.year - 1}-Q4",
              po=po, totals={}, carried=dict(unpaid_prior=2.1e9, paid_to_qe=1.3e9, paid_label="Demo", duplicates=1.2e6),
              accrued=[dict(gss_id=f"DEMO-A-{i}", status="Approved", total_claim=1e6, total_approved=9e5,
                            not_received=9e5 if i % 4 == 0 else 0) for i in range(60)],
              exceptions=[dict(type=r.choice(["Provider name mismatch", "Purchase-order number mismatch", "Amount difference"]),
                               po_value=1e6, claim_value=1e6, difference=r.choice([0, 0, -2500.0])) for _ in range(6)],
              budget=[dict(line="Treatment in hospitals inside the Kingdom", allocation=5.0e9, spend=1.2e9),
                      dict(line="Treatment in hospitals outside the Kingdom", allocation=1.0e9, spend=2.0e8)])
    # ---- F5 governance register
    deliv, meet = [], []
    m = start
    while m <= today:
        due = (m.replace(day=28) + dt.timedelta(days=14))
        sub = due - dt.timedelta(days=r.randint(-2, 3))
        deliv.append(dict(type="Monthly review report", period=m.strftime("%b-%Y"), due=due.isoformat(),
                          qa=(sub - dt.timedelta(days=1)).isoformat() if sub < today else None,
                          submitted=sub.isoformat() if sub < today else None,
                          approved=(sub + dt.timedelta(days=8)).isoformat() if sub + dt.timedelta(days=8) < today else None, ref=""))
        for w in range(4):
            p = m + dt.timedelta(days=7 * w + 1)
            meet.append(dict(type="Weekly project meeting", planned=p.isoformat(), held=p.isoformat() if p < today and r.random() > 0.1 else None))
        m = (m.replace(day=28) + dt.timedelta(days=5)).replace(day=1)
    recs = [dict(id=f"R{i:02d}", title=f"Demo recommendation {i}", root="TPA adjudication", owner="CNHI", raised=start.isoformat(),
                 status=r.choice(["Raised", "Accepted", "Implemented"]), accepted=None, implemented=None) for i in range(1, 9)]
    kt = [dict(item=f"Demo knowledge-transfer item {i}", type=r.choice(["Session", "Document"]),
               planned=(start + dt.timedelta(days=20 * i)).isoformat(),
               delivered=(start + dt.timedelta(days=20 * i + 2)).isoformat() if start + dt.timedelta(days=20 * i + 2) < today else None)
          for i in range(1, 7)]
    # team effort (monthly person-days by workstream and role), CNHI requests and the contract baseline
    effort, reqs = [], []
    m = start
    while m <= today:
        mk = m.strftime("%Y-%m")
        wd = sum(1 for d in range(1, 32) if _valid(m.year, m.month, d) and dt.date(m.year, m.month, d).weekday() not in (4, 5))
        phys = 3 * wd * r.uniform(0.9, 0.98)
        split = [("MARSAD daily review (approvals and claims)", 0.62), ("GSS claims assurance", 0.16), ("Hospital disputes", 0.08),
                 ("Reporting and governance", 0.08), ("CNHI ad-hoc requests", 0.06)]
        for ws_, share in split:
            effort.append(dict(workstream=ws_, role="Physician", month=mk, days=round(phys * share, 1)))
        fin = wd * r.uniform(0.9, 1.0)
        effort.append(dict(workstream="Financial and accounting review", role="Finance consultant", month=mk, days=round(fin * 0.85, 1)))
        effort.append(dict(workstream="Reporting and governance", role="Finance consultant", month=mk, days=round(fin * 0.15, 1)))
        effort.append(dict(workstream="Reporting and governance", role="Additional KPMG support", month=mk, days=round(r.uniform(3, 6), 1)))
        effort.append(dict(workstream="Hospital disputes", role="Additional KPMG support", month=mk, days=round(r.uniform(1, 3), 1)))
        for i in range(r.randint(2, 5)):
            rec = m + dt.timedelta(days=r.randint(0, 20))
            dlv = rec + dt.timedelta(days=r.randint(1, 6))
            reqs.append(dict(id=f"Q{len(reqs) + 1:03d}", received=rec.isoformat(), unit=r.choice(["CNHI Finance", "CNHI Claims", "CNHI PFPS"]),
                             type=r.choice(["Data extract or analysis", "Case review", "Report or presentation", "Meeting or workshop"]),
                             due=(rec + dt.timedelta(days=4)).isoformat(), delivered=dlv.isoformat() if dlv < today else None,
                             hours=r.choice([3, 4, 6, 8, 12]), status="Delivered" if dlv < today else "Open"))
        m = (m.replace(day=28) + dt.timedelta(days=5)).replace(day=1)
    contract = dict(start=start.isoformat(), months=24, physicians=3, finance=1, hours_per_day=8)
    f5 = dict(deliverables=deliv, meetings=meet, recommendations=recs, kt=kt, effort=effort, requests=reqs, contract=contract)
    return {"F1": f1, "F2": f2, "F3": f3, "F4": f4, "F5": f5}


def seed():
    if db.val("SELECT COUNT(*) FROM users WHERE email LIKE '%@demo.local'", default=0) == 0:
        for email, name, role in (("admin@demo.local", "Demo administrator", "admin"), ("kpmg@demo.local", "Demo KPMG viewer", "kpmg"),
                                  ("cfo@demo.local", "Demo CNHI CFO", "cnhi")):
            db.insert("users", email=email, name=name, role=role, pw_hash=auth.hash_pw(DEMO_PASSWORD), created_at=db.now())
    for kind, data in build().items():
        uid = db.insert("uploads", kind=kind, filename=f"demo_{kind}.xlsx", sha256="demo", size=0, label="",
                        status="staged", summary=db.dumps({"Demo": "synthetic data"}), warnings="[]",
                        created_by="seed_demo", created_at=db.now())
        store.save(uid, data)
        store.publish(uid, "seed_demo")


if __name__ == "__main__":
    import os
    os.environ.setdefault("MARSAD_DEMO", "1")
    import app as _app  # noqa: F401  (creating the app seeds the demo)
    print("Demo data seeded.")
