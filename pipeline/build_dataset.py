"""
Turn the raw downloads in data/raw/ into analysis-ready tables in
data/processed/:

  delays.parquet          one row per logged delay, all modes, one schema
  weather_hourly.parquet  one row per local clock hour
  weather_daily.parquet   one row per day
  quality_report.json     what was read, what was dropped, and why

Run:
    python -m pipeline.build_dataset
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import harmonize as hz

MODES = ("bus", "streetcar", "subway")
# Anything above this is a multi-day closure or a typo, not a delay.
MAX_PLAUSIBLE_DELAY_MIN = 24 * 60
# A bus/streetcar "route" seen fewer times than this in 12 years is a
# vehicle number or typo that happened to look like a route number.
MIN_ROUTE_RECORDS = 50


# --------------------------------------------------------------------------
# TTC delays
# --------------------------------------------------------------------------


def _first_present(df: pd.DataFrame, names: list[str]) -> pd.Series:
    """Coalesce several possible column names into one string Series."""
    out = pd.Series(pd.NA, index=df.index, dtype="object")
    for name in names:
        if name in df.columns:
            col = df[name].astype("object")
            col = col.where(col.notna() & (col.astype(str).str.strip() != ""), pd.NA)
            out = out.where(out.notna(), col)
    return out


def read_raw_delays(raw_dir: Path, report: dict) -> pd.DataFrame:
    """Read every delay workbook/CSV into one frame of raw strings."""
    frames, seen_hashes, files = [], {}, []
    for mode in MODES:
        for path in sorted((raw_dir / "ttc" / mode).glob("*")):
            name = path.name.lower()
            if "readme" in name or "code" in name or path.suffix not in {".xlsx", ".csv"}:
                continue
            digest = hashlib.md5(path.read_bytes()).hexdigest()
            if digest in seen_hashes:
                # The City lists the 2020 streetcar workbook twice.
                files.append({"file": path.name, "skipped": f"identical to {seen_hashes[digest]}"})
                continue
            seen_hashes[digest] = path.name

            if path.suffix == ".csv":
                sheets = {"csv": pd.read_csv(path, dtype=str, keep_default_na=False)}
            else:
                sheets = pd.read_excel(path, sheet_name=None, dtype=str, engine="openpyxl")
            rows = 0
            for sheet_name, df in sheets.items():
                df = df.dropna(how="all")
                df.columns = [str(c).strip() for c in df.columns]
                df = df.assign(_mode=mode, _file=path.name, _sheet=str(sheet_name))
                frames.append(df)
                rows += len(df)
            files.append({"file": path.name, "mode": mode, "sheets": len(sheets), "rows": rows})
    report["files"] = files
    return pd.concat(frames, ignore_index=True)


def read_code_descriptions(raw_dir: Path) -> dict[str, str]:
    """Official code -> description, merged across the three modes."""
    lookup: dict[str, str] = {}
    for mode in MODES:
        for path in (raw_dir / "ttc" / mode).glob("Code_Descriptions*.csv"):
            # Published with mis-decoded dashes; the text is only used for keyword matching.
            df = pd.read_csv(path, dtype=str, encoding="utf-8", encoding_errors="replace")
            df.columns = [c.strip().upper() for c in df.columns]
            for code, desc in zip(df["CODE"], df["DESCRIPTION"]):
                if isinstance(code, str) and isinstance(desc, str):
                    lookup[code.strip().upper()] = desc.strip()

    # The older subway workbook also documents the retired Line 3 (SRT)
    # codes, laid out as two side-by-side tables.
    for path in (raw_dir / "ttc" / "subway").glob("ttc-subway-delay-codes*.xlsx"):
        sheet = pd.read_excel(path, header=None, dtype=str)
        for code_col in range(sheet.shape[1] - 1):
            for code, desc in zip(sheet[code_col], sheet[code_col + 1]):
                if isinstance(code, str) and isinstance(desc, str) and re.fullmatch(r"[A-Z]{2,6}\d?", code.strip()):
                    lookup.setdefault(code.strip().upper(), desc.strip())
    return lookup


def harmonize_delays(raw: pd.DataFrame, code_descriptions: dict[str, str], report: dict) -> pd.DataFrame:
    mode = raw["_mode"]
    date_raw = _first_present(raw, ["Date", "Report Date"])
    route_raw = _first_present(raw, ["Line", "Route"])
    cause_raw = _first_present(raw, ["Code", "Incident"])

    date = pd.to_datetime(date_raw, errors="coerce", format="mixed").dt.normalize()
    hm = _first_present(raw, ["Time"]).map(hz.parse_hour_minute)
    hour = hm.map(lambda t: t[0]).astype("Int64")
    minute = hm.map(lambda t: t[1]).astype("Int64")

    is_subway = mode == "subway"
    route = pd.Series(pd.NA, index=raw.index, dtype="object")
    route[is_subway] = route_raw[is_subway].map(hz.normalize_subway_line, na_action="ignore")
    route[~is_subway] = route_raw[~is_subway].map(hz.normalize_surface_route, na_action="ignore")

    # Map each distinct raw cause once, not once per row.
    cause_lookup = {c: hz.cause_group(c, code_descriptions) for c in cause_raw.dropna().unique()}

    out = pd.DataFrame(
        {
            "mode": mode,
            "date": date,
            "hour": hour,
            "minute": minute,
            "route": route,
            "route_raw": route_raw,
            "location": _first_present(raw, ["Station", "Location"]).str.strip().str.upper(),
            "cause_raw": cause_raw.str.strip(),
            "cause": cause_raw.map(cause_lookup).fillna("other"),
            "min_delay": _first_present(raw, ["Min Delay", "Delay"]).map(hz.to_minutes, na_action="ignore"),
            "min_gap": _first_present(raw, ["Min Gap", "Gap"]).map(hz.to_minutes, na_action="ignore"),
            "direction": _first_present(raw, ["Bound", "Direction"]).map(hz.normalize_direction, na_action="ignore"),
            "vehicle": _first_present(raw, ["Vehicle"]).str.strip(),
            "source_file": raw["_file"],
        }
    )
    out["min_delay"] = pd.to_numeric(out["min_delay"], errors="coerce")
    out["min_gap"] = pd.to_numeric(out["min_gap"], errors="coerce")

    # ---- drops, each counted so the report shows exactly what was lost
    steps = {"rows_read": int(len(out))}

    keep = out["date"].notna() & out["hour"].notna()
    steps["dropped_no_date_or_time"] = int((~keep).sum())
    out = out[keep]

    # A handful of rows carry dates outside their own file's year (typos).
    in_range = out["date"].between("2014-01-01", pd.Timestamp.today().normalize())
    steps["dropped_date_out_of_range"] = int((~in_range).sum())
    out = out[in_range]

    keep = out["route"].notna()
    steps["dropped_unrecognized_route"] = int((~keep).sum())
    out = out[keep]

    route_size = out.groupby(["mode", "route"])["route"].transform("size")
    keep = (out["mode"] == "subway") | (route_size >= MIN_ROUTE_RECORDS)
    steps["dropped_rare_route"] = int((~keep).sum())
    out = out[keep]

    too_long = out["min_delay"] > MAX_PLAUSIBLE_DELAY_MIN
    steps["dropped_implausible_delay"] = int(too_long.sum())
    out = out[~too_long]

    before = len(out)
    out = out.drop_duplicates(
        subset=["mode", "date", "hour", "minute", "route", "location", "cause_raw", "min_delay", "min_gap", "direction", "vehicle"]
    )
    steps["dropped_exact_duplicates"] = int(before - len(out))

    out["min_delay"] = out["min_delay"].fillna(0.0)
    out["timestamp"] = out["date"] + pd.to_timedelta(out["hour"].astype(int), unit="h") + pd.to_timedelta(
        out["minute"].astype(int), unit="m"
    )
    out["hour"] = out["hour"].astype("int8")
    out = out.drop(columns=["minute"]).sort_values(["timestamp", "mode", "route"]).reset_index(drop=True)

    steps["rows_kept"] = int(len(out))
    report["delays"] = steps
    report["rows_by_mode"] = {k: int(v) for k, v in out["mode"].value_counts().items()}
    report["rows_by_year"] = {int(k): int(v) for k, v in out["date"].dt.year.value_counts().sort_index().items()}
    report["cause_share"] = {k: round(float(v), 4) for k, v in out["cause"].value_counts(normalize=True).items()}
    return out


# --------------------------------------------------------------------------
# Weather
# --------------------------------------------------------------------------


def _read_weather(raw_dir: Path, station: str, timeframe: str) -> pd.DataFrame:
    files = sorted((raw_dir / "weather" / station).glob(f"{timeframe}_*.csv"))
    frames = [pd.read_csv(f, encoding="utf-8-sig", low_memory=False) for f in files]
    return pd.concat(frames, ignore_index=True)


def build_weather_hourly(raw_dir: Path) -> pd.DataFrame:
    """Hourly weather on the *local clock* the TTC logs use.

    ECCC timestamps are Local Standard Time all year (no daylight
    saving), while TTC logs are wall-clock time. Left alone, every
    summer observation would be joined one hour off, so the timestamps
    are shifted onto America/Toronto clock time here.

    Pearson supplies temperature/wind/visibility/conditions; the
    downtown station supplies hourly precipitation, which Pearson's
    hourly feed does not report.
    """
    pearson = _read_weather(raw_dir, "pearson", "hourly")
    city = _read_weather(raw_dir, "toronto_city", "hourly")

    def clock_time(frame: pd.DataFrame) -> pd.Series:
        lst = pd.to_datetime(frame["Date/Time (LST)"])
        local = lst.dt.tz_localize("Etc/GMT+5").dt.tz_convert("America/Toronto")
        return local.dt.tz_localize(None)

    hourly = pd.DataFrame(
        {
            "timestamp": clock_time(pearson),
            "temp_c": pearson["Temp (°C)"],
            "wind_kmh": pearson["Wind Spd (km/h)"],
            "visibility_km": pearson["Visibility (km)"],
            "humidity_pct": pearson["Rel Hum (%)"],
            "conditions": pearson["Weather"].fillna("").astype(str).str.lower(),
        }
    )
    precip = pd.DataFrame({"timestamp": clock_time(city), "precip_mm": city["Precip. Amount (mm)"]})
    hourly = hourly.merge(precip, on="timestamp", how="left")

    cond = hourly["conditions"]
    hourly["is_snow"] = cond.str.contains("snow", regex=False)
    hourly["is_rain"] = cond.str.contains("rain|drizzle") & ~cond.str.contains("freezing", regex=False)
    hourly["is_freezing"] = cond.str.contains("freezing|ice pellets")
    hourly["is_fog"] = cond.str.contains("fog", regex=False)
    hourly["is_thunder"] = cond.str.contains("thunder", regex=False)

    # The autumn clock change repeats one hour; keep the first reading.
    hourly = hourly.drop_duplicates("timestamp").sort_values("timestamp")
    hourly = hourly[hourly["temp_c"].notna()].reset_index(drop=True)
    return hourly.drop(columns=["conditions"])


def build_weather_daily(raw_dir: Path) -> pd.DataFrame:
    daily = _read_weather(raw_dir, "pearson", "daily")
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(daily["Date/Time"]),
            "temp_max_c": daily["Max Temp (°C)"],
            "temp_min_c": daily["Min Temp (°C)"],
            "temp_mean_c": daily["Mean Temp (°C)"],
            "rain_mm": daily["Total Rain (mm)"],
            "snow_cm": daily["Total Snow (cm)"],
            "precip_mm": daily["Total Precip (mm)"],
            # Only recorded when there is snow on the ground.
            "snow_on_ground_cm": daily["Snow on Grnd (cm)"],
            "max_gust_kmh": pd.to_numeric(daily["Spd of Max Gust (km/h)"].astype(str).str.replace("<", ""), errors="coerce"),
        }
    )
    out = out[out["temp_mean_c"].notna()].sort_values("date").reset_index(drop=True)
    out["snow_on_ground_cm"] = out["snow_on_ground_cm"].fillna(0.0)
    return out


# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, default=Path("data/processed"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    report: dict = {}
    print("Reading raw delay files ...")
    raw = read_raw_delays(args.raw, report)
    codes = read_code_descriptions(args.raw)
    print(f"  {len(raw):,} raw rows, {len(codes)} documented codes")

    delays = harmonize_delays(raw, codes, report)
    delays.to_parquet(args.out / "delays.parquet", index=False)
    print(f"  kept {len(delays):,} rows -> {args.out / 'delays.parquet'}")

    print("Building weather tables ...")
    hourly = build_weather_hourly(args.raw)
    daily = build_weather_daily(args.raw)
    hourly.to_parquet(args.out / "weather_hourly.parquet", index=False)
    daily.to_parquet(args.out / "weather_daily.parquet", index=False)
    report["weather"] = {
        "hourly_rows": int(len(hourly)),
        "daily_rows": int(len(daily)),
        "hourly_from": str(hourly["timestamp"].min()),
        "hourly_to": str(hourly["timestamp"].max()),
    }
    print(f"  {len(hourly):,} hourly rows, {len(daily):,} daily rows")

    (args.out / "quality_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in ("delays", "rows_by_mode")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
