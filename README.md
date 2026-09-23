# UTSC Commute Delay Tracker 🚌

A small data pipeline + dashboard that tracks TTC bus and subway delays
relevant to a **University of Toronto Scarborough (UTSC)** commute,
built on the City of Toronto's public [Open Data Portal](https://open.toronto.ca/) —
no scraping, just a documented, ToS-friendly API. The data refreshes
itself daily via a scheduled GitHub Actions job.

![CI](https://github.com/moarznainglinkhant-cloud/ttc-delay-tracker/actions/workflows/ci.yml/badge.svg)
![Update Data](https://github.com/moarznainglinkhant-cloud/ttc-delay-tracker/actions/workflows/update-data.yml/badge.svg)

**Live demo:** https://ttc-delay-tracker-56pbzhwscg9z9k7tbuyzlm.streamlit.app/

## What it does

1. **Fetches** TTC bus *and* subway delay records from the City of
   Toronto's CKAN API (`fetch_data.py`) — refreshed automatically every day
2. **Cleans & filters** them down to what matters for a UTSC commute
   (`clean.py`) — bus routes near campus, and Line 2 (Bloor–Danforth)
   subway delays for the Kennedy Station leg — edit `config.py` to match
   your own routes
3. **Stores** them in a local SQLite database, deduplicated (`db.py`)
4. **Visualizes** two things:
   - **Overview** (`dashboard.py`) — delay trends, worst days/times, and
     common delay causes for your tracked bus routes
   - **Commute Planner** (`pages/1_Commute_Planner.py`) — combines the
     bus-to-Kennedy leg with the Line 2 subway leg to St. George Station
     to estimate which hours/days are historically the least
     delay-prone time to travel between UTSC and the St. George campus

## Why this exists

Anyone who commutes between UTSC and downtown knows some times of day
are far less reliable than others. Instead of relying on vibes, this
pulls real historical delay data for both legs of the trip and surfaces
which departure windows have actually held up.

**Honesty about what the numbers mean:** the City's delay datasets log
*incidents*, not every scheduled trip, so there's no way to compute a
true "% chance of being late." What the Commute Planner shows is a
relative reliability signal, based on how often and how severely delays
were logged at each hour/day, which is still a meaningfully better
signal than guessing.

## Findings

A few things the data actually showed, pulled from the live database:

- **Day of week barely matters.** Average delay only moves between
  12.0 and 12.9 minutes across all seven days — Monday isn't
  meaningfully worse than Wednesday, and weekends aren't meaningfully
  calmer than weekdays. The common assumption that certain days are
  just "bad days" doesn't hold up here.
- **The subway leg is far more reliable than the bus leg.** Line 2's
  typical average delay is ~2.4 minutes versus the bus's ~12.4 minutes
  — almost all of this commute's unpredictability comes from getting
  to Kennedy Station, not the subway ride itself.
- **Best/worst time to travel:** combined delay risk is lowest around
  3pm (~13.7 min avg) and highest around 10pm (~17.1 min avg), with a
  secondary bump around 6-7am (~16.7 min avg). Midafternoon is the
  sweet spot; early morning and late evening are the riskiest windows.

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
The Commute Planner page is in the sidebar nav once the app is running.

## Configuration

Edit `config.py` to match your own commute:

- `ROUTES_OF_INTEREST` — dict of bus route number → friendly name,
  matched against the City's `"Line"` field (e.g. `"116 MORNINGSIDE"`)
- `SUBWAY_LINE_OF_INTEREST` — the subway line code for your commute's
  subway leg (`"BD"` for Kennedy → St. George on Line 2; use `"YU"` for
  Line 1, `"SHP"` for Line 4)

## Tests & CI

```bash
pytest -v
```

`clean.py` and `db.py` are pure/isolated enough to unit test without
hitting the network — see `tests/` (18 tests, covering bus + subway
normalization and the database migration path). Two GitHub Actions
workflows keep this repo honest:

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

## Data sources

- [TTC Bus Delay Data](https://open.toronto.ca/dataset/ttc-bus-delay-data/)
- [TTC Subway Delay Data](https://open.toronto.ca/dataset/ttc-subway-delay-data/)

Both from the City of Toronto Open Data Portal, published by the TTC
and updated regularly. Fetched via the CKAN `datastore_search` API,
respecting pagination with a small delay between requests.

## Possible extensions

- Add GTFS scheduled-trip data to estimate actual added travel time,
  not just relative delay-incident frequency
- Email/Slack alert when a tracked route or the subway leg has an
  unusually bad week
- A "reliability score" per route combining delay frequency and severity
