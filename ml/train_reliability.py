"""Build a chronological LAMP delay backtest and a serving lookup for supported stops."""

import argparse
import io
import json
import os
from pathlib import Path

import pandas as pd
import pyarrow.parquet as parquet
import requests
import xgboost as xgb

BASE = "https://performancedata.mbta.com/lamp/subway-on-time-performance-v1"
COLUMNS = [
    "service_date", "trip_id", "route_id", "stop_id", "stop_sequence",
    "stop_timestamp", "scheduled_arrival_time",
]
FEATURES = ["route", "stop", "hour", "weekend"]
ROOT = Path(__file__).resolve().parents[1]


def download(url):
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.content


def observed_events(cache, days, today):
    cache.mkdir(parents=True, exist_ok=True)
    index = pd.read_csv(io.BytesIO(download(f"{BASE}/index.csv")), usecols=["service_date"])
    dates = sorted(set(date for date in index["service_date"] if date < today))[-days:]
    if len(dates) < days:
        raise ValueError(f"Expected {days} complete partitions, found {len(dates)}")
    partitions = []
    for date in dates:
        name = f"{date}-subway-on-time-performance-v1.parquet"
        path = cache / name
        if not path.exists():
            payload = download(f"{BASE}/{name}")
            pending = path.with_suffix(".tmp")
            pending.write_bytes(payload)
            pending.replace(path)
        table = parquet.read_table(path, columns=COLUMNS)
        partitions.append(table.to_pandas())

    data = pd.concat(partitions, ignore_index=True).dropna(subset=COLUMNS)
    data = data.loc[~data["trip_id"].str.startswith("ADDED-")].copy()
    data = data.drop_duplicates(["service_date", "trip_id", "stop_id", "stop_sequence"])
    service_day = pd.to_datetime(data["service_date"].astype(str), format="%Y%m%d")
    # GTFS times use the local-noon-minus-12-hours service-day origin.
    noon = (service_day + pd.Timedelta(hours=12)).dt.tz_localize("America/New_York")
    scheduled = noon - pd.Timedelta(hours=12) + pd.to_timedelta(data["scheduled_arrival_time"], unit="s")
    data["delay"] = data["stop_timestamp"] - (scheduled - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds()
    data["hour"] = scheduled.dt.hour
    data["weekend"] = (scheduled.dt.day_of_week >= 5).astype(int)
    data = data.loc[data["delay"].between(-900, 3600)].copy()
    return data, dates


def train(cache, output, days):
    today = pd.Timestamp.now(tz="America/New_York").strftime("%Y-%m-%d")
    events, days_used = observed_events(cache, days, today)
    cutoff = int(days_used[-max(2, days // 5)].replace("-", ""))
    training = events.loc[events["service_date"] < cutoff].copy()
    test = events.loc[events["service_date"] >= cutoff].copy()
    route_codes = {value: index for index, value in enumerate(sorted(training["route_id"].unique()))}
    stop_codes = {value: index for index, value in enumerate(sorted(training["stop_id"].unique()))}
    for split in (training, test):
        split["route"] = split["route_id"].map(route_codes)
        split["stop"] = split["stop_id"].map(stop_codes)
    test = test.dropna(subset=["route", "stop"])
    if training.empty or test.empty:
        raise ValueError("The data does not contain enough matching training and test rows.")

    grids = training[["route_id", "stop_id", *FEATURES]].drop_duplicates().copy()
    counts = training.groupby(FEATURES).size().rename("count")
    grids = grids.join(counts, on=FEATURES)
    grids = grids.loc[grids["count"] >= 8]
    metric = {"train_rows": len(training), "test_rows": len(test), "test_start": cutoff}
    baseline = training.groupby(["route_id", "stop_id"])["delay"].median()
    historical = test.join(baseline.rename("median"), on=["route_id", "stop_id"])["median"]
    metric["schedule_mae_seconds"] = round(test["delay"].abs().mean(), 1)
    metric["median_mae_seconds"] = round((test["delay"] - historical).abs().mean(), 1)
    predictions = {}
    train_matrix = xgb.DMatrix(training[FEATURES], label=training["delay"], nthread=2)
    test_matrix = xgb.DMatrix(test[FEATURES], nthread=2)
    grid_matrix = xgb.DMatrix(grids[FEATURES], nthread=2)
    for quantile in (0.5, 0.9):
        model = xgb.train(
            {"objective": "reg:quantileerror", "quantile_alpha": quantile, "tree_method": "hist",
             "max_depth": 5, "eta": 0.09, "nthread": 2, "seed": 11},
            train_matrix,
            num_boost_round=125,
        )
        predictions[quantile] = model.predict(test_matrix)
        grids[f"p{int(quantile * 100)}"] = model.predict(grid_matrix)
        model.save_model(output.parent / f"delay-p{int(quantile * 100)}.json")
    metric["xgboost_mae_seconds"] = round((test["delay"] - predictions[0.5]).abs().mean(), 1)
    metric["p90_test_coverage"] = round((test["delay"] <= predictions[0.9]).mean(), 3)
    buffers = {
        f"{row.route_id}|{row.stop_id}|{row.hour}|{row.weekend}": round(max(0, row.p90 - row.p50))
        for row in grids.itertuples(index=False)
    }
    grids["spread"] = (grids["p90"] - grids["p50"]).clip(lower=0)
    fallback = grids.groupby(["route_id", "stop_id", "weekend"])["spread"].median()
    buffers.update({
        f"{route}|{stop}|*|{weekend}": round(spread)
        for (route, stop, weekend), spread in fallback.items()
    })
    artifact = {"dates": days_used, "metrics": metric, "buffers": buffers}
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(artifact))
    temporary.replace(output)
    experiment = os.getenv("TRANSITPULSE_MLFLOW_EXPERIMENT")
    if experiment:
        import mlflow

        if os.getenv("DATABRICKS_RUNTIME_VERSION"):
            mlflow.set_tracking_uri("databricks")
            mlflow.set_registry_uri("databricks-uc")
        mlflow.set_experiment(experiment)
        with mlflow.start_run(run_name="mbta-lamp-delay"):
            mlflow.log_params({"days": days, "source": BASE, "features": ",".join(FEATURES)})
            mlflow.log_metrics(metric)
            for path in (output, output.parent / "delay-p50.json", output.parent / "delay-p90.json"):
                mlflow.log_artifact(str(path))
    print(json.dumps(metric, indent=2))
    return metric


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--cache", type=Path, default=ROOT / "data/lamp")
    parser.add_argument("--output", type=Path, default=ROOT / "data/planner/reliability.json")
    args = parser.parse_args()
    if not 7 <= args.days <= 90:
        parser.error("--days must be between 7 and 90")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    train(args.cache, args.output, args.days)
