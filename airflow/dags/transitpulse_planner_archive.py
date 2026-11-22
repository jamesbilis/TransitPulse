"""Separately archive planner inputs in GCS for reproducible future backtests."""

from datetime import timedelta

from airflow.sdk import DAG, get_current_context, task
from pendulum import datetime


@task
def archive_sources(products):
    import hashlib
    import os

    import requests
    from google.api_core.exceptions import PreconditionFailed
    from google.cloud import storage

    name = os.environ["TRANSITPULSE_GCS_BUCKET"]
    bucket = storage.Client().bucket(name)
    from pendulum import instance, now

    context = get_current_context()
    interval = context.get("data_interval_end") or context.get("logical_date")
    captured = instance(interval).in_timezone("UTC") if interval else now("UTC")
    day = captured.in_timezone("America/New_York").subtract(days=2).to_date_string()
    stamp = captured.format("YYYYMMDDTHHmmss[Z]")
    sources = {
        "gtfs": ("https://cdn.mbta.com/MBTA_GTFS.zip", None, "application/zip"),
        "lamp": (
            f"https://performancedata.mbta.com/lamp/subway-on-time-performance-v1/{day}-subway-on-time-performance-v1.parquet",
            f"planner/lamp/service_date={day}/events.parquet", "application/octet-stream",
        ),
    }
    sources.update({
        kind: (
            f"https://cdn.mbta.com/realtime/{feed}.pb",
            f"planner/realtime/{kind}/date={captured.to_date_string()}/{stamp}.pb", "application/x-protobuf",
        )
        for kind, feed in (("trip_updates", "TripUpdates"), ("vehicle_positions", "VehiclePositions"),
                           ("alerts", "Alerts"))
    })
    for product in products:
        url, key, content_type = sources[product]
        response = requests.get(url, timeout=40)
        response.raise_for_status()
        payload = response.content
        if not payload:
            raise ValueError(f"The MBTA returned an empty {product} feed.")
        if product == "gtfs":
            digest = hashlib.sha256(payload).hexdigest()
            key = f"planner/gtfs/sha256={digest}/mbta.gtfs.zip"
        blob = bucket.blob(key)
        blob.metadata = {"source": url, "captured_at_utc": captured.to_iso8601_string()}
        try:
            blob.upload_from_string(payload, content_type=content_type, if_generation_match=0)
        except PreconditionFailed:
            print(f"Already archived gs://{name}/{key}")
        else:
            print(f"Archived gs://{name}/{key}")


with DAG(
    dag_id="transitpulse_planner_realtime_archive",
    start_date=datetime(2026, 11, 22, tz="UTC"),
    schedule="*/15 * * * *",
    catchup=False,
    is_paused_upon_creation=True,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=2)},
) as realtime_archive:
    archive_sources(["trip_updates", "vehicle_positions", "alerts"])

with DAG(
    dag_id="transitpulse_planner_daily_archive",
    start_date=datetime(2026, 11, 22, tz="UTC"),
    schedule="0 13 * * *",
    catchup=False,
    is_paused_upon_creation=True,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=20)},
) as daily_archive:
    archive_sources(["gtfs", "lamp"])
