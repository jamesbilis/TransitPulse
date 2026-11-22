import Image from "next/image";
import { Suspense, type CSSProperties } from "react";
import NearbyScenes from "./nearby-scenes";
import RoutePicker, { routeName, type TransitRoute, type TransitStop } from "./route-picker";
import ServiceAlerts from "./service-alerts";
import TripPlanner from "./trip-planner";
import ThemeToggle from "./theme-toggle";
import WeatherCard from "./weather-card";

const stations = [
  {
    id: "south-station",
    stopId: "place-sstat",
    name: "South Station",
    neighborhood: "Downtown Boston",
    alt: "A southbound Red Line train arriving at South Station",
    photographer: "IliketrainsR211T",
    photo: "South_Station_Southbound_MBTA_Red_Line_Platform_(2),_June_2025.jpg",
    daylight: { photo: "South_Station,_Boston_front_entrance.jpg", author: "Billie Grace Ward", license: "by/2.0", label: "CC BY 2.0" },
    night: { photo: "Dewey_Square_and_South_Station_at_night,_November_2026.jpg", author: "Pi.1415926535", license: "by-sa/4.0", label: "CC BY-SA 4.0" },
  },
  {
    id: "park-street",
    stopId: "place-pktrm",
    name: "Park Street",
    neighborhood: "Boston Common",
    alt: "An Ashmont-bound Red Line train arriving at Park Street",
    photographer: "4300streetcar",
    photo: "Southbound_MBTA_Red_Line_train_at_Park_Street_November_2025.jpg",
    daylight: { photo: "Boston_Common_aerial.JPG", author: "Nick Allen", license: "by-sa/4.0", label: "CC BY-SA 4.0" },
    night: { photo: "Boston_Dusk.jpg", author: "walknboston", license: "by/2.0", label: "CC BY 2.0" },
  },
  {
    id: "harvard",
    stopId: "place-harsq",
    name: "Harvard",
    neighborhood: "Harvard Square, Cambridge",
    alt: "The stacked Red Line platforms at Harvard station",
    photographer: "4300streetcar",
    photo: "Harvard_station_platforms_from_above_August_2024.jpg",
    daylight: { photo: "Harvard_Square_Newsstand.jpg", author: "Fletcher", license: "by/4.0", label: "CC BY 4.0" },
    night: { photo: "Harvard_Yard_at_Night_03.jpg", author: "Meihe Chen", license: "by-sa/4.0", label: "CC BY-SA 4.0" },
  },
];

const redLine: TransitRoute = {
  id: "Red",
  type: 1,
  name: "Red Line",
  short_name: "",
  description: "Rapid Transit",
  color: "DA291C",
  text_color: "FFFFFF",
};

const redStops = stations.map(({ stopId, name }) => ({ id: stopId, name }));

function routeColor(hex: string, fallback: string) {
  return /^[0-9a-f]{6}$/i.test(hex) ? `#${hex}` : fallback;
}

type SearchParams = Promise<{ route?: string | string[]; station?: string | string[] }>;
type Arrival = { predicted_at: string; destination: string | null };

const bostonTime = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  hour: "numeric",
  minute: "2-digit",
  timeZoneName: "short",
});

async function fetchData<T>(path: string, timeout: number) {
  const response = await fetch(`http://127.0.0.1:8000${path}`, {
    cache: "no-store",
    signal: AbortSignal.timeout(timeout),
  });

  if (!response.ok) {
    throw new Error(`TransitPulse API returned ${response.status}`);
  }

  return {
    data: (await response.json()) as T,
    responseDate: Date.parse(response.headers.get("date") ?? ""),
  };
}

