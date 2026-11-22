from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG
from pendulum import datetime
import json
from datetime import timedelta
from time import monotonic, sleep
from airflow.sdk import task

@task
def process_in_databricks(batch):
    import google.auth
    import requests
    from airflow.hooks.base import BaseHook
    from google.cloud import storage

    sources = ("open_meteo", "mbta_alerts")
    objects = batch["objects"]
    if not batch["bucket"] or not all(objects.get(source) for source in sources):
        raise ValueError("Both GCS uploads are required before starting Databricks.")

    timestamp = batch["capture_timestamp"]
    credentials, _ = google.auth.default()
    bucket = storage.Client(credentials=credentials).bucket(batch["bucket"])
    urls = {
        source: bucket.blob(objects[source]).generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=30),
            method="GET",
            credentials=credentials,
        )
        for source in sources
    }

    connection = BaseHook.get_connection("transitpulse_databricks")
    host = connection.host.rstrip("/")
    headers = {"Authorization": f"Bearer {connection.password}"}

    response = requests.post(
        f"{host}/api/2.0/secrets/put",
        headers=headers,
        json={
            "scope": "transitpulse-gcp",
            "key": f"batch-{timestamp}",
            "string_value": json.dumps(urls),
        },
        timeout=30,
    )
    response.raise_for_status()

    response = requests.post(
        f"{host}/api/2.2/jobs/run-now",
        headers=headers,
        json={
            "job_id": 238896861888979,
            "job_parameters": {"capture_timestamp": timestamp},
            "idempotency_token": f"transitpulse-{timestamp}",
        },
        timeout=30,
    )
    response.raise_for_status()
    run_id = response.json()["run_id"]
    print(f"Started Databricks run {run_id} for batch {timestamp}")

    deadline = monotonic() + 20 * 60
    while monotonic() < deadline:
        response = requests.get(
            f"{host}/api/2.2/jobs/runs/get",
            headers=headers,
            params={"run_id": run_id},
            timeout=30,
        )
        response.raise_for_status()
        state = response.json()["state"]

        if state["life_cycle_state"] in {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}:
            try:
                cleanup = requests.post(
                    f"{host}/api/2.0/secrets/delete",
                    headers=headers,
                    json={"scope": "transitpulse-gcp", "key": f"batch-{timestamp}"},
                    timeout=30,
                )
                cleanup.raise_for_status()
                print(f"Removed Databricks secret for batch {timestamp}")
            except requests.RequestException as error:
                print(f"Could not remove Databricks secret for {timestamp}: "
                      f"{type(error).__name__}")

        if state.get("result_state") == "SUCCESS":
            print(f"Databricks run {run_id} succeeded")
            return run_id

        if state["life_cycle_state"] in {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}:
            result = state.get("result_state") or state["life_cycle_state"]
            raise RuntimeError(f"Databricks run {run_id} ended with {result}")

        sleep(15)

    raise TimeoutError(f"Databricks run {run_id} did not finish within 20 minutes")


