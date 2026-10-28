# MARSAD Insights: deployment and operating guide

Version 1.0 · 28 October 2026 · KPI dictionary v0.3

MARSAD Insights is the stakeholder dashboard for the CNHI audit and approval project. It is a separate application from MARSAD live, with its own link and user list. You keep working in your Excel workbooks; you upload them to the dashboard, it checks them, and you publish. The dashboard then shows the 55 KPIs on seven bilingual pages (English and Arabic).

---

## 1. What you are deploying

| Part | What it is |
|---|---|
| Application | Python (Flask), one container, no external services |
| Storage | One SQLite file plus de-identified datasets, all under the data folder (`/data`) |
| Uploaded workbooks | Read once, then deleted. Only de-identified figures are kept. |
| Charts | Drawn on the server; nothing is loaded from the internet |
| Sign-in | Email and password, plus an authenticator-app code (MFA), 8-hour sessions, lockout after 5 failed attempts |

Roles:

| Role | Can do |
|---|---|
| Administrator | Upload and publish workbooks, close months, manage users, view the audit log. This is you. |
| KPMG viewer | All pages, including per-reviewer figures |
| CNHI viewer | All pages without per-reviewer figures. Give this role to the CFO and other CNHI users. |

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

The password for all three is `Demo@Insights2026`.

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
2. Scan or type the key into an authenticator app (Microsoft Authenticator or Google Authenticator).
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
| F3 | Hospital disputes tracker (template on the upload page) | Disputes page, EX-07 and EX-08 |
| F5 | Governance register (template on the upload page) | Governance page, EX-10, FW-08 |

3. **Check the preview** after each upload. It shows what was read and lists any problems, such as a skipped row, an unknown flag code or a missing optional column. Then press **Publish**. To go back, open an older upload and press **Roll back to this version**.
4. **Close a month** (Administration → Close a month) when CNHI approves that month's report. Its figures are then frozen and marked **Approved**. The current month stays **Provisional**. Reopen a month only to restate it, and record why in the note.

---

## 6. Routine (semi-automated)

| When | What you do | Time |
|---|---|---|
| Daily or weekly | Save the daily register and upload F1; upload F2 after GSS reports are issued | About 2 minutes |
| Weekly | Upload the disputes tracker (F3) | 1 minute |
| Monthly | Update and upload the governance register (F5); close the month once CNHI approves the report | 5 minutes |
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
- The uploaded file is deleted as soon as it has been read; the audit log keeps its name, size and fingerprint.
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
insights/parsers.py    reads the five workbooks (columns found by header name)
insights/kpi.py        the 55 KPI calculations
insights/deid.py       hashing and pseudonyms
insights/store.py      versioned datasets, publish and roll back
insights/auth.py       passwords, MFA, roles, CSRF
insights/charts.py     SVG charts
insights/theme.py      colours, icons and sparklines (Option A, 'Vibrant tiles')
insights/i18n.py       English and Arabic screen text
config/kpis.yaml       KPI dictionary v0.3
config/settings.yaml   editable settings
templates/, static/    screens and styles; static/fonts holds IBM Plex Sans Arabic (SIL Open Font License, OFL.txt)
seed_demo.py           synthetic demo data (preview only)
tests/test_app.py      automated checks: python -m unittest discover -s tests
```

To run locally on a laptop: `pip install -r requirements.txt`, then `MARSAD_DEMO=1 MARSAD_HTTPS=0 python app.py`, then open http://localhost:8000.
