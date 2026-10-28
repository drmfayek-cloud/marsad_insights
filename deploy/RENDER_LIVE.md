# Render live service

Create a separate **paid** Render Web Service from this repository's `main` branch. The existing `render.yaml` describes the synthetic demo and must not be used for live data.

Use the Docker runtime and `Dockerfile`, choose the approved region, and attach a persistent disk mounted at `/data` before the first start. Set the health check path to `/health`. Do not scale beyond one instance: this application uses a single SQLite database and a local dataset store.

Set these environment variables in the live service:

| Name | Value |
| --- | --- |
| `MARSAD_DEMO` | `0` |
| `MARSAD_HTTPS` | `1` |
| `MARSAD_REQUIRE_MFA` | `1` |
| `MARSAD_DATA` | `/data` |
| `MARSAD_ADMIN_EMAIL` | The approved administrator email |
| `MARSAD_ADMIN_NAME` | The administrator's display name |
| `MARSAD_ADMIN_PASSWORD` | A strong temporary password, entered in Render's secret settings |

The app generates `secret.key` and `hash.key` in `/data` on first start unless `MARSAD_SECRET_KEY` and `MARSAD_HASH_KEY` are provided. Keep the disk and both keys through every deploy and backup. Never copy the demo service's data or keys into the live service.

Before any real workbook upload, verify that the service is on the approved domain with HTTPS, `/health` returns `{"status":"ok"}`, the demo accounts are absent, the administrator is prompted to enroll MFA and change the temporary password, and the persistent disk survives a restart. Remove `MARSAD_ADMIN_PASSWORD` from Render settings after the first administrator account has been created and the password changed.

Arrange automated backups of the full `/data` disk to an approved location and test a restore. The included `deploy/backup.sh` targets Docker Compose volumes and does not back up a Render disk. Upload real workbooks only after the hosting location, access policy, retention, and backup procedure have been approved by the responsible teams.
