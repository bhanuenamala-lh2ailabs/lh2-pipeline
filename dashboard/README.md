# LH2 Sales Dashboard

Self-contained sales dashboard for the **Scraped** HubSpot pipeline. Independent of
the pipeline code in this repo — everything lives under `dashboard/`.

- `index.html` — the dashboard (GTM Analysts Summary, Lead Manager, Executive/CEO).
  Dashboard-selectable, filterable by member / lead type / date, cumulative by day/week/month.
- `build_dashboard.py` — pulls fresh data from HubSpot into `dashboard_data.json`.
  Reads the token from the `HUBSPOT_API_KEY` env var (CI) or a local `.env` (`hubspot_key=...`).

## Hosting (GitHub Pages, auto-deployed)

Deployed by `.github/workflows/deploy-dashboard.yml` — runs hourly + on demand,
pulls fresh HubSpot data, and publishes to GitHub Pages.

**One-time setup in this repo's settings:**
1. **Settings → Pages → Source: "GitHub Actions"**
2. **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `HUBSPOT_API_KEY`  ·  Value: the HubSpot private-app token (`pat-na2-…`)
3. **Actions → Deploy Sales Dashboard → Run workflow** (first run), then it's hourly.

The page URL appears in the workflow's `deploy` step output
(`https://<owner>.github.io/lh2-pipeline/`).

## Run locally

```bash
python dashboard/build_dashboard.py     # writes dashboard/dashboard_data.json
python -m http.server 8000              # then open http://127.0.0.1:8000/dashboard/
```
