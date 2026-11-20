import json
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


def main():
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    try:
        for name, source in SOURCES.items():
            payload = fetch_json(source)
            path = save_json(name, payload, timestamp)
            print(f"Saved {name} data to {path}")
    except (requests.RequestException, ValueError) as error:
        print(f"Ingestion failed: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