async function StationArrivals({ searchParams }: { searchParams: SearchParams }) {
  const { route: requestedRoute, station } = await searchParams;
  let routes = [redLine];
  let catalogUnavailable = false;
  try {
    const { data } = await fetchData<TransitRoute[]>("/api/routes", 12_000);
    if (data.length) routes = data;
    else catalogUnavailable = true;
  } catch {
    catalogUnavailable = true;
  }

  const route = routes.find((item) => item.id === requestedRoute)
    ?? routes.find((item) => item.id === "Red")
    ?? routes[0];
  let stops: TransitStop[] = route.id === "Red" ? redStops : [];
  let stopsUnavailable = false;
  try {
    const { data } = await fetchData<TransitStop[]>(`/api/routes/${encodeURIComponent(route.id)}/stops`, 12_000);
    if (data.length || route.id !== "Red") stops = data;
  } catch {
    stopsUnavailable = true;
  }

  const stopId = stations.find((item) => item.id === station)?.stopId ?? station;
  const selectedStop = stops.find((item) => item.id === stopId)
    ?? (route.id === "Red" ? stops.find((item) => item.id === "place-sstat") : undefined)
    ?? stops[0];
  const selected = stations.find((item) => item.stopId === selectedStop?.id);
  const style = {
    "--route-color": routeColor(route.color, "#356984"),
    "--route-text": routeColor(route.text_color, "#ffffff"),
  } as CSSProperties;
  let arrivals: Arrival[] | undefined;
  let checkedAt = NaN;

  try {
    if (selectedStop) {
      const params = new URLSearchParams({ route: route.id, station: selectedStop.id });
      const { data, responseDate } = await fetchData<{ arrivals: Arrival[] }>(
        `/api/arrivals?${params}`,
        12_000,
      );
      arrivals = data.arrivals;
      checkedAt = responseDate;
    }
  } catch {
    // The station selector and refresh control stay available during an outage.
  }

  const hasCheckedAt = Number.isFinite(checkedAt);

  return (
    <section className="card arrivals-card" data-station={selected?.id} data-route={route.id} style={style} aria-labelledby="arrivals-heading">
      <RoutePicker routes={routes} currentRoute={route} unavailable={catalogUnavailable} />
      {selected ? <figure className="station-photo">
        <div className="photo-frame">
          <Image
            src={`/stations/${selected.id}.webp`}
            alt={selected.alt}
            fill
            sizes="(min-width: 66rem) 640px, (min-width: 48rem) 62vw, 100vw"
          />
          <div className="photo-title">
            <p className="line-sign">{routeName(route)}</p>
            <h2>{selected.name}</h2>
            <p>{selected.neighborhood}</p>
          </div>
        </div>
        <figcaption>
          Photo by <a href={`https://commons.wikimedia.org/wiki/File:${encodeURIComponent(selected.photo)}`}>{selected.photographer}</a>
          {" · "}<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>
          {" · Resized and cropped"}
        </figcaption>
      </figure> : (
        <div className="route-hero">
          <span className="line-sign">{route.description || "MBTA"}</span>
          <h2>{routeName(route)}</h2>
          {selectedStop && <p>{selectedStop.name}</p>}
        </div>
      )}

      {route.id === "Red" && (
        <form className="station-picker" method="get" aria-label="Featured Red Line stations">
          <input type="hidden" name="route" value={route.id} />
          {[...stations].reverse().map((item) => (
            <button
              key={item.id}
              type="submit"
              name="station"
              value={item.stopId}
              aria-pressed={item.stopId === selectedStop?.id}
            >
              {item.name}
            </button>
          ))}
        </form>
      )}

      {selectedStop && (
        <form className="route-controls" method="get">
          <input type="hidden" name="route" value={route.id} />
          <label htmlFor="mbta-stop">Stop</label>
          <div className="route-control-row">
            <select id="mbta-stop" name="station" defaultValue={selectedStop.id}>
              {stops.map((stop) => <option key={stop.id} value={stop.id}>{stop.name}</option>)}
            </select>
            <button className="refresh" type="submit">Change stop</button>
          </div>
        </form>
      )}

      {selectedStop && (
        <Suspense fallback={<p className="alert-status" role="status">Checking MBTA service alerts…</p>}>
          <ServiceAlerts route={route.id} station={selectedStop.id} />
        </Suspense>
      )}

      <div className="section-heading">
        <div>
          <h2 id="arrivals-heading">Upcoming arrivals</h2>
        </div>
        <form method="get">
          <input type="hidden" name="route" value={route.id} />
          {selectedStop && <input type="hidden" name="station" value={selectedStop.id} />}
          <button className="refresh" type="submit">Refresh</button>
        </form>
      </div>

      {!selectedStop ? (
        <p className="message" role="status">{stopsUnavailable ? "Stops are temporarily unavailable. Try refreshing." : "MBTA has no stops listed for this route."}</p>
      ) : arrivals === undefined ? (
        <p className="message" role="status">Live arrivals are unavailable. Try refreshing.</p>
      ) : arrivals.length === 0 ? (
        <p className="message" role="status">MBTA has no live arrivals for this stop.</p>
      ) : (
        <ul className="arrivals-list" aria-label="Upcoming arrivals">
          {arrivals.map((arrival, index) => {
            const predicted = new Date(arrival.predicted_at);
            const minutes = Math.max(0, Math.ceil((predicted.getTime() - checkedAt) / 60_000));
            return (
              <li key={`${arrival.predicted_at}-${index}`}>
                <span className="stop-marker" aria-hidden="true" />
                <div className="arrival-detail">
                  <strong>{arrival.destination ?? "Destination unavailable"}</strong>
                  <time dateTime={arrival.predicted_at}>{bostonTime.format(predicted)}</time>
                </div>
                {hasCheckedAt && <span className="eta">{minutes <= 1 ? "Due" : `${minutes} min`}</span>}
              </li>
            );
          })}
        </ul>
      )}
      {arrivals !== undefined && hasCheckedAt && (
        <p className="checked">Checked at {bostonTime.format(checkedAt)}</p>
      )}
      {selected && <>
      <p className="scene-credit day-credit">
        Background by <a href={`https://commons.wikimedia.org/wiki/File:${encodeURIComponent(selected.daylight.photo)}`}>{selected.daylight.author}</a>
        {" · "}<a href={`https://creativecommons.org/licenses/${selected.daylight.license}/`}>{selected.daylight.label}</a>
        {" · Resized and cropped"}
      </p>
      <p className="scene-credit night-credit">
        Background by <a href={`https://commons.wikimedia.org/wiki/File:${encodeURIComponent(selected.night.photo)}`}>{selected.night.author}</a>
        {" · "}<a href={`https://creativecommons.org/licenses/${selected.night.license}/`}>{selected.night.label}</a>
        {" · Resized and cropped"}
      </p>
      </>}
      {!selected && selectedStop && (
        <Suspense fallback={null}>
          <NearbyScenes route={route.id} station={selectedStop.id} />
        </Suspense>
      )}
    </section>
  );
}

