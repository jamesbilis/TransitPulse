from datetime import datetime, timezone
from functools import lru_cache
import os
from time import monotonic
import snowflake.connector
from snowflake.connector.errors import Error as SnowflakeError
import requests
from fastapi import FastAPI, HTTPException, Query
from zoneinfo import ZoneInfo

from backend.stop_photos import nearby_photo
from backend.trip_planner import router as planner_router

BOSTON_TIME = ZoneInfo("America/New_York")

app = FastAPI(title="TransitPulse API")
app.include_router(planner_router)

RED_LINE_STATIONS = {
    "harvard": "place-harsq",
    "park-street": "place-pktrm",
    "south-station": "place-sstat",
}


def mbta_payload(resource, params=None):
    try:
        response = requests.get(
            f"https://api-v3.mbta.com/{resource}", params=params, timeout=10
        )
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as error:
        raise HTTPException(status_code=502, detail="Could not reach the MBTA.") from error


@lru_cache(maxsize=4)
def route_catalog(_cache_window):
    return [
        {
            "id": item["id"],
            "type": item["attributes"]["type"],
            "name": item["attributes"]["long_name"],
            "short_name": item["attributes"]["short_name"],
            "description": item["attributes"]["description"],
            "color": item["attributes"]["color"],
            "text_color": item["attributes"]["text_color"],
        }
        for item in mbta_payload("routes")["data"]
    ]


