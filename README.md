# TTC Delay Forecast

Predicting Toronto transit delays from 12 years of public data: **1.25 million
delay records** across every TTC bus, streetcar and subway line (2014 to 2026),
joined to hourly weather, cleaned into one schema, modelled, and evaluated on a
year the models never saw.

![CI](https://github.com/moarznainglinkhant-cloud/ttc-delay-tracker/actions/workflows/ci.yml/badge.svg)

**Live dashboard:** https://ttc-delay-tracker-56pbzhwscg9z9k7tbuyzlm.streamlit.app/
(open "Delay Forecast" in the sidebar)

## Results

All scores are from the held-out test year, 1 Oct 2025 to 30 Sep 2026.

**1. Will this delay run long?** A gradient-boosted classifier estimates, the
moment an incident is logged, whether it becomes a long delay (20+ min on
surface routes, 5+ min on the subway).

| Mode | Best simple baseline (AUC) | Model (AUC) |
|---|---|---|
| Subway | 0.61 | **0.79** |
| Bus | 0.84 | **0.87** |
| Streetcar | 0.73 | 0.74 |

The model clearly earns its keep on the subway. For buses a per-route lookup
table is almost as good, and for streetcars there is no real gain. Flagging
the riskiest 20% of bus incidents catches 50% of all long bus delays, and 77%
of those flags are correct (base rate: 31%).

**2. How many delays tomorrow?** A next-day Poisson forecast of delay counts
per mode, against a 28-day moving average.

| Mode | Delays per day | Baseline error | Model error | Improvement (95% CI) |
|---|---|---|---|---|
| Subway | 78 | 13.3 | 10.3 | **22%** (16% to 28%) |
| Bus | 164 | 30.4 | 25.6 | **16%** (7% to 24%) |
| Streetcar | 37 | 7.0 | 7.1 | none (-7% to 4%) |

**3. Weather only matters when it is extreme.** Adding weather improves
neither model on an average day. But on days with 5 to 10 cm of snow, bus
delays run 27% above normal (95% CI 21% to 35%, 69 days), and on the 27 days
with 10+ cm they run 57% above (CI 20% to 62%).

## How it works

```
download_raw.py  ->  build_dataset.py  ->  train.py  ->  reports/  ->  dashboard
 (City + ECCC)       (one clean table)    (2 models)    (small CSVs)   (Streamlit)
```

| Step | What it does |
|---|---|
| `pipeline/download_raw.py` | Pulls 40 delay files from Toronto Open Data and 336 weather files from Environment Canada, with retries and a manifest. |
| `pipeline/harmonize.py` | Pure functions that reconcile 12 years of format changes (see below). Fully unit tested. |
| `pipeline/build_dataset.py` | Applies them, drops bad rows with a count for every reason, writes Parquet and a data-quality report. |
| `pipeline/features.py` | Leak-safe features: lagged history, calendar and Ontario holidays, daily and hourly weather. |
| `pipeline/train.py` | Trains both models, runs baselines, ablations and bootstrap intervals, writes `reports/`. |
| `pages/2_Delay_Forecast.py` | Dashboard page that reads `reports/` only, so the deployed app needs no ML libraries. |

### The data cleaning

The raw files are not consistent with each other. Handled here:

- **Renamed columns.** `Report Date`/`Date`, `Route`/`Line`, `Direction`/`Bound`,
  `Location`/`Station`, and `Delay`/`Min Delay` for part of 2019 and 2020.
- **Two cause vocabularies.** Bus and streetcar used about 35 plain-English
  labels until 2024, then about 150 internal codes from 2025. Both are mapped
  onto 12 shared groups using the City's code descriptions.
- **Dirty route fields.** `116`, `116 MORNINGSIDE`, vehicle numbers and free
  text all appear in the route column.
- **Fourteen spellings of direction.** `N`, `n`, `NB`, `N/B`, `B/W` and so on.
- **A time-zone trap.** Weather timestamps are standard time all year; TTC logs
  are clock time. Unshifted, every summer hour would join one hour off.
- **A duplicated file.** The City lists the 2020 streetcar workbook twice.

Of 1,257,018 raw rows, 1,246,841 (99.2%) are kept. The cleaned table matches
an independently built earlier version of this project to within 0.3%.

### Evaluation choices

- **Split by time.** Train through Sept 2024, tune on the next 12 months, score
  once on the final 12. A random split would let the model see the future.
- **Strong baselines.** The classifier is compared with both a per-cause rate
  and a per-route, per-time-of-day rate. The second one is what exposed that
  most of the bus result is simply knowing the route.
- **No answer leakage.** `Min Gap` is recorded alongside `Min Delay` and
  correlates 0.95 with it, so it is excluded. A test enforces this.
- **Ablation.** Features were added in stages. Weather did not improve either
  model and is reported as a negative result rather than left in.
- **Uncertainty.** Improvements carry bootstrap intervals, resampling whole
  days because errors within a day are correlated.

## Limits

- The TTC logs *incidents*, not every scheduled trip, so nothing here is a
  "% of trips late". The logged minutes often equal the scheduled gap
  between vehicles (in 51% of records the gap is exactly twice the delay),
  which is why route predicts so much for buses.
- Mapping two cause vocabularies onto 12 groups is approximate, and logging
  habits visibly shift between years.
- The weather-aware forecast uses observed weather, i.e. a perfect forecast.
- Heavy-snow days are rare (27 in 12 years), so those intervals are wide.
- The City refreshes the delay data monthly, so the most recent few weeks are
  never available.

## Run it

```bash
pip install -r requirements.txt
streamlit run dashboard.py            # dashboard only; uses the committed reports/
```

To rebuild everything from the public sources (about 15 minutes):

```bash
pip install -r requirements-pipeline.txt
python -m pipeline.download_raw       # ~130 MB into data/raw/
python -m pipeline.build_dataset      # -> data/processed/*.parquet
python -m pipeline.train              # -> reports/
pytest -q                             # 100 tests
```

## Also in this repo

The project began as a commute tool for University of Toronto Scarborough
students: an Overview page for bus routes near campus and a Commute Planner
for the trip to St. George station. Both still run from `ttc_delays.db`,
which a scheduled GitHub Actions job keeps in step with the City's data.
Those pages describe logged incidents and do not use the models above.

## Stack

Python, pandas, LightGBM, scikit-learn, Streamlit, Altair, SQLite, Parquet,
pytest, GitHub Actions.

## Data sources

- [TTC Bus Delay Data](https://open.toronto.ca/dataset/ttc-bus-delay-data/),
  [Streetcar](https://open.toronto.ca/dataset/ttc-streetcar-delay-data/) and
  [Subway](https://open.toronto.ca/dataset/ttc-subway-delay-data/),
  City of Toronto Open Data
- [Historical climate data](https://climate.weather.gc.ca/), Environment and
  Climate Change Canada (Toronto Pearson and Toronto City stations)