async function BostonWeather() {
  let weather: { temperature_c: number; observed_at: string; source?: string } | undefined;

  try {
    const { data } = await fetchData<{ temperature_c: number; observed_at: string; source?: string }>("/api/weather", 20_000);
    weather = data;
  } catch {
    // Arrivals remain usable when Snowflake weather is unavailable.
  }

  if (!weather) {
    return (
      <section className="card weather-card">
        <h2>Boston weather</h2>
        <p className="message" role="status">Weather is temporarily unavailable.</p>
      </section>
    );
  }

  return <WeatherCard temperatureC={weather.temperature_c} observedAt={weather.observed_at} fromOpenMeteo={weather.source === "open-meteo"} />;
}

export default function Home({ searchParams }: { searchParams: SearchParams }) {
  return (
    <main className="dashboard">
      <header className="masthead">
        <span className="brand-mark" aria-hidden="true"><i /></span>
        <div>
          <h1>Transit<span>Pulse</span></h1>
          <p>Greater Boston transit</p>
        </div>
        <div className="local-mark">
          <Image src="/massachusetts.png" width={623} height={396} sizes="(min-width: 58rem) 148px, (min-width: 24rem) 16vw, 61px" alt="Massachusetts outline with a dot marking Boston" />
        </div>
        <ThemeToggle />
      </header>

      <TripPlanner />

      <div className="dashboard-grid">
        <Suspense fallback={<p className="card loading" role="status">Loading live arrivals…</p>}>
          <StationArrivals searchParams={searchParams} />
        </Suspense>
        <Suspense fallback={<p className="card loading" role="status">Loading Boston weather…</p>}>
          <BostonWeather />
        </Suspense>
      </div>
    </main>
  );
}