@app.get("/api/routes")
def get_routes():
    return route_catalog(int(monotonic() // 300))


@lru_cache(maxsize=256)
def route_stops(route, _cache_window):
    return [
        {
            "id": item["id"],
            "name": item["attributes"]["name"],
            "latitude": item["attributes"].get("latitude"),
            "longitude": item["attributes"].get("longitude"),
        }
        for item in mbta_payload("stops", {"filter[route]": route})["data"]
    ]


@app.get("/api/routes/{route}/stops")
def get_route_stops(route: str):
    if not any(item["id"] == route for item in get_routes()):
        raise HTTPException(status_code=404, detail="Route is not supported.")
    return route_stops(route, int(monotonic() // 300))


@app.get("/api/routes/{route}/stop-photo")
def get_stop_photo(route: str, station: str, night: bool = False):
    stop = next((stop for stop in get_route_stops(route) if stop["id"] == station), None)
    if stop is None:
        raise HTTPException(status_code=404, detail="Stop is not served by this route.")
    latitude, longitude = stop["latitude"], stop["longitude"]
    if latitude is None or longitude is None:
        return None
    try:
        return nearby_photo(round(latitude, 4), round(longitude, 4), night, int(monotonic() // 3600))
    except (requests.RequestException, ValueError):
        return None


@lru_cache(maxsize=2)
def active_alerts(_cache_window):
    return mbta_payload(
        "alerts",
        {
            "filter[datetime]": "NOW",
            "filter[activity]": "ALL",
            "fields[alert]": "header,short_header,service_effect,severity,informed_entity",
            "include": "stops",
        },
    )


@app.get("/api/alerts")
def get_alerts(
    route: str = Query(min_length=1, max_length=128),
    station: str = Query(min_length=1, max_length=128),
):
    selected_route = next((item for item in get_routes() if item["id"] == route), None)
    if selected_route is None:
        raise HTTPException(status_code=404, detail="Route is not supported.")
    stop_ids = {stop["id"] for stop in route_stops(route, int(monotonic() // 300))}
    if station not in stop_ids:
        raise HTTPException(status_code=404, detail="Stop is not served by this route.")

    payload = active_alerts(int(monotonic() // 60))
    parents = {}
    for stop in payload.get("included", []):
        parent = stop.get("relationships", {}).get("parent_station", {}).get("data")
        if stop["type"] == "stop" and parent:
            parents[stop["id"]] = parent["id"]
    selected_stops = {station, parents.get(station, station)}

    def applies(entity):
        if entity.get("route") not in (None, route):
            return False
        if entity.get("route_type") not in (None, selected_route["type"]):
            return False
        stop = entity.get("stop")
        if stop:
            return stop in selected_stops or parents.get(stop) in selected_stops
        return bool(entity.get("route") or entity.get("route_type") is not None) or not (
            entity.get("facility") or entity.get("trip")
        )

    alerts = []
    for alert in payload["data"]:
        attributes = alert["attributes"]
        if not any(applies(entity) for entity in attributes.get("informed_entity", [])):
            continue
        headline = attributes.get("header") or attributes.get("short_header")
        if not headline:
            continue
        alerts.append({
            "id": alert["id"],
            "headline": headline,
            "effect": attributes.get("service_effect"),
            "severity": attributes.get("severity") or 0,
        })
    return sorted(alerts, key=lambda alert: alert["severity"], reverse=True)


@app.get("/api/arrivals")
def get_arrivals(
    station: str = Query(default="south-station", min_length=1, max_length=128),
    route: str = Query(default="Red", min_length=1, max_length=128),
):
    stop_id = RED_LINE_STATIONS.get(station, station)
    if route != "Red" or station not in RED_LINE_STATIONS:
        if not any(stop["id"] == stop_id for stop in get_route_stops(route)):
            raise HTTPException(status_code=404, detail="Stop is not served by this route.")

    payload = mbta_payload(
        "predictions", {"filter[stop]": stop_id, "filter[route]": route, "include": "trip"}
    )

    headsigns = {
        trip["id"]: trip["attributes"].get("headsign")
        for trip in payload.get("included", [])
        if trip["type"] == "trip"
    }
    now = datetime.now(timezone.utc)
    arrivals = []

    for prediction in payload["data"]:
        attributes = prediction["attributes"]
        predicted_time = attributes.get("arrival_time") or attributes.get("departure_time")
        if not predicted_time:
            continue

        arrival = datetime.fromisoformat(predicted_time)
        if arrival < now:
            continue

        trip_id = prediction["relationships"]["trip"]["data"]["id"]
        arrivals.append((arrival, headsigns.get(trip_id)))

    arrivals.sort(key=lambda item: item[0])
    return {
        "station": station,
        "route": route,
        "arrivals": [
            {"predicted_at": arrival.astimezone(BOSTON_TIME).isoformat(), "destination": destination,}
            for arrival, destination in arrivals[:8]
        ],
    }

@lru_cache(maxsize=2)
def open_meteo_weather(_cache_window):
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": 42.3601, "longitude": -71.0589,
                "current": "temperature_2m", "temperature_unit": "celsius",
                "timezone": "GMT",
            },
            timeout=6,
        )
        response.raise_for_status()
        current = response.json()["current"]
        observed_at = datetime.fromisoformat(current["time"]).replace(tzinfo=timezone.utc)
        return {
            "temperature_c": float(current["temperature_2m"]),
            "observed_at": observed_at.astimezone(BOSTON_TIME).isoformat(),
            "source": "open-meteo",
        }
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=502, detail="Could not read Boston weather.") from error


@app.get("/api/weather")
def get_weather():
    key_file = os.getenv("TRANSITPULSE_APP_SNOWFLAKE_KEY")
    passphrase = os.getenv("TRANSITPULSE_APP_SNOWFLAKE_PASSPHRASE")
    if not key_file or not passphrase:
        return open_meteo_weather(int(monotonic() // 300))

    try:
        with snowflake.connector.connect(
            account="RZJTSUN-NK39763",
            user="TRANSITPULSE_APP_USER",
            role="TRANSITPULSE_APP_READER",
            warehouse="COMPUTE_WH",
            authenticator="SNOWFLAKE_JWT",
            private_key_file=key_file,
            private_key_password=passphrase,
            login_timeout=10,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT temperature, observed_at_utc
                    FROM TRANSITPULSE.DBT_DEV.STG_WEATHER
                    WHERE temperature IS NOT NULL
                      AND temperature_unit = '°C'
                      AND observed_at_utc IS NOT NULL
                    ORDER BY observed_at_utc DESC, captured_at_utc DESC
                    LIMIT 1
                """)
                row = cursor.fetchone()
    except (SnowflakeError, OSError, ValueError) as error:
        print(f"Snowflake weather lookup failed: {type(error).__name__}")
        return open_meteo_weather(int(monotonic() // 300))

    if row is None:
        return open_meteo_weather(int(monotonic() // 300))

    temperature, observed_at = row
    return {
        "temperature_c": float(temperature),
        "observed_at": observed_at.replace(tzinfo=timezone.utc)
        .astimezone(BOSTON_TIME)
        .isoformat(),
    }
