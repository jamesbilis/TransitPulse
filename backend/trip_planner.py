import csv
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from itertools import permutations
import io
import json
import os
from pathlib import Path
import re
from zipfile import ZipFile
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import AwareDatetime, BaseModel, Field, StringConstraints
from typing import Annotated
import requests

router = APIRouter(prefix="/api/planner", tags=["trip planner"])
BOSTON = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[1]
PlaceName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=180)]
MODES = "BUS, RAIL, SUBWAY, TRAM, FERRY"


class TripRequest(BaseModel):
    origin: PlaceName
    destination: PlaceName
    depart_at: AwareDatetime | None = None
    arrive_by: AwareDatetime | None = None


class Visit(BaseModel):
    place: PlaceName
    arrive_by: AwareDatetime | None = None
    minutes: int = Field(default=0, ge=0, le=480)
    flexible: bool = False


class ItineraryRequest(BaseModel):
    origin: PlaceName
    depart_at: AwareDatetime | None = None
    visits: list[Visit] = Field(min_length=1, max_length=6)


class ChatMessage(BaseModel):
    role: Annotated[str, StringConstraints(pattern="^(user|assistant)$")]
    content: Annotated[str, StringConstraints(min_length=1, max_length=1800)]


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=12)


def key(text):
    return re.sub(r"[^a-z0-9]", "", text.casefold())


@lru_cache(maxsize=2)
def gtfs_places(path, _mtime):
    with ZipFile(path) as archive, archive.open("stops.txt") as source:
        stops = sorted(csv.DictReader(io.TextIOWrapper(source, encoding="utf-8-sig")),
                       key=lambda stop: stop["location_type"] != "1")
    places = {}
    for stop in stops:
        if stop["stop_lat"] and stop["stop_lon"]:
            point = (float(stop["stop_lat"]), float(stop["stop_lon"]), stop["stop_name"])
            places.setdefault(key(stop["stop_name"]), point)
            places.setdefault(key(stop["stop_id"]), point)
    return places


def resolve_place(name):
    match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*", name)
    if match:
        lat, lon = map(float, match.groups())
        if 41 <= lat <= 43.5 and -73 <= lon <= -69:
            return lat, lon, name
        raise HTTPException(422, "Enter coordinates within the MBTA service area.")

    path = Path(os.getenv("TRANSITPULSE_GTFS", ROOT / "data/planner/mbta.gtfs.zip"))
    if path.exists():
        places = gtfs_places(path, path.stat().st_mtime_ns)
        name_key = key(name)
        match = places.get(name_key) or places.get(name_key.removesuffix("station"))
        if match:
            return match

    # Only submitted place names that do not match GTFS are sent to the geocoder.
    geocoder = os.getenv("TRANSITPULSE_GEOCODER_URL", "https://photon.komoot.io/api")
    if geocoder:
        try:
            response = requests.get(geocoder, params={
                "q": name, "limit": 1, "bbox": "-73,41,-69,43.5",
            }, headers={"User-Agent": "TransitPulse/1.0; local transit planner", "Accept": "application/json"}, timeout=8)
            response.raise_for_status()
            features = response.json()["features"]
        except (requests.RequestException, ValueError, KeyError) as error:
            raise HTTPException(502, "Address search is temporarily unavailable.") from error
        if features:
            result = features[0]
            lon, lat = result["geometry"]["coordinates"]
            if 41 <= lat <= 43.5 and -73 <= lon <= -69:
                return lat, lon, name
    raise HTTPException(422, f"Could not find {name}. Try an MBTA stop name or latitude, longitude.")


def normalize_route(route_id):
    return route_id.split(":", 1)[-1]


@lru_cache(maxsize=2)
def read_reliability(path, _mtime):
    data = json.loads(path.read_text())
    return data["buffers"]


def historical_buffer(legs):
    path = Path(os.getenv("TRANSITPULSE_RELIABILITY", ROOT / "data/planner/reliability.json"))
    if not path.exists():
        return None
    buffers = read_reliability(path, path.stat().st_mtime_ns)
    last_transit = next((leg for leg in reversed(legs) if leg["route_id"]), None)
    if last_transit is None:
        return None
    actual = datetime.fromisoformat(last_transit["scheduled_arrival"] or last_transit["arrival"]).astimezone(BOSTON)
    route, stop = last_transit["route_id"], last_transit["to_stop_id"]
    hk = f"{route}|{stop}|{actual.hour}|{int(actual.weekday() >= 5)}"
    fallback = f"{route}|{stop}|*|{int(actual.weekday() >= 5)}"
    buffer = buffers.get(hk, buffers.get(fallback))
    return round(buffer) if buffer is not None else None