def read_databricks_batch(timestamp, query):
    from datetime import datetime

    import requests
    from airflow.hooks.base import BaseHook

    captured_at = datetime.strptime(timestamp, "%Y%m%dT%H%M%SZ").isoformat()
    connection = BaseHook.get_connection("transitpulse_databricks")
    host = connection.host.rstrip("/")
    headers = {"Authorization": f"Bearer {connection.password}"}

    response = requests.post(
        f"{host}/api/2.0/sql/statements",
        headers=headers,
        json={
            "warehouse_id": "03076a4c965d5e97",
            "statement": query,
            "parameters": [{"name": "captured_at", "value": captured_at}],
            "wait_timeout": "10s",
        },
        timeout=30,
    )
    response.raise_for_status()
    statement = response.json()
    statement_id = statement["statement_id"]

    deadline = monotonic() + 180
    while statement["status"]["state"] in {"PENDING", "RUNNING"}:
        if monotonic() >= deadline:
            raise TimeoutError(f"Databricks SQL statement {statement_id} timed out")
        sleep(5)
        response = requests.get(
            f"{host}/api/2.0/sql/statements/{statement_id}",
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        statement = response.json()

    state = statement["status"]["state"]
    if state != "SUCCEEDED":
        raise RuntimeError(f"Databricks SQL statement {statement_id} ended with {state}")

    result = statement.get("result", {})
    rows = result.get("data_array", [])
    manifest = statement.get("manifest", {})
    if (
        manifest.get("truncated")
        or result.get("next_chunk_index") is not None
        or manifest.get("total_row_count", len(rows)) != len(rows)
    ):
        raise RuntimeError(f"Databricks SQL statement {statement_id} returned an incomplete batch")

    return rows


@task
def load_weather_to_snowflake(batch, databricks_run_id):
    from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook

    timestamp = batch["capture_timestamp"]
    rows = read_databricks_batch(timestamp, """
        SELECT observed_at_local, timezone, temperature, temperature_unit,
               precipitation, precipitation_unit, observed_at_utc, captured_at_utc
        FROM workspace.default.transitpulse_weather_batches
        WHERE captured_at_utc = CAST(:captured_at AS TIMESTAMP_NTZ)
    """)
    if len(rows) != 1:
        raise ValueError(f"Expected one weather row for {timestamp}, got {len(rows)}")

    SnowflakeHook(snowflake_conn_id="transitpulse_snowflake").run(
        """
        MERGE INTO TRANSITPULSE.PUBLIC.TRANSITPULSE_WEATHER_BATCHES AS target
        USING (
            SELECT TO_TIMESTAMP_NTZ(%s) AS observed_at_local,
                   %s AS timezone,
                   TO_DOUBLE(%s) AS temperature,
                   %s AS temperature_unit,
                   TO_DOUBLE(%s) AS precipitation,
                   %s AS precipitation_unit,
                   TO_TIMESTAMP_NTZ(%s) AS observed_at_utc,
                   TO_TIMESTAMP_NTZ(%s) AS captured_at_utc
        ) AS source
        ON target.captured_at_utc = source.captured_at_utc
        WHEN NOT MATCHED THEN INSERT (
            observed_at_local, timezone, temperature, temperature_unit,
            precipitation, precipitation_unit, observed_at_utc, captured_at_utc
        ) VALUES (
            source.observed_at_local, source.timezone,
            source.temperature, source.temperature_unit,
            source.precipitation, source.precipitation_unit,
            source.observed_at_utc, source.captured_at_utc
        )
        """,
        parameters=tuple(rows[0]),
        autocommit=True,
    )
    print(f"Snowflake merge completed for {timestamp} from Databricks run {databricks_run_id}")


@task
def load_alerts_to_snowflake(batch, databricks_run_id):
    from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook

    timestamp = batch["capture_timestamp"]
    rows = read_databricks_batch(timestamp, """
        SELECT alert_id, header, effect, service_effect, severity, captured_at_utc
        FROM workspace.default.transitpulse_alert_batches
        WHERE captured_at_utc = CAST(:captured_at AS TIMESTAMP_NTZ)
    """)

    if not rows:
        print(f"No alerts to load for batch {timestamp}")
        return

    alert_ids = [row[0] for row in rows]
    if any(not alert_id for alert_id in alert_ids) or len(set(alert_ids)) != len(rows):
        raise ValueError(f"Missing or duplicate alert IDs in batch {timestamp}")

    SnowflakeHook(snowflake_conn_id="transitpulse_snowflake").run(
        """
        MERGE INTO TRANSITPULSE.PUBLIC.TRANSITPULSE_ALERT_BATCHES AS target
        USING (
            SELECT value[0]::VARCHAR AS alert_id,
                   STRIP_NULL_VALUE(value[1])::VARCHAR AS header,
                   STRIP_NULL_VALUE(value[2])::VARCHAR AS effect,
                   STRIP_NULL_VALUE(value[3])::VARCHAR AS service_effect,
                   STRIP_NULL_VALUE(value[4])::NUMBER(38, 0) AS severity,
                   TO_TIMESTAMP_NTZ(value[5]::VARCHAR) AS captured_at_utc
            FROM TABLE(FLATTEN(INPUT => PARSE_JSON(%s)))
        ) AS source
        ON target.alert_id = source.alert_id
           AND target.captured_at_utc = source.captured_at_utc
        WHEN NOT MATCHED THEN INSERT (
            alert_id, header, effect, service_effect, severity, captured_at_utc
        ) VALUES (
            source.alert_id, source.header, source.effect,
            source.service_effect, source.severity, source.captured_at_utc
        )
        """,
        parameters=(json.dumps(rows),),
        autocommit=True,
    )
    print(f"Processed {len(rows)} alert rows for {timestamp} from Databricks run {databricks_run_id}")

@task(retries=0)
def build_dbt_models():
    import requests
    from airflow.hooks.base import BaseHook
    from airflow.sdk import get_current_context

    connection = BaseHook.get_connection("transitpulse_dbt_cloud")
    host = connection.host.rstrip("/")
    api = f"{host}/api/v2/accounts/70506183177521"
    headers = {"Authorization": f"Token {connection.password}"}
    airflow_run_id = get_current_context()["run_id"]

    response = requests.post(
        f"{api}/jobs/70506183146814/run/",
        headers=headers,
        json={"cause": f"TransitPulse Airflow run {airflow_run_id}"},
        timeout=30,
    )
    response.raise_for_status()
    run_id = response.json()["data"]["id"]
    print(f"Started dbt Cloud run {run_id}")

    deadline = monotonic() + 10 * 60
    while monotonic() < deadline:
        response = requests.get(
            f"{api}/runs/{run_id}/", headers=headers, timeout=30
        )
        response.raise_for_status()
        status = response.json()["data"]["status"]

        if status == 10:
            print(f"dbt Cloud run {run_id} succeeded")
            return run_id
        if status in {20, 30, 40}:
            raise RuntimeError(f"dbt Cloud run {run_id} ended with status {status}")

        sleep(15)

    raise TimeoutError(f"dbt Cloud run {run_id} did not finish within 10 minutes")

with DAG(
    dag_id="transitpulse_ingest",
    start_date=datetime(2026, 11, 21, tz="UTC"),
    schedule="*/15 * * * *",
    catchup=False,
    max_active_runs=1,
) as dag:
    ingest_snapshots = BashOperator(
        task_id="ingest_snapshots",
        bash_command="python ingest.py",
        cwd="/opt/airflow/transitpulse",
        do_xcom_push=True,
        output_processor=json.loads,
    )
    databricks_run = process_in_databricks(ingest_snapshots.output)
    weather_load = load_weather_to_snowflake(ingest_snapshots.output, databricks_run)
    alerts_load = load_alerts_to_snowflake(ingest_snapshots.output, databricks_run)

    [weather_load, alerts_load] >> build_dbt_models()
