const bostonObservationTime = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  timeZoneName: "short",
});

export default function WeatherCard({
  temperatureC,
  observedAt,
  fromOpenMeteo = false,
}: {
  temperatureC: number;
  observedAt: string;
  fromOpenMeteo?: boolean;
}) {
  const temperatureF = (temperatureC * 9) / 5 + 32;

  return (
    <section className="card weather-card" aria-labelledby="weather-heading">
      <h2 id="weather-heading">Boston weather</h2>
      <fieldset className="weather-controls">
        <legend className="visually-hidden">Temperature unit</legend>
        <input className="visually-hidden" type="radio" name="temperature-unit" id="unit-c" />
        <input className="visually-hidden" type="radio" name="temperature-unit" id="unit-f" defaultChecked />
        <div className="unit-switch">
          <label htmlFor="unit-c">°C</label>
          <label htmlFor="unit-f">°F</label>
        </div>
        <p className="weather-reading" aria-live="polite">
          <span className="reading-c">{temperatureC.toFixed(1)}<small>°C</small></span>
          <span className="reading-f">{temperatureF.toFixed(1)}<small>°F</small></span>
        </p>
      </fieldset>
      <p className="observed">
        {fromOpenMeteo ? "Conditions at" : "Observed"}{" "}
        <time dateTime={observedAt}>
          {bostonObservationTime.format(new Date(observedAt))}
        </time>
        {fromOpenMeteo && <>{" · "}<a href="https://open-meteo.com/">Open-Meteo</a></>}
      </p>
    </section>
  );
}
