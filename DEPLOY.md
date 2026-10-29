# MARSAD Insights: deployment and operating guide

Version 1.7 · 29 October 2026 · KPI dictionary v0.6 · disputes tracker v1.0

MARSAD Insights is the stakeholder dashboard for the CNHI audit and approval project. It is a separate application from MARSAD live, with its own link and user list. You keep working in your Excel workbooks; you upload them to the dashboard, it checks them, and you publish. The dashboard then shows the 74 KPIs on eight bilingual pages (English and Arabic).

---

## 1. What you are deploying

| Part | What it is |
|---|---|
| Application | Python (Flask), one container, no external services |
| Storage | One SQLite file plus de-identified datasets, all under the data folder (`/data`) |
| Uploaded register workbooks (F1-F6) | Read once, then deleted. Only de-identified figures are kept. |
| Documents library | PDF, Word and Excel files deliberately added to the library are kept under `/data/library`, checked at upload (see 7d) |
| Charts | Drawn on the server; nothing is loaded from the internet |
| Sign-in | Email and password, plus an authenticator-app code (MFA, set up by scanning a QR code), 8-hour sessions, lockout after 5 failed attempts |

Roles:

| Role | Can do |
|---|---|
| Administrator | Upload and publish workbooks, close months, manage users, view the audit log. This is you. |
| KPMG viewer | All pages, including per-reviewer figures |
| CNHI viewer | All pages without per-reviewer figures and without the two KPMG-only tiles (OP-08 team deployed, OP-09 output per person-day). Provider names on the Governance page follow D-23 for every role. Give this role to the CFO and other CNHI users. |

---

## 2. Decide where it runs (before any real data)

| Option | Use it for | Data allowed |
|---|---|---|
| **A. Render, free plan** | A preview link to show the dashboard | **Synthetic demo data only.** Frankfurt region, no persistent disk: everything resets on restart. |
| **B. In-Kingdom server (recommended for live use)** | The live dashboard shared with CNHI | Real workbooks, subject to KPMG Risk and CNHI information-security approval |
| C. Render, paid plan with a disk | Only if CNHI approves hosting outside the Kingdom in writing | As approved |

The dashboard stores no patient identifiers, but it still holds CNHI operational and financial data. Do not upload real workbooks to Option A.

---

## 3. Option A: preview on Render from your iPad (about 15 minutes)

### 3.1 Put the code on GitHub

Choose one of the two routes.

**Route 1 (simplest on an iPad):**
1. On github.com, create a new **private** repository named `marsad-insights`. Leave "Add a README" unticked.
2. In this Claude chat, ask: "push the MARSAD Insights code to drmfayek-cloud/marsad-insights". Claude pushes the code to the repository so Render can build it.

**Route 2 (Working Copy app):**
1. Save the ZIP to Files and unzip it.
2. Open the `marsad-insights` folder in the Working Copy app and initialise a repository.
3. Add your GitHub repository as the remote, commit everything and push.

### 3.2 Create the service on Render

1. On dashboard.render.com, choose **New → Blueprint**.
2. Select the `marsad-insights` repository. Render reads `render.yaml`.
3. Confirm the workspace, then choose **Apply**. The first build takes 3 to 6 minutes.
4. Open the service URL and sign in with a demo account:

| Email | Role |
|---|---|
| `admin@demo.local` | Administrator |
| `kpmg@demo.local` | KPMG viewer |
| `cfo@demo.local` | CNHI viewer (CFO view) |

The password for all three is `Demo@Insights2026`. At the first sign-in, scan the QR code with an authenticator app and enter the 6-digit code (see 4.4). The free plan keeps no disk, so after a restart each demo account scans again.

On the free plan, the service sleeps after 15 minutes without visits, so the first visit afterwards takes about a minute. A restart or a redeploy reloads fresh demo data.

---

## 4. Option B: live dashboard on an in-Kingdom server

Give this section to KPMG IT or CNHI IT.

### 4.1 Server