def otp_options(origin, destination, when, arrive_by=False):
    url = os.getenv("TRANSITPULSE_OTP_URL", "http://127.0.0.1:8081/otp/gtfs/v1")
    time_field = "latestArrival" if arrive_by else "earliestDeparture"
    transit = ", ".join("{mode: " + mode + "}" for mode in MODES.split(", "))
    query = """
    { planConnection(
      origin: {location: {coordinate: {latitude: @OLAT, longitude: @OLON}}}
      destination: {location: {coordinate: {latitude: @DLAT, longitude: @DLON}}}
      dateTime: {@TIME_FIELD: @TIME}
      modes: {direct: [WALK], transit: {transit: [@MODES]}}
      first: 10
    ) { edges { node {
      start end
      legs {
        mode
        from { name departure { scheduledTime estimated { time } } }
        to { name stop { gtfsId } arrival { scheduledTime estimated { time } } }
        route { gtfsId longName shortName }
      }
    } } } }
    """
    for token, value in {
        "@OLAT": origin[0], "@OLON": origin[1], "@DLAT": destination[0], "@DLON": destination[1],
        "@TIME_FIELD": time_field, "@TIME": json.dumps(when.isoformat(timespec="seconds")),
        "@MODES": transit,
    }.items():
        query = query.replace(token, str(value))
    try:
        response = requests.post(url, json={"query": query}, timeout=12)
        response.raise_for_status()
        result = response.json()
        if result.get("errors"):
            raise ValueError(result["errors"][0]["message"])
        return result["data"]["planConnection"]["edges"]
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        raise HTTPException(502, "The trip routing service is temporarily unavailable.") from error


def plan_trip(trip, origin=None, destination=None):
    if trip.depart_at and trip.arrive_by:
        raise HTTPException(422, "Choose either depart at or arrive by for a single trip.")
    when = trip.arrive_by or trip.depart_at or datetime.now(timezone.utc)
    origin = origin or resolve_place(trip.origin)
    destination = destination or resolve_place(trip.destination)
    options = []
    for edge in otp_options(origin, destination, when, bool(trip.arrive_by)):
        node = edge["node"]
        legs = []
        for leg in node["legs"]:
            start, end = leg["from"], leg["to"]
            departure, arrival = start["departure"], end["arrival"]
            route = leg["route"] or {}
            route_id = normalize_route(route["gtfsId"]) if route else None
            to_stop = end["stop"]
            legs.append({
                "mode": leg["mode"], "from": start["name"], "to": end["name"],
                "route_id": route_id, "route": (route.get("longName") if leg["mode"] in {"SUBWAY", "TRAM", "RAIL"} else route.get("shortName")) or route.get("longName") or route_id,
                "to_stop_id": normalize_route(to_stop["gtfsId"]) if to_stop else None,
                "departure": (departure.get("estimated") or {}).get("time") or departure["scheduledTime"],
                "arrival": (arrival.get("estimated") or {}).get("time") or arrival["scheduledTime"],
                "scheduled_arrival": arrival.get("scheduledTime"),
                "realtime": bool(route_id and (departure.get("estimated") or arrival.get("estimated"))),
            })
        historical = historical_buffer(legs)
        start, end = datetime.fromisoformat(node["start"]), datetime.fromisoformat(node["end"])
        options.append({
            "departure": start, "arrival": end, "minutes": round((end - start).total_seconds() / 60),
            "live": any(leg["realtime"] for leg in legs), "historical_buffer_seconds": historical,
            "buffered_arrival": end + timedelta(seconds=historical) if historical is not None else None,
            "legs": legs,
        })
    options.sort(key=(lambda option: -option["departure"].timestamp()) if trip.arrive_by else
                 (lambda option: option["arrival"]))
    return {"origin": origin[2], "destination": destination[2], "options": options[:5]}


