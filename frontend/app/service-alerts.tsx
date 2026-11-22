import type { CSSProperties } from "react";

type ServiceAlert = {
  id: string;
  headline: string;
  effect: string | null;
};

function AlertList({ alerts, duplicate = false }: { alerts: ServiceAlert[]; duplicate?: boolean }) {
  return (
    <ul className="alert-headlines" aria-hidden={duplicate || undefined}>
      {alerts.map((alert) => (
        <li key={alert.id}>{alert.headline}</li>
      ))}
    </ul>
  );
}

export default async function ServiceAlerts({ route, station }: { route: string; station: string }) {
  let alerts: ServiceAlert[];
  try {
    const params = new URLSearchParams({ route, station });
    const response = await fetch(`http://127.0.0.1:8000/api/alerts?${params}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(12_000),
    });
    if (!response.ok) throw new Error("Alert feed unavailable");
    alerts = await response.json();
  } catch {
    return <p className="alert-status" role="status">MBTA service alerts are temporarily unavailable.</p>;
  }

  if (!alerts.length) {
    return <p className="alert-status">No current MBTA service alerts for this route and stop.</p>;
  }

  const duration = Math.max(22, alerts.reduce((total, alert) => total + alert.headline.length / 12 + 2, 0));

  return (
    <section className="service-alerts" aria-labelledby="service-alerts-heading">
      <input className="visually-hidden alert-pause" type="checkbox" id="pause-alert-ticker" />
      <div className="alert-bar">
        <h2 id="service-alerts-heading">MBTA service alerts</h2>
        <label className="alert-toggle" htmlFor="pause-alert-ticker">
          <span className="visually-hidden">Pause alert ticker</span>
          <span className="pause-label" aria-hidden="true">Pause</span>
          <span className="resume-label" aria-hidden="true">Resume</span>
        </label>
      </div>
      <div className="alert-window">
        <div className="alert-track" style={{ "--ticker-duration": `${duration}s` } as CSSProperties}>
          <AlertList alerts={alerts} />
          <AlertList alerts={alerts} duplicate />
        </div>
      </div>
      <details className="alert-details">
        <summary>Read all alerts ({alerts.length})</summary>
        <AlertList alerts={alerts} />
      </details>
    </section>
  );
}
