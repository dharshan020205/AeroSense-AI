# AeroSense AI — Predictive Air Quality Forecasting

A React + FastAPI research prototype that uses historical CPCB-derived hourly AQI observations to forecast future AQI for individual Indian monitoring stations.

## Important scope and data integrity
- The supplied dataset contains hourly AQI values in daily wide-format records, covering **1 Jan 2017 to 31 Dec 2023**.
- This build forecasts **AQI**, not PM2.5 concentration.
- It operates in **historical-data mode**. It is not connected to a live sensor or live CPCB feed.
- The dashboard never fabricates monitoring observations.
- Stations are identified by both source station ID and station name because the supplied extract reuses source IDs across multiple named stations.
- Stations with fewer than 300 complete feature rows are marked as not forecast-ready. Tiruchirappalli's supplied station has only 41 usable feature rows, so forecasting is correctly disabled there. Use a station with sufficient history (e.g. Ooty or a major-city station) for the demonstration.

## What is implemented
- React dashboard with Overview, Forecast Studio, City Intelligence and Methodology pages.
- FastAPI endpoints for health, city inventory, station inventory, observations, station readiness and forecasts.
- Station-specific data extraction using both station ID and station name.
- Historical AQI trend chart and station selection.
- Random Forest and HistGradientBoosting regressors.
- Direct horizon-specific forecasts for 1, 3, 6, 12 and 24 hours. Each lead-time model predicts from the latest available historical feature row; it does not feed unknown future predictions back as if they were measurements.
- Time-based features, historical lags and rolling statistics.
- Chronological 80/20 holdout evaluation with MAE, RMSE and R².
- Persistence baseline (carry the last observed AQI forward) for comparison.
- Empirical uncertainty bands based on the 90th percentile absolute error on the chronological holdout.
- Data sufficiency checks and clear historical-data limitations.

## Run on Windows

Extract the project ZIP. Keep the `backend` and `frontend` folders together.

### Terminal 1 — backend
```powershell
cd path	o\AeroSense_AI_Completeackend
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Check the API at http://127.0.0.1:8000/api/health

### Terminal 2 — frontend
```powershell
cd path	o\AeroSense_AI_Completerontend
npm install
npm run dev
```

Open the exact local URL printed by Vite (normally http://localhost:5173).

## Suggested demonstration
1. Open Overview and show the historical AQI trend.
2. Open City Intelligence and search for Ooty or Delhi.
3. Select a station with at least 300 training rows. The station dropdown shows the usable row count.
4. Open Forecast Studio, choose HistGradientBoosting or Random Forest, select 3 or 6 hours, and run the forecast.
5. Explain the selected-horizon holdout metrics, persistence baseline and empirical uncertainty range.
6. Select Tiruchirappalli and explain why the system disables forecasting: its supplied station history is too short for a defensible model.

## API
- `GET /api/health`
- `GET /api/cities`
- `GET /api/stations/{city}`
- `GET /api/observations/{station_id}?limit=336`
- `GET /api/station-readiness/{station_id}`
- `POST /api/forecast/{station_id}?horizon=6&model_name=Random%20Forest`

The station identifier returned by `/api/stations/{city}` is a composite `source_station_id::station_name` key. URL-encode it when calling the API.

## Methodology and limitations
Feature rows at time *t* use only historical AQI observations available at or before *t*. For a requested lead time *h*, the target is AQI at *t+h*. Each lead time is evaluated using its own chronological holdout. The persistence baseline uses the most recent observed AQI value. No random train/test shuffle is used.

The displayed uncertainty range is an empirical residual band, not a guaranteed statistical prediction interval. The model currently does not incorporate weather forecasts, traffic, emissions, satellite data or sudden unobserved events. It is a student research prototype and must not be presented as an official public warning service.

## Folder structure
```text
AeroSense_AI_Complete/
  backend/
    main.py
    requirements.txt
    data/cpcb-aqi.csv.gz
  frontend/
    index.html
    package.json
    package-lock.json
    src/main.jsx
    src/style.css
  README.md
```

## Publish to your GitHub repository (Windows)

This project includes `push_to_github.ps1`. From PowerShell, after extracting the folder, run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\push_to_github.ps1
```

Git for Windows must be installed. Git Credential Manager will prompt you to authenticate with GitHub if needed. The script initializes the local repository, creates the first commit, and pushes the `main` branch to `dharshan020205/AeroSense-AI`.
