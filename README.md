# UTSC Commute Delay Tracker 🚌

A small data pipeline + dashboard that tracks TTC bus delays on routes
near **University of Toronto Scarborough (UTSC)**, built on the City of
Toronto's public [Open Data Portal](https://open.toronto.ca/) — no
scraping, just a documented, ToS-friendly API. The data refreshes itself
daily via a scheduled GitHub Actions job.

![CI](https://github.com/<your-username>/<your-repo>/actions/workflows/ci.yml/badge.svg)
![Update Data](https://github.com/<your-username>/<your-repo>/actions/workflows/update-data.yml/badge.svg)

**Live demo:** _add your Streamlit Community Cloud URL here once deployed_

## What it does

1. **Fetches** TTC bus delay records from the City of Toronto's CKAN API
   (`fetch_data.py`) — refreshed automatically every day
2. **Cleans & filters** them down to routes relevant to a UTSC commute
   (`clean.py`) — edit `config.py` to match your own routes
3. **Stores** them in a local SQLite database, deduplicated (`db.py`)
4. **Visualizes** delay trends, worst days/times, and common delay
   causes in an interactive Streamlit dashboard (`dashboard.py`)

## Why this exists

Anyone who commutes to UTSC by bus knows some routes are far less
reliable than others. Instead of relying on vibes, this pulls real
historical delay data and shows which routes/times are actually worth
avoiding.

## Quickstart

```bash
python -m venv venv && source venv/bin/activate  # optional but recommended
pip install -r requirements.txt

# Option A: load real data from the City of Toronto API
python fetch_data.py

# Option B: no network / just want to see it work right away
python generate_sample_data.py   # synthetic demo data, clearly not real

streamlit run dashboard.py
```

Then open the local URL Streamlit prints (usually http://localhost:8501).

## Configuration

Edit `ROUTES_OF_INTEREST` in `config.py` to track different routes —
it's just a dict of route number → friendly name, matched against the
City's `"Line"` field (e.g. `"116 MORNINGSIDE"`).

## Tests & CI

```bash
pytest -v
```

`clean.py` and `db.py` are pure/isolated enough to unit test without
hitting the network — see `tests/`. Two GitHub Actions workflows keep
this repo honest:

- **`ci.yml`** — runs the test suite on every push and pull request
- **`update-data.yml`** — runs `fetch_data.py` daily on a schedule and
  commits the refreshed `ttc_delays.db` back to the repo, so the live
  dashboard is never more than a day stale (also runnable on demand
  from the Actions tab)

The badges at the top of this README reflect the latest runs of each.

## Deploying the live dashboard

1. Push this repo to GitHub (public repo, since Streamlit Community
   Cloud's free tier deploys from public repos).
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with
   GitHub, and click "New app."
3. Point it at this repo, branch `main`, main file `dashboard.py`.
4. Deploy — you'll get a permanent `*.streamlit.app` URL. Put that link
   directly on your resume/LinkedIn next to this project.

## Data source

[TTC Bus Delay Data](https://open.toronto.ca/dataset/ttc-bus-delay-data/) —
City of Toronto Open Data Portal, published by the TTC, updated
regularly. Fetched via the CKAN `datastore_search` API, respecting
pagination with a small delay between requests.

## Possible extensions

- Add the subway delay dataset (`ttc-subway-delay-data`) for the
  Line 3 Scarborough replacement shuttle
- Email/Slack alert when a tracked route has an unusually bad week
- A "reliability score" per route combining delay frequency and severity