@router.post("/trip")
def trip_endpoint(trip: TripRequest):
    return plan_trip(trip)


def plan_itinerary(request):
    start = request.depart_at or datetime.now(timezone.utc)
    flexible = [index for index, visit in enumerate(request.visits) if visit.flexible]
    if len(flexible) > 3:
        raise HTTPException(422, "Choose up to three flexible stops per itinerary.")
    places = {name: resolve_place(name) for name in dict.fromkeys(
        [request.origin, *(visit.place for visit in request.visits)]
    )}

    @lru_cache(maxsize=60)
    def option(origin, destination, departure):
        if places[origin][:2] == places[destination][:2]:
            return departure, None
        results = plan_trip(
            TripRequest(origin=origin, destination=destination, depart_at=departure),
            places[origin], places[destination],
        )["options"]
        if not results:
            return None, None
        return results[0]["arrival"], results[0]

    def evaluate(order):
        origin, departure = request.origin, start
        visits, missed, late = [], 0, 0
        unreachable = None
        for index in order:
            visit = request.visits[index]
            arrival, trip = option(origin, visit.place, departure)
            if arrival is None:
                unreachable = visit.place
                break
            on_time = visit.arrive_by is None or arrival <= visit.arrive_by
            if not on_time:
                missed += 1
                late += (arrival - visit.arrive_by).total_seconds()
            visits.append({
                "place": visit.place, "deadline": visit.arrive_by, "minutes": visit.minutes,
                "on_time": on_time, "arrival": arrival, "trip": trip,
            })
            origin, departure = visit.place, arrival + timedelta(minutes=visit.minutes)
        score = (len(order) - len(visits), missed, late, departure)
        return score, {"visits": visits, "unreachable": unreachable}

    orders = []
    for rearranged in permutations(flexible):
        order = list(range(len(request.visits)))
        for slot, item in zip(flexible, rearranged):
            order[slot] = item
        orders.append(order)
    return min((evaluate(order) for order in orders), key=lambda result: result[0])[1]


@router.post("/itinerary")
def itinerary_endpoint(request: ItineraryRequest):
    return plan_itinerary(request)


@router.post("/chat")
def chat_endpoint(request: ChatRequest):
    api_key = os.getenv("OPENAI_API_KEY")
    tool = {
        "name": "plan_itinerary",
        "description": "Route a start and ordered visits. Only call with confirmed places and dates.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["origin", "depart_at", "visits"],
            "properties": {
                "origin": {"type": "string"},
                "depart_at": {"type": ["string", "null"]},
                "visits": {"type": "array", "maxItems": 6, "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["place", "arrive_by", "minutes", "flexible"],
                    "properties": {
                        "place": {"type": "string"},
                        "arrive_by": {"type": ["string", "null"]},
                        "minutes": {"type": "integer"},
                        "flexible": {"type": "boolean"},
                    },
                }},
            },
        },
        "strict": True,
    }
    current = datetime.now(BOSTON).isoformat(timespec="minutes")
    instructions = (
        f"You help plan MBTA itineraries in Greater Boston. Current Boston time is {current}. "
        "Ask a short clarification if origin, place, deadline or visit duration is ambiguous. "
        "Set flexible true only for stops the user says may be reordered. Convert requested Boston times to "
        "ISO 8601 with correct UTC offset, including the date. Use null for unspecified times. "
        "Use the tool for all routes and travel times. Never invent service, travel times or opening hours. "
        "The app displays the verified itinerary directly after a tool call."
    )
    if not api_key:
        return local_chat(request, current)
    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": os.getenv("TRANSITPULSE_CHAT_MODEL", "gpt-4.1-mini"),
                "messages": [{"role": "system", "content": instructions}]
                + [message.model_dump() for message in request.messages],
                "tools": [{"type": "function", "function": tool}],
                "parallel_tool_calls": False,
                "max_completion_tokens": 500,
            },
            timeout=20,
        )
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]
        calls = message.get("tool_calls") or []
        if not calls:
            return {"reply": message.get("content") or "Which stops and times should I use?", "itinerary": None}
        arguments = calls[0]["function"]
        if arguments["name"] != "plan_itinerary":
            raise ValueError("Unexpected planner tool")
        itinerary_request = ItineraryRequest.model_validate_json(arguments["arguments"])
    except (requests.RequestException, ValueError, KeyError, IndexError) as error:
        raise HTTPException(502, "The planning assistant is temporarily unavailable.") from error

    itinerary = plan_itinerary(itinerary_request)
    return {
        "reply": "Here’s the itinerary based on the current routing data. Check the arrival shown for each deadline.",
        "itinerary": itinerary,
    }


