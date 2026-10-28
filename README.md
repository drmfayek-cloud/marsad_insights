# MARSAD Insights

Stakeholder dashboard for the CNHI audit and approval of private-sector healthcare procurement project: 55 KPIs on seven bilingual pages (English and Arabic), fed by uploading the team's Excel workbooks.

- Deploy and operate: [DEPLOY.md](DEPLOY.md)
- What was tested, and the limits: [VALIDATION.md](VALIDATION.md)
- KPI definitions: `config/kpis.yaml` (from KPI Dictionary v0.3)

Quick local demo: `pip install -r requirements.txt` then `MARSAD_DEMO=1 MARSAD_HTTPS=0 python app.py` and open http://localhost:8000 (demo password `Demo@Insights2026`).

Never commit workbooks or the `data/` folder to the repository.
