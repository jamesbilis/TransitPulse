import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests


TIMEOUT_SECONDS = 15
OUTPUT_DIR = Path("data/raw")

SOURCES = {
    "mbta_alerts": {
        "url": "https://api-v3.mbta.com/alerts",
        "params": {"page[limit]": 100},
        "expected_key": "data",
        "expected_type": list,
    },
    "open_meteo": {
        "url": "https://api.open-meteo.com/v1/forecast",
        "params": {
            "latitude": 42.3601,
            "longitude": -71.0589,
            "current": "temperature_2m,precipitation",
            "timezone": "America/New_York",
        },
        "expected_key": "current",
        "expected_type": dict,
    },
}


def fetch_json(source):
    response = requests.get(
        source["url"],
        params=source["params"],
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()

    value = payload.get(source["expected_key"])
    if not isinstance(value, source["expected_type"]):
        raise ValueError(
            f"Response did not contain expected {source['expected_key']} data"
        )

    return payload


def save_json(name, payload, timestamp):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{name}_{timestamp}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path

def upload_snapshots(bucket_name, snapshots, capture_date):
    from google.cloud import storage

    bucket = storage.Client().bucket(bucket_name)
    objects = {}

    for source_name, path in snapshots:
        key = f"raw/{source_name}/date={capture_date}/{path.name}"
        bucket.blob(key).upload_from_filename(
            str(path),
            content_type="application/json",
            if_generation_match=0,
        )
        objects[source_name] = key
        print(f"Uploaded gs://{bucket_name}/{key}")

    return objects

def main():
    captured_at = datetime.now(timezone.utc)
    timestamp = captured_at.strftime("%Y%m%dT%H%M%SZ")
    snapshots = []

    try:
        for name, source in SOURCES.items():
            payload = fetch_json(source)
            path = save_json(name, payload, timestamp)
            snapshots.append((name, path))
            print(f"Saved {name} data to {path}")
        bucket_name = os.getenv("TRANSITPULSE_GCS_BUCKET")
        objects = {}
        if bucket_name:
            objects = upload_snapshots(
                bucket_name, snapshots, captured_at.date().isoformat()
            )

        print(json.dumps({
            "capture_timestamp": timestamp,
            "bucket": bucket_name,
            "objects": objects,
        }))
    except (requests.RequestException, ValueError) as error:
        print(f"Ingestion failed: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