def local_chat(request, current):
    prompt = (
        'Extract an MBTA itinerary. Do not calculate routes. Return JSON with origin and visits '
        '(place, minutes, arrive_by). Unstated arrival deadline is null. Unstated visit duration is 0. '
        'Example: "From A, visit B for 10 minutes, then C" -> '
        '{"origin":"A","visits":[{"place":"B","minutes":10,"arrive_by":null},'
        '{"place":"C","minutes":0,"arrive_by":null}]}. '
        f'Current Boston time: {current}. Use ISO 8601 with date and UTC offset for stated times. '
        'Include depart_at only when a time was stated. Keep the given stop order, and add flexible:true only to stops the user explicitly permits reordering. '
        'When the user supplies a timestamp after "by", copy it into arrive_by for that place. '
        'Example: "From A to B by 2026-11-23T16:30:00-05:00" -> '
        '{"origin":"A","visits":[{"place":"B","minutes":0,"arrive_by":"2026-11-23T16:30:00-05:00"}]}. '
        'Include every stop mentioned, including the fixed final stop. If a place is missing, return JSON with one short question.'
    )
    try:
        response = requests.post(
            os.getenv("TRANSITPULSE_OLLAMA_URL", "http://127.0.0.1:11434/api/chat"),
            json={
                "model": os.getenv("TRANSITPULSE_OLLAMA_MODEL", "qwen2.5:1.5b"),
                "messages": [{"role": "system", "content": prompt}]
                + [message.model_dump() for message in request.messages],
                "format": "json", "stream": False, "keep_alive": "1m",
                "options": {"temperature": 0, "num_ctx": 2048, "num_predict": 240, "num_thread": 3, "repeat_penalty": 1.15},
            },
            timeout=60,
        )
        response.raise_for_status()
        request_data = json.loads(response.json()["message"]["content"])
        if not request_data.get("origin") or not request_data.get("visits"):
            return {"reply": request_data.get("question") or "Which stops and times should I use?", "itinerary": None}
        itinerary_request = ItineraryRequest.model_validate(request_data)
        user_text = " ".join(message.content for message in request.messages if message.role == "user")
        fixed_end = re.search(
            r"(?:^|[.!?]\s+)([^.!?]+?)\s+is (?:the |my )?fixed final stop\b",
            user_text, re.IGNORECASE,
        )
        if fixed_end:
            place = fixed_end[1].strip()
            remaining = [visit for visit in itinerary_request.visits if key(visit.place) != key(place)]
            fixed = next((visit for visit in itinerary_request.visits if key(visit.place) == key(place)), None)
            if fixed is None and len(remaining) >= 6:
                return {"reply": "Which visits should I keep in the six-stop itinerary?", "itinerary": None}
            if len(remaining) == 2 and re.search(r"\bboth are flexible\b", user_text, re.IGNORECASE):
                remaining = [visit.model_copy(update={"flexible": True}) for visit in remaining]
            fixed = fixed.model_copy(update={"flexible": False}) if fixed else Visit(place=place)
            itinerary_request.visits = [*remaining, fixed]
        for visit in itinerary_request.visits:
            explicit = re.search(
                re.escape(visit.place) + r"\s+by\s+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2}))",
                user_text, re.IGNORECASE,
            )
            if explicit:
                visit.arrive_by = datetime.fromisoformat(explicit[1])
        if re.search(r"\bby\s+(?:\d|noon\b|midnight\b)", user_text, re.IGNORECASE) and not any(
            visit.arrive_by for visit in itinerary_request.visits
        ):
            return {"reply": "Which stop has the deadline, and what date and Boston time should I use?", "itinerary": None}
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        raise HTTPException(502, "The local planning assistant is unavailable. You can use Multiple stops to plan manually.") from error
    return {
        "reply": "Here’s the itinerary based on MBTA schedules and available live updates.",
        "itinerary": plan_itinerary(itinerary_request),
    }
