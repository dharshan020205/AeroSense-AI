import os
from functools import lru_cache

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sklearn.ensemble import RandomForestRegressor, HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data", "cpcb-aqi.csv.gz")
app = FastAPI(title="AeroSense AI API", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:5174,http://localhost:5175,http://127.0.0.1:5173,http://127.0.0.1:5174,http://127.0.0.1:5175").split(","),
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

HOURS = [f"{h:02d}:00:00" for h in range(24)]
LAGS = [1, 2, 3, 6, 12, 24, 48]
MIN_TRAIN_ROWS = 300
_cache = {"raw": None, "mtime": None}


def load():
    if not os.path.exists(DATA):
        raise HTTPException(404, "CPCB dataset missing. Keep cpcb-aqi.csv.gz in backend/data/.")
    mtime = os.path.getmtime(DATA)
    if _cache["raw"] is None or _cache["mtime"] != mtime:
        _cache["raw"] = pd.read_csv(DATA, compression="gzip")
        _cache["mtime"] = mtime
    return _cache["raw"]


def long_station(raw, station_id):
    if "::" in str(station_id):
        source_id, station_name = str(station_id).split("::", 1)
        part = raw[(raw["Station ID"].astype(str) == source_id) &
                   (raw["Station Name"].astype(str) == station_name)].copy()
    else:
        part = raw[raw["Station ID"].astype(str) == str(station_id)].copy()
    if part.empty:
        return pd.DataFrame(columns=["timestamp", "AQI"])
    cols = [c for c in HOURS if c in part.columns]
    x = part.melt(id_vars=["Station ID", "State", "City", "Station Name", "Date"],
                  value_vars=cols, var_name="hour", value_name="AQI")
    x["timestamp"] = pd.to_datetime(x["Date"], errors="coerce") + pd.to_timedelta(
        x["hour"].str[:2].astype(int), unit="h")
    x["AQI"] = pd.to_numeric(x["AQI"], errors="coerce")
    x = x.dropna(subset=["timestamp", "AQI"])
    x = x[(x.AQI >= 0) & (x.AQI <= 1000)].sort_values("timestamp")
    return x.drop_duplicates("timestamp", keep="last")[["timestamp", "AQI"]]


def band(v):
    if v <= 50: return "Good"
    if v <= 100: return "Satisfactory"
    if v <= 200: return "Moderate"
    if v <= 300: return "Poor"
    if v <= 400: return "Very Poor"
    return "Severe"


def feature_frame(series):
    """Features at time t use only observations available at or before t."""
    s = series.sort_index().asfreq("h")
    d = pd.DataFrame(index=s.index)
    for lag in LAGS:
        d[f"lag_{lag}"] = s.shift(lag)
    prior = s.shift(1)
    d["mean6"] = prior.rolling(6, min_periods=6).mean()
    d["mean24"] = prior.rolling(24, min_periods=24).mean()
    d["std24"] = prior.rolling(24, min_periods=24).std()
    ix = d.index
    d["hour_sin"] = np.sin(2 * np.pi * ix.hour / 24)
    d["hour_cos"] = np.cos(2 * np.pi * ix.hour / 24)
    d["dow_sin"] = np.sin(2 * np.pi * ix.dayofweek / 7)
    d["dow_cos"] = np.cos(2 * np.pi * ix.dayofweek / 7)
    d["month_sin"] = np.sin(2 * np.pi * ix.month / 12)
    d["month_cos"] = np.cos(2 * np.pi * ix.month / 12)
    return s, d


def make_model(name):
    if name == "HistGradientBoosting":
        return HistGradientBoostingRegressor(max_iter=160, learning_rate=0.06,
                    max_leaf_nodes=18, l2_regularization=1.0, random_state=42)
    return RandomForestRegressor(n_estimators=100, max_depth=15, min_samples_leaf=2,
                                 max_features=0.9, n_jobs=-1, random_state=42)


def evaluate(y_true, pred):
    return {
        "mae": round(float(mean_absolute_error(y_true, pred)), 3),
        "rmse": round(float(mean_squared_error(y_true, pred) ** 0.5), 3),
        "r2": round(float(r2_score(y_true, pred)), 4) if len(y_true) > 1 else None
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "AeroSense AI API", "version": "2.0"}


@app.get("/api/cities")
def cities():
    r = load()
    g = r.groupby(["State", "City"]).agg(
        stations=("Station Name", "nunique"), records=("Date", "size")).reset_index()
    return {"cities": g.sort_values("City").to_dict("records")}


@app.get("/api/stations/{city}")
def stations(city: str):
    r = load()
    x = r[r.City.astype(str) == city]
    if x.empty:
        raise HTTPException(404, "City not found")
    st = x[["Station ID", "Station Name", "State"]].drop_duplicates().sort_values("Station Name")
    out = []
    for row in st.to_dict("records"):
        source_id = str(row["Station ID"])
        station_name = str(row["Station Name"])
        station_key = source_id + "::" + station_name
        obs = long_station(r, station_key)
        series = obs.set_index("timestamp")["AQI"] if not obs.empty else pd.Series(dtype=float)
        _, feats = feature_frame(series)
        usable = int(feats.notna().all(axis=1).sum())
        row["source_station_id"] = source_id
        row["Station ID"] = station_key
        row.update({"observations": int(len(obs)), "training_rows": usable,
                    "forecast_ready": usable >= MIN_TRAIN_ROWS})
        out.append(row)
    return {"stations": out, "minimum_training_rows": MIN_TRAIN_ROWS}


@app.get("/api/observations/{station_id}")
def observations(station_id: str, limit: int = 336):
    r = load()
    x = long_station(r, station_id)
    if x.empty:
        raise HTTPException(404, "No observations for this station.")
    x = x.tail(max(24, min(limit, 2000)))
    records = [{"timestamp": t.isoformat(), "aqi": float(v), "category": band(float(v))}
               for t, v in zip(x.timestamp, x.AQI)]
    return {"observations": records, "latest": records[-1], "count": int(len(x)),
            "start": x.timestamp.min().isoformat(), "end": x.timestamp.max().isoformat()}


@app.post("/api/forecast/{station_id}")
def forecast(station_id: str, horizon: int = 6, model_name: str = "Random Forest"):
    if horizon not in [1, 3, 6, 12, 24]:
        raise HTTPException(400, "Choose a forecast horizon of 1, 3, 6, 12 or 24 hours.")
    if model_name not in ["Random Forest", "HistGradientBoosting"]:
        raise HTTPException(400, "Unsupported model.")
    raw = load()
    frame = long_station(raw, station_id)
    if frame.empty:
        raise HTTPException(404, "No observations for this station.")
    series = frame.set_index("timestamp")["AQI"].sort_index()
    series = series[~series.index.duplicated(keep="last")]
    s, features = feature_frame(series)
    complete_features = features.dropna()
    if complete_features.empty:
        raise HTTPException(400, "This station does not have enough continuous hourly history to forecast.")
    latest_features = complete_features.iloc[[-1]]
    forecast_origin = latest_features.index[-1]
    if (s.index.max() - forecast_origin) > pd.Timedelta(hours=6):
        raise HTTPException(400, "The latest usable feature window is more than six hours behind the latest record.")
    future = []
    selected_metrics = None
    selected_holdout = []
    baseline_metrics = None
    uncertainty = None
    split_index = None

    # Direct horizon models: each target is exactly t + step hours.
    # The features always end at t, preventing recursive use of unknown future values.
    for step in range(1, horizon + 1):
        target = s.shift(-step).rename("target")
        supervised = features.join(target).dropna()
        if len(supervised) < MIN_TRAIN_ROWS + 50:
            raise HTTPException(400, f"Only {len(supervised)} usable examples for a {step}-hour model; at least {MIN_TRAIN_ROWS + 50} are required. Try a station with a longer, more continuous history.")
        X = supervised.drop(columns="target")
        y = supervised["target"]
        split = int(len(supervised) * 0.8)
        if split < MIN_TRAIN_ROWS or len(supervised) - split < 30:
            raise HTTPException(400, "Insufficient chronological train/test samples.")
        model = make_model(model_name)
        model.fit(X.iloc[:split], y.iloc[:split])
        test_pred = np.clip(model.predict(X.iloc[split:]), 0, 1000)
        actual = y.iloc[split:]
        metrics = evaluate(actual, test_pred)
        persistence = X.iloc[split:]["lag_1"].to_numpy()
        baseline = evaluate(actual, persistence)
        residual = np.abs(actual.to_numpy() - test_pred)
        q90 = float(np.quantile(residual, 0.90))
        point = float(np.clip(model.predict(latest_features)[0], 0, 1000))
        future.append({
            "step": step,
            "timestamp": (forecast_origin + pd.Timedelta(hours=step)).isoformat(),
            "forecast": round(point, 2),
            "category": band(point),
            "lower": round(max(0, point - q90), 2),
            "upper": round(min(1000, point + q90), 2)
        })
        if step == horizon:
            selected_metrics = metrics
            baseline_metrics = baseline
            uncertainty = {"method": "90th percentile absolute chronological holdout error",
                           "half_width": round(q90, 2)}
            split_index = split
            selected_holdout = [
                {"timestamp": (t + pd.Timedelta(hours=step)).isoformat(),
                 "actual": float(a), "predicted": float(p)}
                for t, a, p in zip(X.iloc[split:].index[-240:],
                                   actual.iloc[-240:].to_numpy(), test_pred[-240:])
            ]

    return {
        "metrics": {**selected_metrics, "train_samples": int(split_index),
                    "test_samples": int(len(supervised) - split_index)},
        "baseline": baseline_metrics,
        "holdout": selected_holdout,
        "future": future,
        "model": model_name,
        "horizon": horizon,
        "evaluation": "Direct horizon-specific prediction on a chronological 80/20 holdout",
        "uncertainty": uncertainty,
        "data_mode": "historical",
        "forecast_origin": forecast_origin.isoformat(),
        "target": "AQI"
    }


@app.get("/api/station-readiness/{station_id}")
def station_readiness(station_id: str):
    r = load()
    x = long_station(r, station_id)
    if x.empty:
        raise HTTPException(404, "No observations for this station.")
    s = x.set_index("timestamp")["AQI"]
    _, f = feature_frame(s)
    usable = int(f.notna().all(axis=1).sum())
    return {"observations": int(len(x)), "training_rows": usable,
            "minimum_training_rows": MIN_TRAIN_ROWS,
            "forecast_ready": usable >= MIN_TRAIN_ROWS,
            "first": x.timestamp.min().isoformat(), "last": x.timestamp.max().isoformat()}


# Serve the production React build from the same origin when deployed as a container.
STATIC_DIR = os.path.join(os.path.dirname(BASE), "frontend", "dist")
if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")
