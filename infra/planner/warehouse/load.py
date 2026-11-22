"""Load MBTA planner data after a Snowflake admin provisions the destination tables."""

import argparse
from datetime import date, datetime
import io
import json
import os
from pathlib import Path

import pyarrow.parquet as parquet
import requests
import snowflake.connector
from google.cloud import storage

VERSION_BASE = "https://performancedata.mbta.com/lamp/gtfs_archive"


def service_day(value):
    return datetime.strptime(str(value), "%Y%m%d").date()


def load(connection, bucket, day, alert_path):
    source = f"planner/lamp/service_date={day.isoformat()}/events.parquet"
    events = parquet.read_table(io.BytesIO(bucket.blob(source).download_as_bytes()))
    rows = {}
    for row in events.to_pylist():
        trip = row["trip_id"]
        stop = row["stop_id"]
        sequence = row["stop_sequence"]
        if not trip or not stop or not row["route_id"] or sequence is None or service_day(row["service_date"]) != day:
            continue
        epoch = row["stop_timestamp"]
        rows.setdefault((trip, stop, sequence), (
            day, trip, row["route_id"], stop, sequence, row["scheduled_arrival_time"], epoch,
            "source_reported" if epoch is not None else "missing", source,
        ))
    if not rows:
        raise ValueError(f"LAMP partition {source} is empty.")

    version_url = f"{VERSION_BASE}/{day.year}/feed_info.parquet"
    version_response = requests.get(version_url, timeout=40)
    version_response.raise_for_status()
    versions = parquet.read_table(io.BytesIO(version_response.content)).to_pylist()
    matched = [
        (service_day(row["gtfs_active_date"]), service_day(row["gtfs_end_date"]), row["feed_version"], version_url)
        for row in versions if row.get("feed_version")
        and row.get("gtfs_active_date") and row.get("gtfs_end_date")
        and service_day(row["gtfs_active_date"]) <= day <= service_day(row["gtfs_end_date"])
    ]
    if not matched:
        raise ValueError(f"No archived GTFS version covers {day}.")

    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM TRANSITPULSE.PUBLIC.PLANNER_STOP_EVENTS WHERE SERVICE_DATE = %s", (day,))
        records = list(rows.values())
        for index in range(0, len(records), 400):
            cursor.executemany(
                "INSERT INTO TRANSITPULSE.PUBLIC.PLANNER_STOP_EVENTS VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                records[index:index + 400],
            )
        for record in sorted(set(matched)):
            cursor.execute(
                """MERGE INTO TRANSITPULSE.PUBLIC.PLANNER_GTFS_VERSIONS target
                   USING (SELECT %s::date as active_date, %s::date as end_date,
                                 %s::varchar as feed_version, %s::varchar as source_file) source
                   ON target.active_date=source.active_date AND target.end_date=source.end_date
                      AND target.feed_version=source.feed_version
                   WHEN NOT MATCHED THEN INSERT (ACTIVE_DATE, END_DATE, FEED_VERSION, SOURCE_FILE)
                   VALUES (source.active_date,source.end_date,source.feed_version,source.source_file)""",
                record,
            )
        if alert_path:
            captured = datetime.strptime(Path(alert_path).stem.removeprefix("mbta_alerts_"), "%Y%m%dT%H%M%SZ")
            payload = json.loads(bucket.blob(alert_path).download_as_bytes())
            records = {alert["id"]: alert["attributes"] for alert in payload["data"]}
            cursor.execute(
                """MERGE INTO TRANSITPULSE.PUBLIC.PLANNER_ALERT_SNAPSHOTS target
                   USING (SELECT %s::timestamp_ntz as captured_at_utc, key as alert_id, value as attributes
                          FROM TABLE(FLATTEN(INPUT => PARSE_JSON(%s)))) source
                   ON target.captured_at_utc=source.captured_at_utc AND target.alert_id=source.alert_id
                   WHEN NOT MATCHED THEN INSERT (CAPTURED_AT_UTC, ALERT_ID, ATTRIBUTES)
                   VALUES (source.captured_at_utc,source.alert_id,source.attributes)""",
                (captured, json.dumps(records)),
            )
    print(f"Loaded {len(rows)} stop events for {day} into Snowflake.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service_date", type=date.fromisoformat)
    parser.add_argument("--alert-path", help="Optional existing GCS raw MBTA alert JSON object")
    args = parser.parse_args()
    bucket = storage.Client().bucket(os.environ["TRANSITPULSE_GCS_BUCKET"])
    with snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        role="TRANSITPULSE_LOADER",
        warehouse="COMPUTE_WH",
        private_key_file=os.environ["TRANSITPULSE_SNOWFLAKE_KEY"],
        private_key_file_pwd=os.getenv("TRANSITPULSE_SNOWFLAKE_PASSPHRASE"),
        authenticator="SNOWFLAKE_JWT",
        autocommit=False,
    ) as connection:
        load(connection, bucket, args.service_date, args.alert_path)
