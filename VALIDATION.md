# Validation - 28 October 2026

## Completed

**Automated tests: 10 passed** (`python -m unittest discover -s tests`), on synthetic workbooks. They cover:
- sign-in, the MFA code check, the forced password change, lockout after 5 failures, and CSRF;
- the administrator role being required for data, users and month close;
- daily-register upload: patient narrative, staff and owner names are not stored; references are hashed; TPA names are normalised;
- KPI arithmetic: encounters counted once (D-02), amount counted once per encounter (D-19), coverage, backlog and validation rate;
- the disputes tracker template round trip: the example row is ignored, partial outcomes are handled, and working days exclude Friday and Saturday;
- the governance register template round trip;
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

**Screens**: the Option A design ('Vibrant tiles') was checked in a browser in English and Arabic (right to left), in light and dark mode, and at phone width. The font is bundled with the app, so nothing is loaded from the internet.

## Not completed here

- The package registry was not reachable from the build workspace, so gunicorn (the production server) and the Docker build were not run. The app was run with Flask's own server. Confirm the first Render build and the `/health` check after deployment.
- No deployment was made to Render or to a server.
- Working days exclude Friday and Saturday but not official holidays.
- Caveats under each KPI are written in English in both languages. Names, definitions and screen text are in Arabic.
- The hospital disputes tracker and the governance register are new templates with no real data yet. Their KPIs were tested on synthetic entries only.
