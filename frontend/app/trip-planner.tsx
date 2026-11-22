"use client";

import { useRef, useState, type FormEvent } from "react";

type Leg = { mode: string; from: string; to: string; route: string | null; departure: string; arrival: string };
type Option = { departure: string; arrival: string; minutes: number; legs: Leg[]; live: boolean; buffered_arrival: string | null };
type Trip = { origin: string; destination: string; options: Option[] };
type Itinerary = { visits: { place: string; deadline: string | null; minutes: number; on_time: boolean; arrival: string; trip: Option | null }[]; unreachable: string | null };
type Message = { role: "user" | "assistant"; content: string; itinerary?: Itinerary | null };

const dateTime = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short",
});
const displayTime = (value: string) => dateTime.format(new Date(value));
const isoTime = (value: FormDataEntryValue | null) => value ? new Date(String(value)).toISOString() : null;

async function send<T>(action: string, data: unknown) {
  const response = await fetch(`/api/planner/${action}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok) {
    throw new Error(typeof result.detail === "string" ? result.detail : "Check the places and times in your request.");
  }
  return result as T;
}

function TripOption({ option }: { option: Option }) {
  return (
    <div className="plan-option">
      <strong>{displayTime(option.arrival)} · {option.minutes} min</strong>
      <p>{option.live ? "Includes live estimates" : "Scheduled times"} · Departs {displayTime(option.departure)}</p>
      {option.buffered_arrival && <p>With historical delay buffer · {displayTime(option.buffered_arrival)}</p>}
      <ol>
        {option.legs.map((leg, index) => (
          <li key={index}>
            <strong>{leg.route ?? (leg.mode === "WALK" ? "Walk" : leg.mode)}</strong>
            <span>{leg.from} → {leg.to}</span>
            <small>{displayTime(leg.departure)} – {displayTime(leg.arrival)}</small>
          </li>
        ))}
      </ol>
    </div>
  );
}

function VisitResults({ itinerary }: { itinerary: Itinerary }) {
  return (
    <div className="plan-results">
      {itinerary.visits.map((visit, index) => (
        <details key={index} open={index === 0}>
          <summary>{visit.place} · {displayTime(visit.arrival)}{visit.deadline && (visit.on_time ? " · Meets deadline" : " · Misses deadline")}</summary>
          {visit.minutes > 0 && <p>{visit.minutes} minutes at this stop</p>}
          {visit.trip && <TripOption option={visit.trip} />}
        </details>
      ))}
      {itinerary.unreachable && <p>No route found to {itinerary.unreachable} for that departure.</p>}
    </div>
  );
}

export default function TripPlanner() {
  const [tab, setTab] = useState<"trip" | "itinerary" | "chat">("trip");
  const [visitCount, setVisitCount] = useState(2);
  const [preferBuffer, setPreferBuffer] = useState(false);
  const [trip, setTrip] = useState<Trip | null>(null);
  const [itinerary, setItinerary] = useState<Itinerary | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const originInput = useRef<HTMLInputElement>(null);

  function useLocation() {
    if (!navigator.geolocation) {
      setError("Location is unavailable on this connection. Enter a stop name or coordinates instead.");
      return;
    }
    navigator.geolocation.getCurrentPosition(({ coords }) => {
      if (originInput.current) originInput.current.value = `${coords.latitude.toFixed(6)}, ${coords.longitude.toFixed(6)}`;
      setError("");
    }, () => setError("Location could not be read. Enter a stop name or coordinates instead."), { timeout: 8000 });
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setPending(true);
    setError("");
    try {
      if (tab === "trip") {
        setTrip(null);
        const time = isoTime(data.get("time"));
        setTrip(await send<Trip>("trip", {
          origin: data.get("origin"), destination: data.get("destination"),
          [data.get("timing") === "arrive" ? "arrive_by" : "depart_at"]: time,
        }));
      } else if (tab === "itinerary") {
        setItinerary(null);
        const visits = Array.from({ length: visitCount }, (_, index) => ({
          place: data.get(`visit-${index}`),
          arrive_by: isoTime(data.get(`deadline-${index}`)),
          minutes: Number(data.get(`duration-${index}`) ?? 0),
          flexible: data.has(`flexible-${index}`),
        }));
        setItinerary(await send<Itinerary>("itinerary", { origin: data.get("origin"), depart_at: isoTime(data.get("time")), visits }));
      } else {
        const history: Message[] = [...messages, { role: "user", content: String(data.get("message")) }];
        const result = await send<{ reply: string; itinerary: Itinerary | null }>("chat", {
          messages: history.slice(-12).map(({ role, content }) => ({ role, content })),
        });
        setMessages([...history, { role: "assistant", content: result.reply, itinerary: result.itinerary }]);
        form.reset();
      }
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Could not plan this trip.");
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="card planner-card" aria-labelledby="planner-heading">
      <div className="section-heading"><h2 id="planner-heading">Plan a trip</h2></div>
      <div className="planner-tabs" aria-label="Planning tools">
        {([["trip", "One trip"], ["itinerary", "Multiple stops"], ["chat", "Ask TransitPulse"]] as const).map(([name, label]) => (
          <button className="refresh" key={name} type="button" disabled={pending} aria-pressed={tab === name} onClick={() => { setTab(name); setError(""); }}>{label}</button>
        ))}
      </div>
      {tab === "chat" && (
        <div className="planner-chat" aria-live="polite">
          {messages.map((message, index) => <div key={index}><strong>{message.role === "user" ? "You" : "TransitPulse"}</strong><p>{message.content}</p>{message.itinerary && <VisitResults itinerary={message.itinerary} />}</div>)}
        </div>
      )}
      <form className="planner-form" key={tab} onSubmit={submit}>
        {tab === "chat" ? (
          <label>What’s your plan?
            <textarea name="message" required maxLength={1800} rows={3} placeholder="I’m at Harvard and need to be at South Station by 5 pm, with a stop at Park Street." />
          </label>
        ) : (
          <>
            <label>Where are you starting? <input ref={originInput} name="origin" required maxLength={180} placeholder="Harvard" /></label>
            <button className="refresh planner-location" type="button" onClick={useLocation}>Use my location</button>
            {tab === "trip" && <label>Where are you going? <input name="destination" required maxLength={180} placeholder="North Station" /></label>}
            <div className="planner-time">
              {tab === "trip" && <label>Timing <select name="timing"><option value="depart">Depart at</option><option value="arrive">Arrive by</option></select></label>}
              <label>{tab === "trip" ? "Date and time (optional)" : "Departure time (optional)"} <input name="time" type="datetime-local" /></label>
            </div>
            {tab === "itinerary" && Array.from({ length: visitCount }, (_, index) => (
              <fieldset className="planner-visit" key={index}>
                <legend>Stop {index + 1}</legend>
                <label className="planner-flexible"><input type="checkbox" name={`flexible-${index}`} /> Can reorder this stop</label>
                <label>Place <input name={`visit-${index}`} required maxLength={180} /></label>
                <div className="planner-time">
                  <label>Arrive by (optional) <input name={`deadline-${index}`} type="datetime-local" /></label>
                  <label>Minutes there <input name={`duration-${index}`} type="number" min={0} max={480} defaultValue={0} /></label>
                </div>
              </fieldset>
            ))}
            {tab === "itinerary" && <p className="planner-help">Mark up to three stops as flexible. Fixed stops stay in their original positions.</p>}
            {tab === "itinerary" && <div className="planner-tabs">
              <button className="refresh" type="button" disabled={visitCount === 6} onClick={() => setVisitCount(visitCount + 1)}>Add stop</button>
              <button className="refresh" type="button" disabled={visitCount === 1} onClick={() => setVisitCount(visitCount - 1)}>Remove last stop</button>
            </div>}
            <p className="planner-help">Times you enter use your device’s time zone. Results display in Boston time. Address and landmark searches use Photon.</p>
          </>
        )}
        <button className="planner-submit" disabled={pending}>{pending ? "Planning…" : tab === "chat" ? "Send" : "Find a route"}</button>
      </form>
      {error && <p className="alert-status" role="status">{error}</p>}
      {tab === "trip" && trip && (
        <div className="plan-results" aria-live="polite">
          <h3>{trip.origin} → {trip.destination}</h3>
          {trip.options.length === 0 && <p>No route found for that time.</p>}
          {trip.options.some((option) => option.buffered_arrival) && (
            <label><input type="checkbox" checked={preferBuffer} onChange={(event) => setPreferBuffer(event.target.checked)} /> Compare by historical buffer</label>
          )}
          {(preferBuffer ? [...trip.options].sort((a, b) =>
            (a.buffered_arrival ? Date.parse(a.buffered_arrival) : Infinity)
            - (b.buffered_arrival ? Date.parse(b.buffered_arrival) : Infinity)
          ) : trip.options).map((option, index) => <TripOption key={index} option={option} />)}
        </div>
      )}
      {tab === "itinerary" && itinerary && <VisitResults itinerary={itinerary} />}
    </section>
  );
}
