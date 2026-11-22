# TransitPulse trip planner

The local dashboard sends trip requests through Next.js to FastAPI. OpenTripPlanner
uses MBTA GTFS and OpenStreetMap plus the MBTA Trip Updates and Alerts feeds.
FastAPI resolves GTFS stop names and coordinates locally and uses Photon for
address or landmark searches. Set `TRANSITPULSE_GEOCODER_URL` to use a different
Photon instance or to an empty value to allow only stops and coordinates.

## Start the local router

The graph directory needs `mbta.gtfs.zip` and one Greater Boston `.osm.pbf`
extract. Keep the statewide extract outside the graph directory on low-memory hosts.

```bash
mkdir -p data/planner
curl -fL https://cdn.mbta.com/MBTA_GTFS.zip -o data/planner/mbta.gtfs.zip
osmium extract -b '-71.36,42.15,-70.80,42.57' massachusetts.osm.pbf -o data/planner/boston.osm.pbf
docker compose -f infra/planner/compose.yaml run --rm planner --build --save
docker compose -f infra/planner/compose.yaml up -d planner
```

The router stays on loopback port 8081. Start the existing FastAPI and Next.js
services as usual. Rebuild the graph when the static schedule changes.
The local walking map covers Greater Boston. Trips beginning or ending outside
that map may require a larger graph.

## Backtest and serve the historical model

```bash
.venv/bin/python -m pip install -r ml/requirements.txt
.venv/bin/python ml/train_reliability.py --days 14
```

The trainer downloads complete MBTA LAMP daily partitions, uses the scheduled
arrival included in each event, and holds out the latest service dates.
The first run used November 8–21, 2026. The held-out results were 266.3 seconds
MAE for schedules, 248.0 for historical medians, and 261.0 for XGBoost p50.
The XGBoost p90 covered 84.7% of held-out events. The dashboard keeps OTP’s
arrival as its primary estimate and offers the model spread as an illustrative
delay buffer for supported stops. The buffer applies to the last transit
arrival and does not estimate individual transfer risk.

## Enable the itinerary assistant

By default the assistant uses local Ollama with `qwen2.5:1.5b`. Install the
model with `ollama pull qwen2.5:1.5b`. You can override the local model with
`TRANSITPULSE_OLLAMA_MODEL`. To use OpenAI instead, set `OPENAI_API_KEY` in
FastAPI's environment. The key stays on the server.
The assistant extracts a structured plan and hands the routing work to FastAPI.
The manual itinerary form works independently of the chat provider.

## Historical data and experiment tracking

The optional Airflow planner archive DAGs reuse `TRANSITPULSE_GCS_BUCKET`.
The daily DAG stores GTFS by content hash and LAMP by service date.
The 15-minute DAG archives Trip Updates, Vehicle Positions, and full Alerts
messages with capture timestamps. OpenTripPlanner still polls its live feeds
directly. Both archival DAGs start paused so their bucket and credentials can
be verified before initiating captures.

In a Databricks Python environment with the ML dependencies installed, run the
same trainer and set `TRANSITPULSE_MLFLOW_EXPERIMENT` to an experiment path.
If configured, training logs the parameters, the holdout metrics, and all three
artifacts to MLflow. The local trainer runs without MLflow when the variable
is absent.

## Snowflake and dbt

A Snowflake administrator must run `infra/planner/warehouse/setup.sql` once.
Use the existing loader service account and GCP application credentials for
the load. The script requires `pyarrow`, `snowflake-connector-python`,
`google-cloud-storage`, and `requests`. Configure `TRANSITPULSE_GCS_BUCKET`,
`SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `TRANSITPULSE_SNOWFLAKE_KEY`, and the
key passphrase when required. Keep credentials in the process environment or
the existing secret store.

```bash
.venv/bin/python infra/planner/warehouse/load.py 2026-11-20
cd dbt
dbt build --select stg_planner_stop_events stg_planner_alert_scope
```

Pass `--alert-path` with the object name of a raw MBTA alerts JSON snapshot to
include active periods and affected routes and stops. The loader replaces a
service date in one Snowflake transaction. LAMP does not distinguish measured
and inferred timestamps in this public export, so present values are marked
`source_reported`.

## Flexible itineraries

Mark up to three visits as flexible. The planner compares permutations of
those slots using the router at each leg's actual departure time. Fixed
visits retain their positions. It favors completing all visits, meeting more
deadlines, and reducing lateness before breaking a tie by finish time.
