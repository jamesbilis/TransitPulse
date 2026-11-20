import sys

import requests

TIMEOUT_SECONDS = 15


def check_mbta():
    response = requests.get(
        "https://api-v3.mbta.com/alerts",
        params={"page[limit]": 1},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json().get("data")
    if not isinstance(data, list):
        raise ValueError("MBTA response did not contain a data list")
    return f"{len(data)} alert record(s) returned"


def check_open_meteo():
    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": 42.3601,
            "longitude": -71.0589,
            "current": "temperature_2m,precipitation",
            "timezone": "America/New_York",
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    current = response.json().get("current")
    if not isinstance(current, dict):
        raise ValueError("Open-Meteo response did not contain current conditions")
    return f"current weather returned for {current.get('time')}"


def main():
    failed = False
    for name, check in (("MBTA", check_mbta), ("Open-Meteo", check_open_meteo)):
        try:
            print(f"{name}: OK — {check()}")
        except (requests.RequestException, ValueError) as error:
            failed = True
            print(f"{name}: FAILED — {error}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