| Item | Requirement |
|---|---|
| Machine | Ubuntu 22.04 or 24.04, 2 vCPU, 4 GB RAM, 50 GB disk |
| Software | Docker with the Compose plugin, nginx, certbot (or the organisation's certificate) |
| Network | A DNS name (for example `insights.<domain>.sa`), port 443 open to CNHI and KPMG users |
| Approvals | KPMG Risk sign-off and a CNHI information-security review |

### 4.2 Install

```bash
git clone <your repository URL> marsad-insights && cd marsad-insights
cp .env.example insights.env
nano insights.env      # set MARSAD_ADMIN_EMAIL, MARSAD_ADMIN_NAME and a temporary MARSAD_ADMIN_PASSWORD
docker compose up -d --build
curl -s http://127.0.0.1:8000/health          # {"status": "ok"}
```

### 4.3 HTTPS

1. Copy `deploy/nginx.conf` to `/etc/nginx/sites-available/insights` and replace `insights.example.sa` with your name.
2. Enable the site, then run `sudo certbot --nginx -d <your name>`, or install the organisation's certificate.
3. To limit access to CNHI and KPMG networks, uncomment the `allow`/`deny` lines.

### 4.4 First sign-in

1. Open the site and sign in with the administrator email and temporary password.
2. Set up two-step sign-in. The screen shows a QR code:
   - **Phone and computer:** in Microsoft Authenticator or Google Authenticator, choose Add account, then scan the QR code on the computer screen.
   - **Signing in on the same phone or iPad:** press "Open in the authenticator app"; the app adds the account directly.
   - **If neither works:** open "Can't scan? Enter the key instead" and type the key (account name MARSAD Insights, time-based).
   - Enter the 6-digit code the app shows. If it is refused, check that the phone's clock is set automatically.

   Every new user goes through the same screen at first sign-in, and again after an administrator presses **Reset MFA** (Users page).
3. Set your own password when asked.
4. Remove `MARSAD_ADMIN_PASSWORD` from `insights.env`, then run `docker compose up -d`.

### 4.5 Backups

Schedule `deploy/backup.sh` nightly with cron, and copy the archives to a second in-Kingdom location:

```bash
sudo crontab -e
# 30 1 * * * /path/to/marsad-insights/deploy/backup.sh
```

Back up the whole data volume. The keys in it (`secret.key`, `hash.key`) are needed to read existing sessions and to match references across uploads.

### 4.6 Updating the code

```bash
git pull && docker compose up -d --build
```

Data and users stay in the volume. Database changes apply automatically on start.

---

## 5. Setting up the dashboard (Administrator)

1. **Add users** (Administration → Users). Each user gets a temporary password, shown once; send it through a separate channel. Users set up MFA and change the password at first sign-in.
2. **Upload the workbooks** (Administration → Data uploads), in this order:

| Code | Workbook | Feeds |
|---|---|---|
| F1 | MARSAD Daily Record & Action Tracker (.xlsm) | Executive, daily review, FWA pages |
| F2 | MARSAD GSS Assurance Workbook (.xlsm) | GSS page and the claims headline (EX-05, EX-09) |
| F4 | Quarterly accounting report (.xlsx). Enter the quarter (for example `2026-Q1`) if the sheet names do not show it. | Financial page |
| F3 | CNHI Hospital Disputes Tracker v1.0 (blank copy on the upload page; see section 7a) | Disputes page, EX-07 and EX-08 |
| F5 | Project delivery register (template on the upload page) | KPMG delivery & effort page, EX-10 |
| F6 | Governance & corrective-action register (template on the upload page; see 7c) | Governance & corrective actions page, EX-11, FW-08 |

3. **Check the preview** after each upload. It shows what was read and lists any problems, such as a skipped row, an unknown flag code or a missing optional column. Then press **Publish**. To go back, open an older upload and press **Roll back to this version**.
4. **Close a month** (Administration → Close a month) when CNHI approves that month's report. Its figures are then frozen and marked **Approved**. The current month stays **Provisional**. Reopen a month only to restate it, and record why in the note.

---

## 6. Routine (semi-automated)

| When | What you do | Time |
|---|---|---|
| Daily or weekly | Save the daily register and upload F1; upload F2 after GSS reports are issued | About 2 minutes |
| Weekly, and after each opinion batch | Update and upload the disputes tracker (F3) | 1 minute |
| As documents are issued | Add reports, minutes, evidence and objection files to the documents library, linked and with the right visibility | 1 minute each |
| Monthly | Update the project delivery register (F5), including Team effort and CNHI requests, and upload it; close the month once CNHI approves the report | 10 minutes |
| After each CNHI decision meeting | Update the governance & corrective-action register (F6) from the minutes and upload it | 10 minutes |
| Quarterly | Upload the accounting report (F4) | 2 minutes |

Everything else is calculated: de-identification, KPIs, charts, both languages.

---

## 7. Columns to add to the workbooks

These columns switch on KPIs that show "data capture in progress" today. Type the header text exactly as shown, anywhere in the header row: the upload finds columns by name, not position.

| Workbook and sheet | Header | Switches on |
|---|---|---|
| Daily register, Daily Log | `Shared with TPA on` (date) | EX-06, and the "shared with TPA" stage in FW-05 |
| Daily register, Daily Log | `Selection reason` (text containing "outlier" for outlier cases) | DR-05 |
| Daily register, Daily Log | `Evidence reference` | DR-08 |
| Daily register, Config | `FWA level` per flag code (Error, Waste, Abuse, Suspected fraud) | FW-03 |
| Daily register, Config | `Root cause` per flag code | FW-06 |
| Daily register, Daily Log | Fill `Status` and `Date closed` when a flag is resolved | The "closed or recovered" stage in FW-05 |

DR-03 (review turnaround) also needs a received time and a reviewed time for each encounter. The daily intake records totals per day, so DR-03 stays empty until that is captured.

---

## 7a. Hospital disputes tracker (F3)

The tracker has one sheet per job:

| Sheet | One row per | You enter |
|---|---|---|
| Batches | Objection file received from a hospital | Received date, KPMG opinion date, date sent to CNHI. Every dispute in the batch takes these dates unless its own row overrides them. |
| Disputes | Disputed claim or pre-authorization | References, rejection codes, claimed and approved amounts, KPMG position, recommended action, value to pay (partial acceptances only), FWA indicator, comment, CNHI's final decision |
| Actions | Action on a dispute or batch | Date, action type, team member, hours, whether the hours are a backfilled estimate |

Grey columns are calculated (amount disputed, received and opinion dates, value maintained, outcome, closure date, days to opinion, hours). Do not type over them. The upload also works when the file was saved without recalculation: the dashboard applies the same rules.

How the dashboard reads it:

| KPI | Counts |
|---|---|
| EX-07 | Disputes with a KPMG opinion date in the month |
| EX-08 | Of those, the share where the objection was not accepted (rejection maintained in full) |
| HD-01, HD-02 | Disputes by received date; open = not yet answered by KPMG |
| HD-03, HD-05 | Claimed less approved amount, and the part maintained. A dispute without an approved amount is left out and the tile says how many. |
| HD-04 | KPMG position: Not accepted = Maintained, Partially accepted = Partially maintained, Accepted = Reversed |
| HD-06 | Working days from the received date to the KPMG opinion date |
| HD-07 | Hours in the Actions sheet, from October 2026 |

The upload preview lists disputes without a received date, an opinion date or an approved amount, so you can complete them before publishing. The dashboard keeps the hospital name, theme, position, action and FWA indicator. It never reads the comment, argument or reference columns.

The Almodawat source file contains patient names and national IDs. They were not copied into the tracker; keep that source file out of shared folders.

---

## 7b. KPMG delivery & effort page (from the project delivery register, F5)

The register formerly called the governance register is now the **project delivery register**. Download a fresh copy from the upload page: it has three more sheets, and its Recommendations sheet has moved to F6. Deliverables, meetings, quality review and knowledge transfer (GV-01 to GV-06) now show on this page, under 'Contract delivery and project governance'. If you already keep a register, copy these sheets into it; the upload finds them by name.

| Sheet | Fill in | When |
|---|---|---|
| Contract | Contract start date (yellow). Duration (24 months), 3 physicians, 1 finance consultant and 8 hours per person-day are prefilled. | Once |
| Team effort | One row per workstream and role each month: person-days. Roles: Physician, Finance consultant, Additional KPMG support (anyone outside the contracted team: management, QA, specialists). | Monthly, about 5 minutes |
| CNHI requests | One row per ad-hoc request from CNHI: date received, requesting unit (never a person's name), type, due and delivered dates, hours, status | As requests arrive |

Workstreams: MARSAD daily review (approvals and claims), GSS claims assurance, Hospital disputes, Financial and accounting review, Reporting and governance, CNHI ad-hoc requests.

| KPI | Shows | Who sees it |
|---|---|---|
| OP-01 | Work delivered: encounters reviewed, GSS claims sampled and reports issued, disputes answered, deliverables submitted; this month and contract to date | Everyone |
| OP-02 | Findings and value identified per workstream (never added together; identified, not recovered) | Everyone |
| OP-03 | Person-days by workstream | Everyone (the FTE equivalent shows to KPMG users only) |
| OP-04 | Medical vs financial effort against the 80/20 operating model and the 3:1 contracted team | Everyone |
| OP-05 | Additional work: disputes and CNHI requests, plus KPMG support outside the contracted team, as a share of total effort | Everyone |
| OP-06 | CNHI requests received, delivered, open, and median working days | Everyone |
| OP-07 | Month *n* of 24 and contractual deliverables submitted against the contract total | Everyone |
| OP-08 | Team deployed (FTE) against 3 physicians + 1 finance consultant | KPMG users only |
| OP-09 | Cases reviewed per person-day, by workstream | KPMG users only |

FTE equivalent = person-days ÷ working days in the month (Sunday to Thursday; holidays and leave are not deducted). Dispute hours in the disputes tracker are shown in OP-05 for reference only; the person-days in Team effort are the figure that counts.

---

## 7c. Governance & corrective actions page (F6)

Governance here means the loop from findings to change: **finding → recommendation or escalation → CNHI decision → corrective action on a TPA or provider, or a policy or manual change → completed → effect on later findings**. KPMG keeps the register from CNHI decision minutes and records the minutes reference of every decision.

| Sheet | One row per | Key fields |
|---|---|---|
| Policy & recommendations | Recommendation to CNHI (policy or manual, contract or pricing, process, system or control) | Document affected, source (flag, GSS report, dispute, financial review, trend), stage (Proposed → Under CNHI review → Approved → Issued, or Rejected / Withdrawn) with the date of each stage |
| Decisions | Item submitted to CNHI for a decision | Subject (TPA, provider, policy), topic, value at stake, forum, decision, decision date, minutes reference |
| Corrective actions | Action on a TPA or a provider | Decision ID, action type, flag code, opened / due / completed dates, status, value agreed for recovery, value recovered |

**Provider names (decision D-23).** TPAs are always named. A provider is named only when its decision is Approved (or Approved with changes) and the action is not a referral for investigation. Otherwise the upload discards the name, so it is never stored, and the provider is counted as "Not named". Referrals for investigation appear as counts only. The upload preview shows how many names were withheld.

| KPI | Shows |
|---|---|
| GC-01 | Recommendations by stage and type; changes issued in the period |
| GC-02 | Median days from proposal to CNHI approval, and from approval to issue; age of items awaiting a decision |
| GC-03 | CNHI decisions: decided, outcome mix, pending, median days to decision, value at stake by topic |
| GC-04 | Corrective actions on TPAs: open, overdue, opened and completed, by TPA |
| GC-05 | TPA actions completed by their due date |
| GC-06 | Corrective actions on providers by type; referrals (counts only); providers with repeat actions |
| GC-07 | SAR recovered against SAR agreed, cumulative (the 'recovered' stage: actual cash, unlike identified values elsewhere) |
| GC-08 | For completed actions with a flag code: the same finding for the same TPA or provider, 90 days before against 90 days after. Needs 30 days of review data on each side. An indicator, not proof. |
| GC-09 | Corrective-action status: count by status, age of open actions, stale-register warning |
| EX-11 | CFO page: corrective actions open, overdue, due soon and completed |

### Corrective-action status (decision D-24)

Status is calculated from the dates, never typed, and the same rule drives every tile, the tracker and the download:

| Status | Rule |
|---|---|
| Not started | No opened date yet |
| On track | Open, due in more than 7 days |
| Due soon | Open, due within 7 days |
| Overdue | Open and past the due date |
| Completed - evidence pending | Completed date, no evidence reference |
| Completed - verified | Completed date and evidence reference |
| Cancelled | Status column = Cancelled (kept for the audit trail) |

A red warning shows on the Governance page, the tracker and the CFO tile when the register has not been uploaded for more than 7 days. Thresholds are in `config/settings.yaml` (`corrective_actions`).

**Action tracker** (Governance page → Open the action tracker), for every signed-in user:
- status strip with counts (click to filter), age of open actions, filters for as-at date, TPA, target and action type;
- one row per action: status, change since the previous upload ("was Overdue", "New since last upload"), target, decision and minutes reference, due date and days overdue, owner, recovery, status note;
- action page: timeline from submission to evidence, recovery progress, and status at each published version of the register;
- **Download Excel** (the filtered view, English and Arabic headers, stamped with the as-at date) and **Print or save as PDF** (A4 landscape). Every download is written to the audit log.
- Choose "End of <month>" for a closed month: the tracker then uses the register version current when the month was closed, so it shows the approved month-end position.

**F6 candidates** (Data uploads page, administrators only): an Excel file in the register's column order with decision candidates (daily-register TPA-level flags grouped by TPA, flag code and month, the 5 largest per TPA and month worth at least SAR 100,000; Unsatisfactory GSS reports; disputes with a fraud, waste or abuse indicator) and action candidates (flags CNHI endorsed for routing to the TPA). Copy the rows CNHI should consider into F6 and keep their Source reference, so they are not offered again. The file can contain provider names: keep it internal. Recoveries are not suggested from the quarterly accounting report, which has no reference linking a deduction to an action.

### Operating the register

| When | Who | What |
|---|---|---|
| Within 2 working days of an event (report submitted, minutes received, letter in) | KPMG register maintainer (one named person) | Add or update the row; every row has a source reference |
| Weekly project meeting | Maintainer, with the engagement manager | Review due-soon and overdue actions, chase owners, download candidates, upload F6 (with F3) |
| Monthly management review, before month close | CNHI counterpart confirms; engagement manager closes the month | Confirm the decision log and action statuses with CNHI |
| Quarterly | Finance consultant; medical review lead | Reconcile recovered amounts with the accounting report; review GC-08 effect |

Rules: no row without a source reference; Completed and Value recovered only on evidence; IDs never reused; cancelled actions stay in the file. The Excel file holds provider names: keep it in the restricted engagement folder.

---

## 7d. Documents library (1.7)

**Documents** button in the header, for every signed-in user. KPMG users (administrator and KPMG viewer) upload; CNHI users see and download the documents shared with them.

| Field | Use |
|---|---|
| File | PDF, Word (.docx) or Excel (.xlsx, .xlsm), up to 25 MB. Older .doc and .xls are refused: save them as .docx or .xlsx, because their content cannot be checked. |
| Category | Monthly / quarterly / annual / GSS report, CNHI minutes, decision memo, corrective-action evidence, TPA or provider correspondence, hospital objection file, KPMG dispute opinion, policy or manual, other |
| Period | Month the document covers |
| Who can see it | **KPMG only**, or **KPMG and CNHI**. For a shared document, follow the provider naming rule (D-23) in the title and description. |
| Links | Corrective actions, CNHI decisions, deliverables and dispute batches, chosen from the published registers. Several of each are allowed. |

Checks at upload:
- the content must really be the claimed type (a renamed file is refused);
- the text is scanned for patient identifiers: 10-digit numbers starting with 1 or 2 (national ID and iqama format) and labels such as "patient name" or "رقم الهوية". A file with a match, or with no readable text (a scanned PDF), is refused unless the uploader ticks the confirmation that it holds no patient identifiers. The confirmation is written to the audit log. Matches are counted, never stored.

Where documents appear:
- the action page lists the documents linked to the action and to its decision, with **Add evidence or correspondence**; the tracker shows a paperclip with the count;
- the Governance, Delivery and Disputes pages link to minutes and decisions, deliverable documents, and objection files and opinions;
- search covers the title, file name and the text inside the file.

**New version** keeps the history: the earlier file stays available from the document page, marked "Earlier version", and the list shows the current one. **Delete** (administrator only) removes the file and its versions for good.

A linked evidence document does not change an action's status by itself: the register stays the source of truth. The action page reminds you to enter the evidence reference in F6.

Storage: files sit in the data volume (`/data/library`) and are included in the nightly backup (`deploy/backup.sh`). Plan disk space accordingly (the 50 GB in 4.1 is ample for several thousand reports). On the Render preview the library is emptied at every restart: do not upload real documents there.

**Phase 2 - extraction (not built yet, needs approval).** Reading figures or register rows out of Word and PDF files needs an AI service called from the server, which sends CNHI content outside it. Before it is switched on: KPMG Risk and CNHI information-security approval, an in-Kingdom or approved endpoint, and a review step in which a person accepts each extracted row (as with the candidate list). Until then, extraction is done on request in a Claude session, with the result checked before it goes into the registers.

---

## 8. Settings you may change

| File | What |
|---|---|
| `config/settings.yaml` | TPA name variants (add one when an upload warns about a new spelling), flag-family names in English and Arabic, weekend days, outlier threshold, critical GSS checkpoints, dispute age bands |
| `config/kpis.yaml` | KPI names, definitions (English and Arabic), formulas, caveats, placement on the CFO page |
| `insights/kpi.py` | The calculations. Each KPI is one short function named after its ID (for example `ex04`). |
| `insights/theme.py` | Colour and icon of each KPI tile, and fixed colours for meaningful labels (Unsatisfactory, Maintained, ...) |
| `static/app.css` | The look: palette (light and dark), fonts, tiles, header |

Decisions D-18 to D-21 are built as recommended: review coverage on the CFO page, amount at risk counted once per encounter, the claims headline taken from the GSS sample, and financial KPIs taken from the quarterly accounting report. A different decision means a small change in `kpis.yaml` (wording) and in `kpi.py` (calculation).

---

## 9. Data protection

- Patient IDs and free-text columns (finding narratives, resolutions, hospital arguments) are never read from the workbooks.
- Approval, claim and case references are replaced by a keyed hash. Staff names become "Reviewer 1", "Reviewer 2" and so on.
- A register workbook (F1-F6) is deleted as soon as it has been read; the audit log keeps its name, size and fingerprint.
- Documents library files are kept, because the document itself is what people need. Each is checked at upload for its real type and for patient identifiers, carries its own visibility (KPMG only, or KPMG and CNHI), is served only as a download to users allowed to see it, and every upload, confirmation, download, change and deletion is in the audit log. Deleting a document removes the file and all its versions.
- Every sign-in, upload, publish, month close and user change is recorded in the audit log.
- Security headers: no third-party scripts, a strict content-security policy, secure cookies over HTTPS, and CSRF protection on every form.

---

## 10. Troubleshooting

| Message or symptom | What to do |
|---|---|
| "header row with ... not found" | A header was renamed in the workbook. Restore the original header text. |
| "Sheet '...' was not found" | The wrong workbook type was chosen, or a sheet was renamed |
| "Enter the quarter" | Type the quarter (for example `2026-Q1`) in the upload form |
| A TPA appears twice under two spellings | Add the spelling to `tpa_names` in `config/settings.yaml` and redeploy |
| A user forgot the password or lost the phone | Users page: Reset password or Reset MFA |
| Locked out after 5 attempts | Wait 15 minutes, or ask the administrator to reset the password |
| Render preview is slow to open | The free plan was asleep; wait about a minute |
| A KPI shows "data capture in progress" | The note under it names the missing workbook or column (see section 7) |

---

## 11. File map

```
app.py                 routes: sign-in, pages, uploads, month close, users, audit
insights/parsers.py    reads the six workbooks (columns found by header name)
insights/kpi.py        the 74 KPI calculations
insights/actions.py    corrective-action status rules, tracker, history and Excel download
insights/candidates.py F6 candidate list built from F1-F3
insights/library.py    documents library: type and identifier checks, storage, versions, visibility, links
insights/samplefiles.py small PDF and Word builders (demo library and tests)
insights/deid.py       hashing and pseudonyms
insights/store.py      versioned datasets, publish and roll back
insights/auth.py       passwords, MFA, roles, CSRF
insights/charts.py     SVG charts
insights/theme.py      colours, icons and sparklines (Option A, 'Vibrant tiles')
insights/i18n.py       English and Arabic screen text
config/kpis.yaml       KPI dictionary v0.6
config/settings.yaml   editable settings
templates/, static/    screens and styles; static/fonts holds IBM Plex Sans Arabic (SIL Open Font License, OFL.txt)
seed_demo.py           synthetic demo data (preview only)
tests/test_app.py      automated checks: python -m unittest discover -s tests
```

To run locally on a laptop: `pip install -r requirements.txt`, then `MARSAD_DEMO=1 MARSAD_HTTPS=0 python app.py`, then open http://localhost:8000.
