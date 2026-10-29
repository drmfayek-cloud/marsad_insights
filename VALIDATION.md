# Validation - 29 October 2026

## Completed

**Automated tests: 11 passed** (`python -m unittest discover -s tests`), on synthetic workbooks. They cover:
- sign-in, the MFA code check, the forced password change, lockout after 5 failures, and CSRF;
- the administrator role being required for data, users and month close;
- daily-register upload: patient narrative, staff and owner names are not stored; references are hashed; TPA names are normalised;
- KPI arithmetic: encounters counted once (D-02), amount counted once per encounter (D-19), coverage, backlog and validation rate;
- the disputes tracker v1.0 round trip, saved without recalculation: batch dates are inherited, the example action row is ignored, amount disputed and value maintained are derived, pending disputes stay open, and working days exclude Friday and Saturday;
- the governance register template round trip, including Team effort (month typed as text), CNHI requests and the Contract sheet: effort by workstream, the 80/20 mix, additional work, requests, month 12 of 24, and team deployed against 3 + 1 FTE;
- a CNHI viewer seeing the delivery page without the KPMG-only tiles (OP-08, OP-09);
- MFA setup with a QR code: the setup link, the drawn QR code (or the typed-key fallback when the QR package is missing), enrolment with a valid code, and the chosen language kept through sign-in;
- every page rendering in English and Arabic without a calculation error;
- month close freezing figures as Approved, and reopening.

**Real workbooks**: run locally, never stored in the code or the package. The three workbooks shared on 28 October 2026 uploaded, validated and published. The figures reconcile with the source files:

| Check | Dashboard | Source workbook |
|---|---|---|
| Encounters reviewed, September 2026 | 17,036 | Daily Intake total, 17,036 |
| Encounters with a confirmed flag, September 2026 | 1,131 (6.6%) | Distinct references in the Daily Log, 1,131 |
| GSS reports issued; share Unsatisfactory | 8; 62% | GSS workbook dashboard: 5 of 8 completed reviews Unsatisfactory |
| GSS amount at issue (all months) | SAR 2.9M + SAR 0.3M | GSS workbook dashboard, SAR 3,200,582 |
| Open GSS claim flags; past due | 269; 161 | Flag Tracker: 269 open; 161 overdue |
| GSS awaiting review | 24 (4 not registered, 20 sampling) | Priority Queue and GSS Register |
| Q1 2026 claims approved | SAR 3.46B of SAR 3.71B claimed | Q1 report header, SAR 3,463,957,771 |
| Budget utilisation, Q1 2026 | 22% (SAR 1.43B of SAR 6.40B) | Budget sheet, treatment lines total |
| Accrued GSS value not yet invoiced | SAR 79.4M | Accrued-expenses sheet |

**Disputes tracker v1.0** (132 disputes from the four files of 28 October 2026) uploaded and published. The preview reads 132 disputes, 129 KPMG opinions (95 dated), 3 pending and 24 FWA indicators, matching the tracker's Summary sheet. It warns about 128 disputes without a received date, 34 opinions without a date and 129 disputes without an approved amount. October 2026 shows EX-07 = 95 and EX-08 = 93% (88 of 95, Al-Ahly batch only, the one batch with an opinion date). This uploaded check also found and fixed a crash when a dispute had no received date.

**KPMG delivery & effort page** checked on the demo data in English and Arabic, as a KPMG user (nine tiles) and as the CFO (seven tiles, no FTE figure), at desktop and phone width. While building it, a misplaced check from v1.2 was found and removed from GV-03 and GS-08 (it could show a disputes message on those tiles).

**QR-code MFA (v1.4)** checked end to end in a browser: sign in, screenshot the QR code, decode it with OpenCV as a phone camera would, generate the code from the decoded key, and complete sign-in. Passed in light mode (desktop, English) and dark mode (phone, Arabic). The QR package (segno 1.6.6) was tested from its source release; the Docker build installs the same version from PyPI.

**Screens**: the Option A design ('Vibrant tiles') was checked in a browser in English and Arabic (right to left), in light and dark mode, and at phone width. The font is bundled with the app, so nothing is loaded from the internet.

## Not completed here

- The package registry was not reachable from the build workspace, so gunicorn (the production server) and the Docker build were not run. The app was run with Flask's own server. Confirm the first Render build and the `/health` check after deployment.
- No deployment was made to Render or to a server.
- Working days exclude Friday and Saturday but not official holidays.
- Caveats under each KPI are written in English in both languages. Names, definitions and screen text are in Arabic.
- The governance register, including the new effort, request and contract sheets, has no real data yet; its KPIs were tested on synthetic entries only.
- The dispute value KPIs (HD-03, HD-05) and turnaround (HD-06) were checked only on synthetic entries, because no source file gives an approved amount and most batches have no received date yet.
